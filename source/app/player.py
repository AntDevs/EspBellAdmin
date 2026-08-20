import os
import machine
from machine import I2S, Pin
import uasyncio as asyncio
import struct

try:
    import mp3dec
except ImportError:
    mp3dec = None

class AudioPlayer:
    def __init__(self, bck_pin15=15, lck_pin16=16, din_pin17=17, i2s_id=0):
        """
        :param bck_pin15: Пин BCK (Bit Clock) -> IO15
        :param lck_pin16: Пин LCK/LRCK (Word Select) -> IO16
        :param din_pin17: Пин DIN (Data Input) -> IO17
        """
        self.bck_pin15 = bck_pin15
        self.lck_pin16 = lck_pin16
        self.din_pin17 = din_pin17
        self.i2s_id = i2s_id
        self.i2s = None
        self.is_playing = False
        self._stop = False

    def _init_i2s(self, rate=44100, bits=16, channels=2):
        if self.i2s:
            try:
                self.i2s.deinit()
            except Exception:
                pass
        fmt = I2S.STEREO if channels == 2 else I2S.MONO

        # Передача 16 бит с увеличенным DMA-буфером (16 КБ) под MicroPython v1.23.0
        self.i2s = I2S(
            self.i2s_id,
            sck=Pin(self.bck_pin15),
            ws=Pin(self.lck_pin16),
            sd=Pin(self.din_pin17),
            mode=I2S.TX,
            bits=bits,
            format=fmt,
            rate=rate,
            ibuf=16384
        )

    def stop(self):
        self._stop = True

    async def _play_wav(self, f):
        """Воспроизведение WAV формата через I2S DMA."""
        header = f.read(44)
        if len(header) < 44 or header[:4] != b'RIFF' or header[8:12] != b'WAVE':
            print("[AUDIO ERROR] Файл не является валидным WAV!")
            return False

        channels = struct.unpack('<H', header[22:24])[0]
        rate = struct.unpack('<I', header[24:28])[0]
        bits = struct.unpack('<H', header[34:36])[0]

        print(f"[AUDIO] Запуск WAV: {rate} Hz, {bits} bit, channels={channels}")
        self._init_i2s(rate=rate, bits=bits, channels=channels)

        buf = bytearray(4096)
        yield_counter = 0
        while not self._stop:
            num_read = f.readinto(buf)
            if num_read == 0:
                break
            self.i2s.write(buf[:num_read])
            
            # Дозированное переключение контекста async для предотвращения опустошения DMA
            yield_counter += 1
            if yield_counter % 4 == 0:
                await asyncio.sleep_ms(1)
        return True

    async def _play_mp3(self, f):
        """Воспроизведение MP3 формата через C-модуль mp3dec."""
        if not mp3dec:
            print("[AUDIO ERROR] C-модуль mp3dec не найден в прошивке!")
            return False

        decoder = mp3dec.Decoder()
        pcm_buf = bytearray(4096)
        self._init_i2s(rate=44100, bits=16, channels=2)

        yield_counter = 0
        while not self._stop:
            chunk = f.read(1024)
            if not chunk:
                break
            
            decoder.write(chunk)
            while decoder.has_pcm() and not self._stop:
                pcm_bytes = decoder.read_pcm(pcm_buf)
                if pcm_bytes > 0:
                    self.i2s.write(pcm_buf[:pcm_bytes])
            
            yield_counter += 1
            if yield_counter % 2 == 0:
                await asyncio.sleep_ms(1)
        return True

    async def play(self, filepath="/media/bell.mp3"):
        if self.is_playing:
            print("[AUDIO] Остановка текущего воспроизведения...")
            self.stop()
            for _ in range(20):
                if not self.is_playing:
                    break
                await asyncio.sleep_ms(50)

        try:
            os.stat(filepath)
        except OSError:
            print(f"[AUDIO ERROR] Файл {filepath} не найден!")
            return False

        self.is_playing = True
        self._stop = False

        print(f"[AUDIO] Открытие файла {filepath}...")
        try:
            with open(filepath, "rb") as f:
                if filepath.lower().endswith(".wav"):
                    await self._play_wav(f)
                else:
                    await self._play_mp3(f)

        except Exception as e:
            print(f"[AUDIO ERROR] Ошибка воспроизведения: {e}")
        finally:
            self.is_playing = False
            if self.i2s:
                try:
                    self.i2s.deinit()
                except Exception:
                    pass
                self.i2s = None
            print("[AUDIO] Воспроизведение завершено")

        return True