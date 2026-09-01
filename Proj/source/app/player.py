import os
import logging
import uasyncio as asyncio

from hal.audio_utils import play_audio_track, deinit_hardware_i2s

log = logging.getLogger("AUDIO")

class AudioPlayer:
    """Асинхронный проигрыватель для вызовов из UI веб-сервера Microdot."""
    def __init__(self, config=None):
        log.info("[TRACE ENTER] AudioPlayer.__init__()")
        self.is_playing = False
        self._stop = False
        self.current_pos_bytes = 0
        self.current_pos_sec = 0.0
        self.config = config
        log.info("[TRACE EXIT] AudioPlayer.__init__")

    def deinit(self):
        log.info("[TRACE ENTER] AudioPlayer.deinit()")
        deinit_hardware_i2s()
        log.info("[TRACE EXIT] AudioPlayer.deinit")

    def stop(self):
        """Мгновенная остановка проигрывания и сброс DMA-буфера."""
        log.info("[TRACE ENTER] AudioPlayer.stop()")
        log.info("Запрос на мгновенную остановку воспроизведения.")
        self._stop = True
        self.deinit()
        log.info("[TRACE EXIT] AudioPlayer.stop()")

    async def play(self, filepath=None):
        log.info("[TRACE ENTER] AudioPlayer.play(filepath=%s)", filepath)
        if self.is_playing:
            log.info("Остановка текущего воспроизведения...")
            self.stop()
            for _ in range(20):
                if not self.is_playing:
                    break
                await asyncio.sleep_ms(50)

        self.is_playing = True
        self._stop = False

        try:
            res = await play_audio_track(
                mode='ui',
                filepath=filepath,
                ibuf=8192,
                stop_checker=lambda: self._stop,
                yield_ms=1,
                pos_container=self,
                config=self.config
            )
            log.info("[TRACE EXIT] AudioPlayer.play -> %s", res)
            return res
        finally:
            self.is_playing = False