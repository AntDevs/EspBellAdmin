import os
import time
import json
import re
import machine
from machine import I2S, Pin
import uasyncio as asyncio
import struct
import array
import logging

from hal.audio_utils import save_position_to_config, parse_wav_header, write_pcm_with_gain

# Логгер модуля аудиосопровождения UI
log = logging.getLogger("AUDIO")

try:
    import mp3dec
except ImportError:
    mp3dec = None

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

    def _write_pcm_with_gain(self, buf, num_bytes, gain):
        """
        Запись PCM данных в I2S с пропорциональным изменением громкости (gain: 0.0 .. 1.0).
        Используется сэмплирование array.array для подписанных 16-битных целых чисел.
        """
        log.debug("[TRACE ENTER] AudioPlayer._write_pcm_with_gain(num_bytes=%s, gain=%s)", num_bytes, gain)
        if self._stop or not self.i2s:
            log.debug("[TRACE EXIT] AudioPlayer._write_pcm_with_gain (stopped or no i2s)")
            return
        write_pcm_with_gain(self.i2s, buf, num_bytes, gain)
        log.debug("[TRACE EXIT] AudioPlayer._write_pcm_with_gain")

    async def _play_wav(self, f, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=0, start_pos_sec=0.0):
        """Воспроизведение WAV формата через I2S DMA с динамическим парсингом заголовков."""
        log.info("[TRACE ENTER] AudioPlayer._play_wav(start_pos_bytes=%s, start_pos_sec=%s)", start_pos_bytes, start_pos_sec)
        wav_fmt = parse_wav_header(f)
        if not wav_fmt:
            log.error("Файл не является валидным WAV!")
            log.info("[TRACE EXIT] AudioPlayer._play_wav -> False")
            return False

        channels, rate, bits, data_size, data_offset = wav_fmt
        log.info(f"Запуск WAV: {rate} Hz, {bits} bit, channels={channels}, data_size={data_size} B")

        bytes_per_sec = rate * channels * (bits // 8) if (rate and channels and bits) else 176400
        frame_align = channels * (bits // 8)
        self._init_i2s(rate=rate, bits=bits, channels=channels)

        # Расчет позиционирования по секундам, если байты равны 0
        if start_pos_bytes == 0 and start_pos_sec > 0:
            start_pos_bytes = data_offset + int(start_pos_sec * bytes_per_sec)

        # Переход к сохранённой позиции в байтах с выравниванием по границе сэмпла
        if start_pos_bytes > data_offset and start_pos_bytes < (data_offset + data_size):
            seek_pos = data_offset + ((start_pos_bytes - data_offset) // frame_align) * frame_align
            f.seek(seek_pos)
            log.info(f"Возобновление WAV с позиции {seek_pos} B / {start_pos_sec} сек (data offset: {data_offset} B)")

        bytes_per_ms = bytes_per_sec / 1000.0
        buf = bytearray(4096)
        bytes_read_total = f.tell() - data_offset

        while not self._stop:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)

            # Проверка глобального лимита времени
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

            # 1. Расчет затухания по достижению лимита времени (max_ms)
            if max_ms > 0 and fade_out_ms > 0:
                rem_ms = max_ms - elapsed_ms
                if rem_ms <= fade_out_ms:
                    gain = max(0.0, rem_ms / fade_out_ms)

            # 2. Расчет затухания к концу файла (для последнего повтора)
            elif is_last_repeat and fade_out_ms > 0 and data_size > 0:
                bytes_left = data_size - bytes_read_total
                if bytes_left <= 0:
                    gain = 0.0
                else:
                    ms_left = bytes_left / bytes_per_ms
                    if ms_left <= fade_out_ms:
                        gain = max(0.0, ms_left / fade_out_ms)

            self._write_pcm_with_gain(buf, num_read, gain)

            # Переключение контекста uasyncio на каждом шаге для оперативного отклика веб-сервера
            await asyncio.sleep_ms(1)

        log.info("[TRACE EXIT] AudioPlayer._play_wav -> True")
        return True

    async def _play_mp3(self, f, file_size, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=0, start_pos_sec=0.0):
        """Воспроизведение MP3 формата через C-модуль mp3dec с поддержкой плавного затухания."""
        log.info("[TRACE ENTER] AudioPlayer._play_mp3(start_pos_bytes=%s, start_pos_sec=%s)", start_pos_bytes, start_pos_sec)
        if not mp3dec:
            log.error("C-модуль mp3dec не найден в прошивке!")
            log.info("[TRACE EXIT] AudioPlayer._play_mp3 -> False")
            return False

        log.info(f"Запуск MP3 через mp3dec, размер файла: {file_size} B")
        bytes_per_sec = 16000

        if start_pos_bytes == 0 and start_pos_sec > 0:
            start_pos_bytes = int(start_pos_sec * bytes_per_sec)

        if start_pos_bytes > 0 and start_pos_bytes < file_size:
            f.seek(start_pos_bytes)
            log.info(f"Возобновление MP3 с позиции {start_pos_bytes} B / {start_pos_sec} сек")

        decoder = mp3dec.Decoder()
        pcm_buf = bytearray(4096)
        self._init_i2s(rate=44100, bits=16, channels=2)

        bytes_read_from_file = f.tell()

        while not self._stop:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)

            # Проверка лимита времени
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

            while decoder.has_pcm() and not self._stop:
                pcm_bytes = decoder.read_pcm(pcm_buf)
                if pcm_bytes > 0:
                    elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)
                    gain = 1.0

                    # Расчет затухания по лимиту времени
                    if max_ms > 0 and fade_out_ms > 0:
                        rem_ms = max_ms - elapsed_ms
                        if rem_ms <= fade_out_ms:
                            gain = max(0.0, rem_ms / fade_out_ms)

                    # Расчет затухания к концу MP3 файла
                    elif is_last_repeat and fade_out_ms > 0 and file_size > 0:
                        file_bytes_left = file_size - bytes_read_from_file
                        if file_bytes_left <= 0:
                            gain = 0.0
                        else:
                            ms_left = file_bytes_left / 16.0
                            if ms_left <= fade_out_ms:
                                gain = max(0.0, ms_left / fade_out_ms)

                    self._write_pcm_with_gain(pcm_buf, pcm_bytes, gain)
                    
                    # Переключение контекста uasyncio при выдаче порций PCM
                    await asyncio.sleep_ms(1)

        log.info("[TRACE EXIT] AudioPlayer._play_mp3 -> True")
        return True

    async def play(self, filepath="/media/bell.mp3", repeat_count=1, max_duration_sec=0, fade_out_ms=1000, resume_playback=False, start_pos_bytes=0, start_pos_sec=0.0):
        """
        Запуск воспроизведения аудиофайла.
        :param filepath: Путь к аудиофайлу
        :param repeat_count: Количество повторов трека
        :param max_duration_sec: Максимальная длительность воспроизведения в секундах (0 - без лимита)
        :param fade_out_ms: Длительность плавного затухания громкости в миллисекундах
        :param resume_playback: Возобновлять проигрывание с места остановки
        :param start_pos_bytes: Позиция смещения в байтах для старта
        :param start_pos_sec: Позиция возобновления в секундах
        """
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
                        await self._play_wav(f, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s)
                    else:
                        await self._play_mp3(f, file_size, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s)

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