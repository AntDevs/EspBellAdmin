import os
import time
import struct
import array
import machine
from machine import I2S, Pin
import logging

from hal.chip_monitor import ChipMonitor, EVENT_BOOT_REASON, EVENT_LOW_MEMORY
from logger import log_exception
from hal.audio_utils import save_position_to_config, parse_wav_header, write_pcm_with_gain

log = logging.getLogger("BOOT_AUDIO")

try:
    import mp3dec
except ImportError:
    mp3dec = None

class StandaloneBootPlayer:
    def __init__(self, bck_pin=15, ws_pin=16, sd_pin=17, i2s_id=0, config=None):
        log.info("[TRACE ENTER] StandaloneBootPlayer.__init__(bck=%s, ws=%s, sd=%s, i2s_id=%s)", bck_pin, ws_pin, sd_pin, i2s_id)
        self.bck_pin = bck_pin
        self.ws_pin = ws_pin
        self.sd_pin = sd_pin
        self.i2s_id = i2s_id
        self.i2s = None
        self.current_pos_bytes = 0
        self.current_pos_sec = 0.0
        self.config = config
        log.info("[TRACE EXIT] StandaloneBootPlayer.__init__")

    def _init_i2s(self, rate=44100, bits=16, channels=2):
        """Быстрая и чистая инициализация I2S без разрыва DMA потока."""
        log.info("[TRACE ENTER] StandaloneBootPlayer._init_i2s(rate=%s, bits=%s, channels=%s)", rate, bits, channels)
        if self.i2s:
            try:
                self.i2s.deinit()
            except Exception:
                pass
            self.i2s = None

        fmt = I2S.STEREO if channels == 2 else I2S.MONO

        log.info(f"Конфигурирование I2S (Rate={rate}Hz, Bits={bits}, Format={fmt})...")
        
        self.i2s = I2S(
            self.i2s_id,
            sck=Pin(self.bck_pin),
            ws=Pin(self.ws_pin),
            sd=Pin(self.sd_pin),
            mode=I2S.TX,
            bits=bits,
            format=fmt,
            rate=rate,
            ibuf=16384
        )

        # Мгновенный прогрев без блокирующих зависаний процессора
        try:
            self.i2s.write(bytearray(2048))
        except Exception:
            pass
        log.info("[TRACE EXIT] StandaloneBootPlayer._init_i2s")

    def deinit(self):
        log.info("[TRACE ENTER] StandaloneBootPlayer.deinit()")
        if self.i2s:
            try:
                self.i2s.deinit()
            except Exception:
                pass
            self.i2s = None
        log.info("[TRACE EXIT] StandaloneBootPlayer.deinit")

    def _write_pcm_with_gain(self, buf, num_bytes, gain):
        log.debug("[TRACE ENTER] StandaloneBootPlayer._write_pcm_with_gain(num_bytes=%s, gain=%s)", num_bytes, gain)
        write_pcm_with_gain(self.i2s, buf, num_bytes, gain)
        log.debug("[TRACE EXIT] StandaloneBootPlayer._write_pcm_with_gain")

    def _save_position_to_config(self, pos_bytes, pos_sec=0.0):
        log.info("[TRACE ENTER] StandaloneBootPlayer._save_position_to_config(pos_bytes=%s, pos_sec=%s)", pos_bytes, pos_sec)
        save_position_to_config(pos_bytes, pos_sec, self.config)
        log.info("[TRACE EXIT] StandaloneBootPlayer._save_position_to_config")

    def _play_wav_sync(self, f, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=0, start_pos_sec=0.0):
        log.info("[TRACE ENTER] StandaloneBootPlayer._play_wav_sync(start_pos_bytes=%s, start_pos_sec=%s)", start_pos_bytes, start_pos_sec)
        wav_fmt = parse_wav_header(f)
        if not wav_fmt:
            log.error("Файл не является валидным WAV!")
            log.info("[TRACE EXIT] StandaloneBootPlayer._play_wav_sync -> False")
            return False

        channels, rate, bits, data_size, data_offset = wav_fmt
        log.info(f"Параметры WAV: {rate} Hz, {bits} bit, channels={channels}, data={data_size} B")

        bytes_per_sec = rate * channels * (bits // 8) if (rate and channels and bits) else 176400
        frame_align = channels * (bits // 8)
        self._init_i2s(rate=rate, bits=bits, channels=channels)
        log.info("Начало передачи PCM аудиопотока в шину I2S...")

        # Вычисление позиционирования
        if start_pos_bytes == 0 and start_pos_sec > 0:
            start_pos_bytes = data_offset + int(start_pos_sec * bytes_per_sec)

        if start_pos_bytes > data_offset and start_pos_bytes < (data_offset + data_size):
            seek_pos = data_offset + ((start_pos_bytes - data_offset) // frame_align) * frame_align
            f.seek(seek_pos)
            log.info(f"Возобновление WAV (boot) с позиции {seek_pos} B / {start_pos_sec} сек (data offset: {data_offset} B)")

        bytes_per_ms = bytes_per_sec / 1000.0
        buf = bytearray(4096)
        bytes_read_total = f.tell() - data_offset

        while True:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)

            if max_ms > 0 and elapsed_ms >= max_ms:
                log.info(f"Достигнут лимит времени воспроизведения ({max_ms} ms)")
                break

            self.current_pos_bytes = f.tell()
            self.current_pos_sec = max(0.0, (self.current_pos_bytes - data_offset) / bytes_per_sec)

            num_read = f.readinto(buf)
            if num_read == 0:
                self.current_pos_bytes = 0
                self.current_pos_sec = 0.0
                break

            bytes_read_total += num_read
            gain = 1.0

            if max_ms > 0 and fade_out_ms > 0:
                rem_ms = max_ms - elapsed_ms
                if rem_ms <= fade_out_ms:
                    gain = max(0.0, rem_ms / fade_out_ms)
            elif is_last_repeat and fade_out_ms > 0 and data_size > 0:
                bytes_left = data_size - bytes_read_total
                if bytes_left <= 0:
                    gain = 0.0
                else:
                    ms_left = bytes_left / bytes_per_ms
                    if ms_left <= fade_out_ms:
                        gain = max(0.0, ms_left / fade_out_ms)

            self._write_pcm_with_gain(buf, num_read, gain)

        log.info("[TRACE EXIT] StandaloneBootPlayer._play_wav_sync -> True")
        return True

    def _play_mp3_sync(self, f, file_size, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=0, start_pos_sec=0.0):
        log.info("[TRACE ENTER] StandaloneBootPlayer._play_mp3_sync(start_pos_bytes=%s, start_pos_sec=%s)", start_pos_bytes, start_pos_sec)
        if not mp3dec:
            log.error("C-модуль mp3dec не найден в прошивке!")
            log.info("[TRACE EXIT] StandaloneBootPlayer._play_mp3_sync -> False")
            return False

        log.info(f"Параметры MP3 файла: размер {file_size} B")
        bytes_per_sec = 16000

        if start_pos_bytes == 0 and start_pos_sec > 0:
            start_pos_bytes = int(start_pos_sec * bytes_per_sec)

        if start_pos_bytes > 0 and start_pos_bytes < file_size:
            f.seek(start_pos_bytes)
            log.info(f"Возобновление MP3 (boot) с позиции {start_pos_bytes} B / {start_pos_sec} сек")

        self._init_i2s(rate=44100, bits=16, channels=2)
        log.info("Начало декодирования и передачи PCM аудиопотока в I2S...")
        
        decoder = mp3dec.Decoder()
        pcm_buf = bytearray(4096)
        bytes_read_from_file = f.tell()

        while True:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)

            if max_ms > 0 and elapsed_ms >= max_ms:
                log.info(f"Достигнут лимит времени воспроизведения ({max_ms} ms)")
                break

            self.current_pos_bytes = f.tell()
            self.current_pos_sec = self.current_pos_bytes / bytes_per_sec

            chunk = f.read(1024)
            if not chunk:
                self.current_pos_bytes = 0
                self.current_pos_sec = 0.0
                break

            bytes_read_from_file += len(chunk)
            decoder.write(chunk)

            while decoder.has_pcm():
                pcm_bytes = decoder.read_pcm(pcm_buf)
                if pcm_bytes > 0:
                    elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)
                    gain = 1.0

                    if max_ms > 0 and fade_out_ms > 0:
                        rem_ms = max_ms - elapsed_ms
                        if rem_ms <= fade_out_ms:
                            gain = max(0.0, rem_ms / fade_out_ms)
                    elif is_last_repeat and fade_out_ms > 0 and file_size > 0:
                        file_bytes_left = file_size - bytes_read_from_file
                        if file_bytes_left <= 0:
                            gain = 0.0
                        else:
                            ms_left = file_bytes_left / 16.0
                            if ms_left <= fade_out_ms:
                                gain = max(0.0, ms_left / fade_out_ms)

                    self._write_pcm_with_gain(pcm_buf, pcm_bytes, gain)

        log.info("[TRACE EXIT] StandaloneBootPlayer._play_mp3_sync -> True")
        return True

    def play(self, filepath, repeat_count=1, max_duration_sec=0, fade_out_ms=1000, resume_playback=False, start_pos_bytes=0, start_pos_sec=0.0):
        log.info("[TRACE ENTER] StandaloneBootPlayer.play(filepath=%s, repeat=%s, max_dur=%s, fade=%s, resume=%s, start_b=%s, start_s=%s)",
                 filepath, repeat_count, max_duration_sec, fade_out_ms, resume_playback, start_pos_bytes, start_pos_sec)
        try:
            file_size = os.stat(filepath)[6]
        except OSError:
            log.error(f"Файл {filepath} не найден!")
            log.info("[TRACE EXIT] StandaloneBootPlayer.play -> False (file not found)")
            return False

        initial_seek_bytes = start_pos_bytes if resume_playback else 0
        initial_seek_sec = start_pos_sec if resume_playback else 0.0
        self.current_pos_bytes = initial_seek_bytes
        self.current_pos_sec = initial_seek_sec

        max_ms = int(max_duration_sec * 1000) if max_duration_sec > 0 else 0
        start_ticks = time.ticks_ms()

        log.info(f"Открытие файла {filepath}...")
        log.info(f"Настройки: повторов={repeat_count}, лимит={max_duration_sec}s, fade={fade_out_ms}ms, resume={resume_playback}, start_pos={initial_seek_bytes}B ({initial_seek_sec}s)")

        try:
            for rep in range(repeat_count):
                elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)
                if max_ms > 0 and elapsed_ms >= max_ms:
                    log.info("Прерывание цикла повторов по лимиту времени.")
                    break

                is_last_repeat = (rep == repeat_count - 1)
                current_seek_b = initial_seek_bytes if rep == 0 else 0
                current_seek_s = initial_seek_sec if rep == 0 else 0.0
                log.info(f"Проигрывание стартовой итерации {rep + 1}/{repeat_count}...")

                with open(filepath, "rb") as f:
                    if filepath.lower().endswith(".wav"):
                        self._play_wav_sync(f, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s)
                    else:
                        self._play_mp3_sync(f, file_size, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s)

        except Exception as e:
            log.error(f"Ошибка автономного воспроизведения: {e}")
        finally:
            if resume_playback:
                self._save_position_to_config(self.current_pos_bytes, self.current_pos_sec)
            self.deinit()
            log.info("Автономное воспроизведение завершено, I2S освобождён.")

        log.info("[TRACE EXIT] StandaloneBootPlayer.play -> True")
        return True

