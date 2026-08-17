import os
import machine
from machine import I2S, Pin
import uasyncio as asyncio

try:
    import mp3dec
except ImportError:
    mp3dec = None

class AudioPlayer:
    def __init__(self, sck_pin=4, ws_pin=5, sd_pin=6, i2s_id=0):
        self.sck_pin = sck_pin
        self.ws_pin = ws_pin
        self.sd_pin = sd_pin
        self.i2s_id = i2s_id
        self.i2s = None
        self.is_playing = False
        self._stop = False

    def _init_i2s(self, rate=44100, bits=16, channels=2):
        if self.i2s:
            self.i2s.deinit()
        fmt = I2S.STEREO if channels == 2 else I2S.MONO
        self.i2s = I2S(
            self.i2s_id,
            sck=Pin(self.sck_pin),
            ws=Pin(self.ws_pin),
            sd=Pin(self.sd_pin),
            mode=I2S.TX,
            bits=bits,
            format=fmt,
            rate=rate,
            ibuf=8192
        )

    def stop(self):
        self._stop = True

    async def play(self, filepath="/media/bell.mp3"):
        if self.is_playing:
            print("Воспроизведение завершено, останавливаем текущий трек...?")
            self.stop()
            await asyncio.sleep_ms(100)

        if not mp3dec:
            print("[AUDIO ERROR] C-модуль mp3dec не встроен в прошивку!")
            return False

        try:
            os.stat(filepath)
        except OSError:
            print(f"[AUDIO ERROR] Файл {filepath} не найден!")
            return False

        self.is_playing = True
        self._stop = False
        
        decoder = mp3dec.Decoder()
        pcm_buf = bytearray(4096)
        self._init_i2s()

        try:
            with open(filepath, "rb") as f:
                while not self._stop:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    
                    decoder.write(chunk)
                    while decoder.has_pcm():
                        pcm_bytes = decoder.read_pcm(pcm_buf)
                        if pcm_bytes > 0:
                            self.i2s.write(pcm_buf[:pcm_bytes])
                    
                    await asyncio.sleep_ms(0)

        except Exception as e:
            print(f"[AUDIO ERROR] Ошибка воспроизведения: {e}")
        finally:
            self.is_playing = False
            if self.i2s:
                self.i2s.deinit()
                self.i2s = None
            print("[AUDIO] Воспроизведение завершено")

        print("Воспроизведение текущий трек...")
        return True