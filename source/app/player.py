import os
import time
import machine
from machine import I2S, Pin
import uasyncio as asyncio
import logging

from hal.audio_utils import save_position_to_config, stream_wav, stream_mp3

log = logging.getLogger("AUDIO")

class AudioPlayer:
    def __init__(self, bck_pin15=15, lck_pin16=16, din_pin17=17, i2s_id=0, config=None):
        """
        Конструктор аудиоплеера I2S DAC.
        :param bck_pin15: Пин BCK (Bit Clock) -> IO15
        :param lck_pin16: Пин LCK/LRCK (Word Select) -> IO16
        :param din_pin17: Пин DIN (Data Input) -> IO17
        :param i2s_id: Идентификатор аппаратной шины I2S (0 или 1)
        """
        log.info("[TRACE ENTER] AudioPlayer.__init__(bck=%s, lck=%s, din=%s, i2s_id=%s)", bck_pin15, lck_pin16, din_pin17, i2s_id)
        self.bck_pin15 = bck_pin15
        self.lck_pin16 = lck_pin16
        self.din_pin17 = din_pin17
        self.i2s_id = i2s_id
        self.i2s = None
        self.is_playing = False
        self._stop = False
        self.current_pos_bytes = 0
        self.current_pos_sec = 0.0
        self.config = config
        log.info("[TRACE EXIT] AudioPlayer.__init__")

    def _init_i2s(self, rate=44100, bits=16, channels=2):
        """Инициализация и конфигурирование DMA-буфера шины I2S."""
        log.info("[TRACE ENTER] AudioPlayer._init_i2s(rate=%s, bits=%s, channels=%s)", rate, bits, channels)
        if self.i2s:
            try:
                self.i2s.deinit()
            except Exception:
                pass
        fmt = I2S.STEREO if channels == 2 else I2S.MONO

        # Передача 16 бит с оптимизированным DMA-буфером (8 КБ) под MicroPython v1.23.0
        self.i2s = I2S(
            self.i2s_id,
            sck=Pin(self.bck_pin15),
            ws=Pin(self.lck_pin16),
            sd=Pin(self.din_pin17),
            mode=I2S.TX,
            bits=bits,
            format=fmt,
            rate=rate,
            ibuf=8192
        )
        
        # Прогрев и захват тактовой частоты (PLL Lock) внешнего ЦАП PCM5102A для предотвращения щелчков
        try:
            silence = bytearray(1024)
            self.i2s.write(silence)
        except Exception:
            pass
        log.info("[TRACE EXIT] AudioPlayer._init_i2s")
        return self.i2s

    def stop(self):
        """Мгновенная остановка проигрывания и сброс DMA-буфера."""
        log.info("[TRACE ENTER] AudioPlayer.stop()")
        log.info("Запрос на мгновенную остановку воспроизведения.")
        self._stop = True
        if self.i2s:
            try:
                self.i2s.deinit()
            except Exception:
                pass
            self.i2s = None
        log.info("[TRACE EXIT] AudioPlayer.stop()")

    def _save_position_to_config(self, pos_bytes, pos_sec=0.0):
        """Сохранение позиции остановки воспроизведения в config.json без потери комментариев."""
        log.info("[TRACE ENTER] AudioPlayer._save_position_to_config(pos_bytes=%s, pos_sec=%s)", pos_bytes, pos_sec)
        save_position_to_config(pos_bytes, pos_sec, self.config)
        log.info("[TRACE EXIT] AudioPlayer._save_position_to_config")

    async def play(self, filepath="/media/bell.mp3", repeat_count=1, max_duration_sec=0, fade_out_ms=1000, resume_playback=False, start_pos_bytes=0, start_pos_sec=0.0):
        log.info("[TRACE ENTER] AudioPlayer.play(filepath=%s, repeat=%s, max_dur=%s, fade=%s, resume=%s, start_b=%s, start_s=%s)",
                 filepath, repeat_count, max_duration_sec, fade_out_ms, resume_playback, start_pos_bytes, start_pos_sec)
        if self.is_playing:
            log.info("Остановка текущего воспроизведения...")
            self.stop()
            for _ in range(20):
                if not self.is_playing:
                    break
                await asyncio.sleep_ms(50)

        try:
            file_size = os.stat(filepath)[6]
        except OSError:
            log.error(f"Файл {filepath} не найден!")
            log.info("[TRACE EXIT] AudioPlayer.play -> False (file not found)")
            return False

        self.is_playing = True
        self._stop = False
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
                if self._stop:
                    log.info("Воспроизведение прервано пользователем.")
                    break

                elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)
                if max_ms > 0 and elapsed_ms >= max_ms:
                    log.info("Прерывание цикла повторов по лимиту времени.")
                    break

                is_last_repeat = (rep == repeat_count - 1)
                current_seek_b = initial_seek_bytes if rep == 0 else 0
                current_seek_s = initial_seek_sec if rep == 0 else 0.0
                log.info(f"Проигрывание итерации {rep + 1}/{repeat_count}...")

                with open(filepath, "rb") as f:
                    if filepath.lower().endswith(".wav"):
                        res, final_b, final_s = await stream_wav(
                            f, self._init_i2s, start_ticks, max_ms, fade_out_ms, is_last_repeat,
                            start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s,
                            stop_checker=lambda: self._stop, yield_ms=1, pos_container=self
                        )
                    else:
                        res, final_b, final_s = await stream_mp3(
                            f, file_size, self._init_i2s, start_ticks, max_ms, fade_out_ms, is_last_repeat,
                            start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s,
                            stop_checker=lambda: self._stop, yield_ms=1, pos_container=self
                        )

        except Exception as e:
            log.error(f"Ошибка воспроизведения: {e}")
        finally:
            self.is_playing = False
            # Сохраняем текущее положение (будь то ручная остановка или прерывание по лимиту времени)
            final_pos_bytes = self.current_pos_bytes
            final_pos_sec = self.current_pos_sec
            if resume_playback:
                self._save_position_to_config(final_pos_bytes, final_pos_sec)
                
            if self.i2s:
                try:
                    self.i2s.deinit()
                except Exception:
                    pass
                self.i2s = None
            log.info("Воспроизведение завершено")

        log.info("[TRACE EXIT] AudioPlayer.play -> True")
        return True