def run_boot_audio(config):
    """Точка входа для запуска автономного аудио из main.py без создания помех Wi-Fi"""
    log.info("[TRACE ENTER] run_boot_audio(config_keys=%s)", list(config.keys()))
    chip_mon = ChipMonitor()
    chip_mon.diagnose_and_report()

    try:
        machine.freq(240000000)
    except Exception:
        pass

    media_dir = config.get('media_dir', '/media')
    target = config.get('target_filename', 'bell.wav')
    filepath = f"{media_dir}/{target}"

    try:
        os.stat(filepath)
    except OSError:
        log.warning(f"Файл {filepath} не найден, пропуск стартового аудио.")
        log.info("[TRACE EXIT] run_boot_audio -> file not found")
        return

    repeat_count = config.get('repeat_count', 1)
    max_duration_sec = config.get('max_play_duration_sec', 0)
    fade_out_ms = config.get('fade_out_ms', 1000)
    resume_playback = config.get('resume_playback', True)
    start_pos_bytes = config.get('last_play_pos_bytes', 0)
    start_pos_sec = config.get('last_play_pos_sec', 0)

    log.info("=== [HAL] Запуск автономной стартовой аудиосистемы по питанию ===")
    player = StandaloneBootPlayer(bck_pin=15, ws_pin=16, sd_pin=17, config=config)
    player.play(
        filepath=filepath,
        repeat_count=repeat_count,
        max_duration_sec=max_duration_sec,
        fade_out_ms=fade_out_ms,
        resume_playback=resume_playback,
        start_pos_bytes=start_pos_bytes,
        start_pos_sec=start_pos_sec
    )
    log.info("[TRACE EXIT] run_boot_audio -> completed")