import os
import logging
import uasyncio as asyncio

from hal.chip_monitor import ChipMonitor
from hal.audio_utils import play_audio_track, deinit_hardware_i2s

log = logging.getLogger("BOOT_AUDIO")

class StandaloneBootPlayer:
    """Автономный аудиоплеер уровня HAL."""
    def __init__(self, config=None):
        log.info("[TRACE ENTER] StandaloneBootPlayer.__init__()")
        self.current_pos_bytes = 0
        self.current_pos_sec = 0.0
        self.config = config
        log.info("[TRACE EXIT] StandaloneBootPlayer.__init__")

    def deinit(self):
        log.info("[TRACE ENTER] StandaloneBootPlayer.deinit()")
        deinit_hardware_i2s()
        log.info("[TRACE EXIT] StandaloneBootPlayer.deinit")

    def play(self, filepath=None):
        log.info("[TRACE ENTER] StandaloneBootPlayer.play(filepath=%s)", filepath)
        res = asyncio.run(play_audio_track(
            mode='boot',
            filepath=filepath,
            ibuf=16384,
            pos_container=self,
            config=self.config
        ))
        log.info("[TRACE EXIT] StandaloneBootPlayer.play -> %s", res)
        return res

def run_boot_audio(config):
    """Точка входа для запуска автономного аудио из main.py"""
    log.info("[TRACE ENTER] run_boot_audio()")

    # test anton rem 1
    # chip_mon = ChipMonitor()
    # chip_mon.diagnose_and_report()

    try:
        import machine
        machine.freq(240000000)
    except Exception:
        pass

    log.info("=== [HAL] Запуск автономной стартовой аудиосистемы по питанию ===")
    player = StandaloneBootPlayer(config=config)
    player.play()
    log.info("[TRACE EXIT] run_boot_audio -> completed")