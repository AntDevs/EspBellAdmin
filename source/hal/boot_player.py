import os
import time
import struct
import array
import machine
from machine import I2S, Pin
import logging

from hal.chip_monitor import ChipMonitor, EVENT_BOOT_REASON, EVENT_LOW_MEMORY
from logger import log_exception

log = logging.getLogger("BOOT_AUDIO")

try:
    import mp3dec
except ImportError:
    mp3dec = None

class StandaloneBootPlayer:
    def __init__(self, bck_pin=15, ws_pin=16, sd_pin=17, i2s_id=0):
        self.bck_pin = bck_pin
        self.ws_pin = ws_pin
        self.sd_pin = sd_pin
        self.i2s_id = i2s_id
        self.i2s = None

    def _init_i2s(self, rate=44100, bits=16, channels=2):
        """Быстрая и чистая инициализация I2S без разрыва DMA потока."""
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

    def deinit(self):
        if self.i2s:
            try:
                self.i2s.deinit()
            except Exception:
                pass
            self.i2s = None

    def _write_pcm_with_gain(self, buf, num_bytes, gain):
        try:
            if gain >= 0.99:
                self.i2s.write(buf[:num_bytes])
            elif gain <= 0.01:
                self.i2s.write(bytearray(num_bytes))
            else:
                arr = array.array('h', memoryview(buf)[:num_bytes])
                for i in range(len(arr)):
                    arr[i] = int(arr[i] * gain)
                self.i2s.write(arr)
        except Exception as e:
            log.warning(f"Ошибка записи PCM: {e}")

    def _play_wav_sync(self, f, start_ticks, max_ms, fade_out_ms, is_last_repeat):
        riff_hdr = f.read(12)
        if len(riff_hdr) < 12 or riff_hdr[:4] != b'RIFF' or riff_hdr[8:12] != b'WAVE':
            log.error("Файл не является валидным WAV!")
            return False

        channels = 2
        rate = 44100
        bits = 16
        data_size = 0

        while True:
            chunk_hdr = f.read(8)
            if len(chunk_hdr) < 8:
                break
            chunk_id = chunk_hdr[:4]
            chunk_size = struct.unpack('<I', chunk_hdr[4:8])[0]

            if chunk_id == b'fmt ':
                fmt_data = f.read(chunk_size)
                if len(fmt_data) >= 14:
                    channels = struct.unpack('<H', fmt_data[2:4])[0]
                    rate = struct.unpack('<I', fmt_data[4:8])[0]
                    if len(fmt_data) >= 16:
                        bits = struct.unpack('<H', fmt_data[14:16])[0]
            elif chunk_id == b'data':
                data_size = chunk_size
                break
            else:
                try:
                    f.seek(chunk_size, 1)
                except Exception:
                    rem = chunk_size
                    while rem > 0:
                        to_read = min(1024, rem)
                        f.read(to_read)
                        rem -= to_read

        log.info(f"Параметры WAV: {rate} Hz, {bits} bit, channels={channels}, data={data_size} B")

        self._init_i2s(rate=rate, bits=bits, channels=channels)
        log.info("Начало передачи PCM аудиопотока в шину I2S...")

        bytes_per_ms = (rate * channels * (bits // 8)) / 1000.0 if (rate and channels and bits) else 176.4
        buf = bytearray(4096)
        bytes_read_total = 0

        while True:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)

            if max_ms > 0 and elapsed_ms >= max_ms:
                log.info(f"Достигнут лимит времени воспроизведения ({max_ms} ms)")
                break

            num_read = f.readinto(buf)
            if num_read == 0:
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

        return True

    def _play_mp3_sync(self, f, file_size, start_ticks, max_ms, fade_out_ms, is_last_repeat):
        if not mp3dec:
            log.error("C-модуль mp3dec не найден в прошивке!")
            return False

        log.info(f"Параметры MP3 файла: размер {file_size} B")
        self._init_i2s(rate=44100, bits=16, channels=2)
        log.info("Начало декодирования и передачи PCM аудиопотока в I2S...")
        
        decoder = mp3dec.Decoder()
        pcm_buf = bytearray(4096)
        bytes_read_from_file = 0

        while True:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)

            if max_ms > 0 and elapsed_ms >= max_ms:
                log.info(f"Достигнут лимит времени воспроизведения ({max_ms} ms)")
                break

            chunk = f.read(1024)
            if not chunk:
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

        return True

    def play(self, filepath, repeat_count=1, max_duration_sec=0, fade_out_ms=1000):
        try:
            file_size = os.stat(filepath)[6]
        except OSError:
            log.error(f"Файл {filepath} не найден!")
            return False

        max_ms = int(max_duration_sec * 1000) if max_duration_sec > 0 else 0
        start_ticks = time.ticks_ms()

        log.info(f"Открытие файла {filepath}...")
        log.info(f"Настройки: повторов={repeat_count}, лимит={max_duration_sec}s, fade={fade_out_ms}ms")

        try:
            for rep in range(repeat_count):
                elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)
                if max_ms > 0 and elapsed_ms >= max_ms:
                    log.info("Прерывание цикла повторов по лимиту времени.")
                    break

                is_last_repeat = (rep == repeat_count - 1)
                log.info(f"Проигрывание стартовой итерации {rep + 1}/{repeat_count}...")

                with open(filepath, "rb") as f:
                    if filepath.lower().endswith(".wav"):
                        self._play_wav_sync(f, start_ticks, max_ms, fade_out_ms, is_last_repeat)
                    else:
                        self._play_mp3_sync(f, file_size, start_ticks, max_ms, fade_out_ms, is_last_repeat)

        except Exception as e:
            log.error(f"Ошибка автономного воспроизведения: {e}")
        finally:
            self.deinit()
            log.info("Автономное воспроизведение завершено, I2S освобождён.")

        return True

def run_boot_audio(config):
    """Точка входа для запуска автономного аудио из main.py без создания помех Wi-Fi"""
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
        return

    repeat_count = config.get('repeat_count', 1)
    max_duration_sec = config.get('max_play_duration_sec', 0)
    fade_out_ms = config.get('fade_out_ms', 1000)

    log.info("=== [HAL] Запуск автономной стартовой аудиосистемы по питанию ===")
    player = StandaloneBootPlayer(bck_pin=15, ws_pin=16, sd_pin=17)
    player.play(
        filepath=filepath,
        repeat_count=repeat_count,
        max_duration_sec=max_duration_sec,
        fade_out_ms=fade_out_ms
    )