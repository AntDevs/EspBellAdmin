import io
import sys
import time
import machine
import network
import logging

# Единственная точка настройки номера пина питания для всего проекта
POWER_PIN = 4

log = logging.getLogger("POWER_MGR")

# anton 2
# def hold_power_early():
#     """
#     Быстрый вызов для boot.py.
#     Защелкивает реле на самом раннем этапе (до инициализации логгеров).
#     """
#     print("[TRACE ENTER] hold_power_early()")
#     try:
#         log.info("*************** [TRACE ENTER] hold_power_early() ***************")
#         p = machine.Pin(POWER_PIN, machine.Pin.OUT)
#         p.value(1)
#         log.info("hold_power_early p.value(1)")
#         # На этапе boot.py логгер еще не создан, вывод идет в стандартную консоль UART
#         print(f"[BOOT] Раннее защелкивание реле на GPIO{POWER_PIN} выполнено.")
#         # 3. Пауза для сглаживания индуктивного броска катушки реле
#         log.info(f"[BOOT] Раннее защелкивание реле на GPIO{POWER_PIN} выполнено.")
#     except Exception as exc:
#         print(f"[BOOT ERROR] Сбой раннего защелкивания питания: {exc}")
#     print("[TRACE EXIT] hold_power_early")


class PowerManager:
    """
    Единый модуль инкапсуляции питания и Smart Timeout автоотключения.
    Основан на независимом аппаратном таймере.
    """

    def __init__(self, pin_num=POWER_PIN):
        log.info("[TRACE ENTER] PowerManager.__init__(pin_num=%s)", pin_num)
        self.pin_num = pin_num
        self._pin = None
        self.last_activity = time.ticks_ms()
        self.current_timeout_sec = 7
        self._hw_timer = machine.Timer(0)
        self.config = {}
        # self._init_gpio()
        log.info("[TRACE EXIT] PowerManager.__init__")

    def set_config(self, config):
        """Инъекция конфигурации для получения задержек и таймаутов."""
        self.config = config

# anton 2
    # def _init_gpio(self):
    #     """Инициализация управляющего GPIO пина."""
    #     log.info("[TRACE ENTER] PowerManager._init_gpio()")
    #     try:
    #         self._pin = machine.Pin(self.pin_num, machine.Pin.OUT)
    #         log.info(f"[POWER MANAGER] Менеджер питания инициализирован на GPIO{self.pin_num}")
    #     except Exception as exc:
    #         self._log_traceback("Ошибка инициализации GPIO питания", exc)
    #     log.info("[TRACE EXIT] PowerManager._init_gpio")

    def notify_activity(self):
        """Фиксирует действие пользователя и сбрасывает счетчик таймаута."""
        log.info("[TRACE ENTER] PowerManager.notify_activity()")
        self.last_activity = time.ticks_ms()
        log.info("[TRACE EXIT] PowerManager.notify_activity")

    def set_timeout(self, timeout_sec):
        """Единый метод обновления таймаута и режима индикации."""
        log.info("[TRACE ENTER] PowerManager.set_timeout(timeout_sec=%s)", timeout_sec)
        try:
            self.current_timeout_sec = int(timeout_sec)
            self.notify_activity()

            from hal.indicator import set_led_mode
            if self.current_timeout_sec > 30:
                set_led_mode("moonlight")
            else:
                set_led_mode("police")

            log.info(f"[POWER_MGR] Новый таймаут: {self.current_timeout_sec} сек.")
        except Exception as exc:
            self._log_traceback("Ошибка установки нового таймаута", exc)
        log.info("[TRACE EXIT] PowerManager.set_timeout")

