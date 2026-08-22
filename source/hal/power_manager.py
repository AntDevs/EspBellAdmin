import io
import sys
import time
import machine
import logging
import uasyncio as asyncio

# Единственная точка настройки номера пина питания для всего проекта
POWER_PIN = 4

log = logging.getLogger("POWER_MGR")


def hold_power_early():
    """
    Быстрый вызов для boot.py.
    Защелкивает реле на самом раннем этапе (до инициализации логгеров).
    """
    try:
        p = machine.Pin(POWER_PIN, machine.Pin.OUT)
        p.value(1)
        # На этапе boot.py логгер еще не создан, вывод идет в стандартную консоль UART
        print(f"[BOOT] Раннее защелкивание реле на GPIO{POWER_PIN} выполнено.")
    except Exception as exc:
        print(f"[BOOT ERROR] Сбой раннего защелкивания питания: {exc}")


class PowerManager:
    """
    Единый модуль инкапсуляции питания и Smart Timeout автоотключения.
    """

    def __init__(self, pin_num=POWER_PIN):
        self.pin_num = pin_num
        self._pin = None
        self.last_activity = time.ticks_ms()
        self._init_gpio()

    def _init_gpio(self):
        """Инициализация управляющего GPIO пина."""
        try:
            self._pin = machine.Pin(self.pin_num, machine.Pin.OUT)
        except Exception as exc:
            self._log_traceback("Ошибка инициализации GPIO питания", exc)

    def notify_activity(self):
        """Фиксирует действие пользователя и сбрасывает счетчик таймаута."""
        self.last_activity = time.ticks_ms()

    def hold_power(self):
        """Подтверждает и фиксирует удержание питания с выводом в системный лог."""
        try:
            if self._pin:
                self._pin.value(1)
                log.info(f"[POWER HOLD START] Подтверждение удержания питания: Реле ВКЛЮЧЕНО (GPIO{self.pin_num} = HIGH)")
        except Exception as exc:
            self._log_traceback("Сбой удержания питания", exc)

    def shutdown(self):
        """Размыкает реле питания, полностью обесточивая систему."""
        try:
            log.info(f"[RELAY OFF] Отключение реле: Система обесточивается (GPIO{self.pin_num} = LOW)")
            time.sleep_ms(100)
            if self._pin:
                self._pin.value(0)
        except Exception as exc:
            self._log_traceback("Ошибка при выключении питания", exc)

    async def start_smart_timeout(self, mode=None, timeout_sec=7):
        """
        Асинхронный Smart Timeout:
        Сбрасывает отсчет при старте и обесточивает систему при отсутствии HTTP-активности.
        """
        # СБРОС ТАЙМЕРА: Отсчет начинается строго с этого момента, не учитывая время проигрывания музыки
        self.notify_activity()
        
        log.info(f"[SMART TIMEOUT START] Старт отслеживания активности приложения на {timeout_sec} сек...")
        timeout_ms = timeout_sec * 1000
        try:
            while True:
                await asyncio.sleep(1)
                elapsed_ms = time.ticks_diff(time.ticks_ms(), self.last_activity)

                if elapsed_ms >= timeout_ms:
                    log.info(f"[SMART TIMEOUT END] Нет активности в приложении {timeout_sec} сек. Выход с обесточиванием системы...")
                    self.shutdown()
                    break

        except asyncio.CancelledError:
            log.info("[SMART TIMEOUT CANCEL] Таймер автоотключения отменен.")
        except Exception as exc:
            self._log_traceback("Сбой в работе смарт-таймера", exc)
            self.shutdown()

    def _log_traceback(self, context_msg, exc):
        """Перехватчик исключений с записью трейсбэков."""
        buf = io.StringIO()
        sys.print_exception(exc, buf)
        log.error(f"{context_msg}: {exc}\nПодробный трейсбэк:\n{buf.getvalue()}")


# Глобальный экземпляр для экспорта
power_mgr = PowerManager()