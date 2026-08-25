import machine
import neopixel
import logging
import uasyncio as asyncio

log = logging.getLogger("INDICATOR")

# Глобальное состояние режима индикации ("police", "moonlight", "off")
_current_mode = "police"

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
    try:
        set_led_color(0, 45, 90, pin_num=pin_num)
        log.info("Установлен небесно-голубой цвет индикатора.")
    except Exception as e:
        log.warning(f"Ошибка установки лунного цвета: {e}")
    log.info("[TRACE EXIT] set_moonlight_color")

def set_led_mode(mode):
    """Переключение глобального состояния светодиодной индикации."""
    global _current_mode
    log.info("[TRACE ENTER] set_led_mode(mode=%s)", mode)
    try:
        _current_mode = mode
        log.info(f"[INDICATOR] Режим индикации успешно переключен на: '{mode}'")
    except Exception as e:
        log.warning(f"Сбой смены режима индикации: {e}")
    log.info("[TRACE EXIT] set_led_mode")

async def start_led_loop(pin_num=48):
    """
    Фоновый асинхронный цикл управления светодиодом.
    Динамически отрабатывает текущий режим без создания дублирующих задач.
    """
    global _current_mode
    log.info("[TRACE ENTER] start_led_loop(pin_num=%s)", pin_num)
    try:
        pin = machine.Pin(pin_num, machine.Pin.OUT)
        np = neopixel.NeoPixel(pin, 1)

        while True:
            if _current_mode == "police":
                # Серия вспышек красного стробоскопа
                np[0] = (255, 0, 0)
                np.write()
                await asyncio.sleep_ms(80)
                np[0] = (0, 0, 0)
                np.write()
                await asyncio.sleep_ms(60)
                np[0] = (255, 0, 0)
                np.write()
                await asyncio.sleep_ms(80)
                np[0] = (0, 0, 0)
                np.write()
                await asyncio.sleep_ms(100)

                if _current_mode != "police":
                    continue

                # Серия вспышек синего стробоскопа
                np[0] = (0, 0, 255)
                np.write()
                await asyncio.sleep_ms(80)
                np[0] = (0, 0, 0)
                np.write()
                await asyncio.sleep_ms(60)
                np[0] = (0, 0, 255)
                np.write()
                await asyncio.sleep_ms(80)
                np[0] = (0, 0, 0)
                np.write()
                await asyncio.sleep_ms(200)

            elif _current_mode == "moonlight":
                # Небесно-голубой постоянный цвет (soft pale cyan-blue)
                np[0] = (0, 45, 90)
                np.write()
                await asyncio.sleep(1)

            else:
                np[0] = (0, 0, 0)
                np.write()
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        log.info("[INDICATOR] Задача управления LED отменена.")
    except Exception as e:
        log.error(f"Сбой в работе индикатора LED: {e}")
    log.info("[TRACE EXIT] start_led_loop")