# anton 2
    # def hold_power(self):
    #     """Подтверждает и фиксирует удержание питания с выводом в системный лог."""
    #     log.info("[TRACE ENTER] PowerManager.hold_power()")
    #     try:
    #         if self._pin:
    #             self._pin.value(1)
    #             log.info(f"[POWER HOLD START] Подтверждение удержания питания: Реле ВКЛЮЧЕНО (GPIO{self.pin_num} = HIGH)")
    #     except Exception as exc:
    #         self._log_traceback("Сбой удержания питания", exc)
    #     log.info("[TRACE EXIT] PowerManager.hold_power")

    def shutdown(self):
        """Размыкает реле питания, полностью обесточивая систему."""
        log.info("[TRACE ENTER] PowerManager.shutdown()")
        try:
            log.info(f"[RELAY OFF] Отключение реле: Система обесточивается (GPIO{self.pin_num} = LOW)")
            self._hw_timer.deinit()
            
            delay_ms = self.config.get('shutdown_delay_ms', 100)
            time.sleep_ms(delay_ms)
            
            p = machine.Pin(self.pin_num, machine.Pin.OUT, value=0)
            # if self._pin:
            #     self._pin.value(0)            
        except Exception as exc:
            self._log_traceback("Ошибка при выключении питания", exc)
        log.info("================= [TRACE EXIT] PowerManager.shutdown =================")

    def has_active_clients(self, mode):
        """Проверяет наличие активных Wi-Fi клиентов (подключенные устройства в AP или соединение с роутером в STA)."""
        log.info("[TRACE ENTER] PowerManager.has_active_clients(mode=%s)", mode)
        try:
            if mode == 'AP':
                ap = network.WLAN(network.AP_IF)
                if ap.active():
                    stations = ap.status('stations')
                    count = len(stations)
                    log.info(f"Проверка клиентов AP: подключено {count} устройств.")
                    log.info("[TRACE EXIT] PowerManager.has_active_clients -> %s", count > 0)
                    return count > 0
            elif mode == 'STA':
                sta = network.WLAN(network.STA_IF)
                is_conn = sta.isconnected()
                log.info(f"Проверка подключения STA: isconnected={is_conn}")
                log.info("[TRACE EXIT] PowerManager.has_active_clients -> %s", is_conn)
                return is_conn
        except Exception as exc:
            self._log_traceback("Ошибка при проверке Wi-Fi клиентов", exc)
        log.info("[TRACE EXIT] PowerManager.has_active_clients -> False")
        return False

    def _timer_callback(self, timer):
        """Обработчик прерывания аппаратного таймера."""
        elapsed_ms = time.ticks_diff(time.ticks_ms(), self.last_activity)
        timeout_ms = self.current_timeout_sec * 1000

        if elapsed_ms >= timeout_ms:
            log.info(f"[SMART TIMEOUT END] Выход с обесточиванием системы ({self.current_timeout_sec} сек без активности)...")
            self.shutdown()

    def start_hardware_timeout(self, mode=None, timeout_sec=7):
        """
        Аппаратный Smart Timeout:
        Сбрасывает отсчет при старте и обесточивает систему при отсутствии HTTP-активности.
        Единственная точка управления автоотключением в системе.
        """
        log.info("[TRACE ENTER] PowerManager.start_hardware_timeout(mode=%s, timeout_sec=%s)", mode, timeout_sec)
        self.set_timeout(timeout_sec)
        
        try:
            period_ms = self.config.get('timer_period_ms', 1000)
            self._hw_timer.init(period=period_ms, mode=machine.Timer.PERIODIC, callback=self._timer_callback)
        except Exception as exc:
            self._log_traceback("Сбой инициализации аппаратного таймера", exc)
            self.shutdown()
        log.info("[TRACE EXIT] PowerManager.start_hardware_timeout")

    def _log_traceback(self, context_msg, exc):
        """Перехватчик исключений с записью трейсбэков."""
        log.info("[TRACE ENTER] PowerManager._log_traceback()")
        try:
            buf = io.StringIO()
            sys.print_exception(exc, buf)
            log.error(f"{context_msg}: {exc}\nПодробный трейсбэк:\n{buf.getvalue()}")
        except Exception as e:
            log.error(f"Сбой логирования исключения: {e}")
        log.info("[TRACE EXIT] PowerManager._log_traceback")


# Глобальный экземпляр для экспорта
power_mgr = PowerManager()