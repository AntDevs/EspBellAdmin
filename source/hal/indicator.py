import machine
import neopixel
import logging

log = logging.getLogger("INDICATOR")

def set_led_color(r, g, b, pin_num=48):
    """Установка цвета встроенного адресованного светодиода WS2812 (NeoPixel)."""
    log.info("[TRACE ENTER] set_led_color(r=%s, g=%s, b=%s, pin=%s)", r, g, b, pin_num)
    try:
        pin = machine.Pin(pin_num, machine.Pin.OUT)
        np = neopixel.NeoPixel(pin, 1)
        np[0] = (r, g, b)
        np.write()
        log.info("Цвет LED успешно обновлён на RGB(%s, %s, %s)", r, g, b)
    except Exception as e:
        log.warning(f"Не удалось установить цвет LED (Pin {pin_num}): {e}")
    log.info("[TRACE EXIT] set_led_color")

def set_moonlight_color(pin_num=48):
    """Установка мягкого голубого лунного цвета (Moonlight Blue)."""
    log.info("[TRACE ENTER] set_moonlight_color(pin_num=%s)", pin_num)
    # Голубой лунный цвет (soft pale cyan-blue) с комфортной яркостью
    set_led_color(0, 45, 90, pin_num=pin_num)
    log.info("[TRACE EXIT] set_moonlight_color")