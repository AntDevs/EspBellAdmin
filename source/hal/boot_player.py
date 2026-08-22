import os
import time
import machine
from machine import I2S, Pin
import logging
import uasyncio as asyncio

from hal.chip_monitor import ChipMonitor
from hal.audio_utils import save_position_to_config, stream_wav, stream_mp3

log = logging.getLogger("BOOT_AUDIO")

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
        """Инициализация I2S для автономного воспроизведения."""
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
        return self.i2s

    def deinit(self):
        log.info("[TRACE ENTER] StandaloneBootPlayer.deinit()")
        if self.i2s:
            try:
                self.i2s.deinit()
            except Exception:
                pass
            self.i2s = None
        log.info("[TRACE EXIT] StandaloneBootPlayer.deinit")

    def _save_position_to_config(self, pos_bytes, pos_sec=0.0):
        log.info("[TRACE ENTER] StandaloneBootPlayer._save_position_to_config(pos_bytes=%s, pos_sec=%s)", pos_bytes, pos_sec)
        save_position_to_config(pos_bytes, pos_sec, self.config)
        log.info("[TRACE EXIT] StandaloneBootPlayer._save_position_to_config")

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
                        res, final_b, final_s = asyncio.run(stream_wav(
                            f, self._init_i2s, start_ticks, max_ms, fade_out_ms, is_last_repeat,
                            start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s,
                            stop_checker=None, yield_ms=0, pos_container=self
                        ))
                    else:
                        res, final_b, final_s = asyncio.run(stream_mp3(
                            f, file_size, self._init_i2s, start_ticks, max_ms, fade_out_ms, is_last_repeat,
                            start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s,
                            stop_checker=None, yield_ms=0, pos_container=self
                        ))

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