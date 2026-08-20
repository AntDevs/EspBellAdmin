import gc
import sys
import time
import machine
import logging

# Пробуем импортировать специализированный модуль esp32 для чтения внутренней температуры
try:
    import esp32
except ImportError:
    esp32 = None

# Логгер модуля мониторинга чипа
log = logging.getLogger("CHIP_MONITOR")

# Константы типов системных событий
EVENT_BOOT_REASON = "SYS_BOOT_REASON"
EVENT_LOW_MEMORY = "SYS_LOW_MEMORY"
EVENT_HIGH_TEMP = "SYS_HIGH_TEMP"
EVENT_I2S_STATE = "I2S_STATE_CHANGED"
EVENT_CRITICAL_ERROR = "SYS_CRITICAL_ERROR"


class ChipMonitor:
    """
    Системный монитор состояния чипа ESP32-S3 и периферии.
    Осуществляет непрерывную диагностику телеметрии, обработку
    аппаратных событий сброса и оповещение компонентов системы.
    """

    def __init__(self, low_ram_threshold_bytes=32768, high_temp_celsius=75.0):
        """
        Конструктор системного монитора.
        :param low_ram_threshold_bytes: Порог минимального объёма свободной RAM в байтах (по умолчанию 32 КБ)
        :param high_temp_celsius: Порог срабатывания критической температуры кристалла (°C)
        """
        self.low_ram_threshold = low_ram_threshold_bytes
        self.high_temp_threshold = high_temp_celsius
        self._event_handlers = {}
        
        # Карта расшифровки причин сброса чипа ESP32-S3
        self._reset_reasons = {
            machine.PWRON_RESET: "PWRON_RESET (Холодное включение питания)",
            machine.HARD_RESET: "HARD_RESET (Аппаратный сброс кнопкой/пином RESET)",
            machine.WDT_RESET: "WDT_RESET (Сброс аппаратным Watchdog таймером)",
            machine.DEEPSLEEP_RESET: "DEEPSLEEP_RESET (Выход из режима глубокого сна)",
            machine.SOFT_RESET: "SOFT_RESET (Программный сброс из кода)"
        }

    def register_event_handler(self, event_type, handler_func):
        """
        Регистрация колбэк-функции подписка на событие.
        :param event_type: Тип строкового события (например, EVENT_LOW_MEMORY)
        :param handler_func: Функция вида handler(event_type, payload)
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler_func)
        log.info(f"Зарегистрирован обработчик события '{event_type}': {handler_func.__name__}")

    def emit_event(self, event_type, payload=None):
        """
        Генерация и рассылка события всем зарегистрированным подписчикам.
        :param event_type: Название возникшего события
        :param payload: Словарь или объект с данными события
        """
        log.info(f"[EVENT EMITTED] {event_type} -> Payload: {payload}")
        if event_type in self._event_handlers:
            for handler in self._event_handlers[event_type]:
                try:
                    handler(event_type, payload)
                except Exception as e:
                    log.error(f"Ошибка внутри обработчика события '{event_type}': {e}")

    def get_reset_cause_string(self):
        """Получение текстового описания причины последнего сброса процессора."""
        cause_code = machine.reset_cause()
        return self._reset_reasons.get(cause_code, f"UNKNOWN_RESET_CODE ({cause_code})")

    def read_chip_temperature(self):
        """
        Чтение встроенного датчика температуры кристалла ESP32-S3.
        Возвращает температуру в °C или None, если модуль недоступен.
        """
        if esp32 and hasattr(esp32, 'raw_temperature'):
            try:
                # На некоторых прошивках MicroPython значение выводится в Фаренгейтах
                raw_temp = esp32.raw_temperature()
                temp_c = (raw_temp - 32) * 5 / 9 if raw_temp > 100 else float(raw_temp)
                return round(temp_c, 1)
            except Exception as e:
                log.warning(f"Не удалось считать температуру чипа: {e}")
        return None

    def collect_telemetry(self):
        """
        Сбор полной системной телеметрии чипа ESP32-S3.
        :return: Словарь с показателями памяти, частоты, температуры и сброса
        """
        gc.collect()
        free_ram = gc.mem_free()
        alloc_ram = gc.mem_alloc()
        total_ram = free_ram + alloc_ram
        cpu_freq_mhz = machine.freq() // 1000000
        chip_temp = self.read_chip_temperature()
        reset_reason = self.get_reset_cause_string()

        telemetry = {
            "timestamp_ms": time.ticks_ms(),
            "cpu_freq_mhz": cpu_freq_mhz,
            "free_ram_bytes": free_ram,
            "allocated_ram_bytes": alloc_ram,
            "total_ram_bytes": total_ram,
            "ram_usage_percent": round((alloc_ram / total_ram) * 100, 1) if total_ram > 0 else 0,
            "chip_temp_celsius": chip_temp,
            "reset_reason": reset_reason
        }
        return telemetry

    def diagnose_and_report(self):
        """
        Проведение мгновенной диагностики чипа и эмиссия событий при выходе за пределы нормативов.
        """
        log.info("=== Запуск комплексной диагностики состояния чипа ESP32-S3 ===")
        telemetry = self.collect_telemetry()

        log.info(f"Частота CPU: {telemetry['cpu_freq_mhz']} МГц")
        log.info(f"Причина запуска: {telemetry['reset_reason']}")
        log.info(f"ОЗУ (RAM): Свободно {telemetry['free_ram_bytes']} B / Использовано {telemetry['allocated_ram_bytes']} B ({telemetry['ram_usage_percent']}%)")
        
        if telemetry['chip_temp_celsius'] is not None:
            log.info(f"Температура чипа: {telemetry['chip_temp_celsius']} °C")

        # 1. Проверка лимита свободной оперативной памяти
        if telemetry['free_ram_bytes'] < self.low_ram_threshold:
            log.warning(f"[HEALTH ALERT] Низкий уровень ОЗУ: {telemetry['free_ram_bytes']} B < {self.low_ram_threshold} B!")
            self.emit_event(EVENT_LOW_MEMORY, {
                "free_bytes": telemetry['free_ram_bytes'],
                "threshold_bytes": self.low_ram_threshold
            })

        # 2. Проверка критического перегрева кристалла
        if telemetry['chip_temp_celsius'] is not None and telemetry['chip_temp_celsius'] > self.high_temp_threshold:
            log.error(f"[HEALTH ALERT] Зафиксирован перегрев чипа: {telemetry['chip_temp_celsius']}°C > {self.high_temp_threshold}°C!")
            self.emit_event(EVENT_HIGH_TEMP, {
                "temp_celsius": telemetry['chip_temp_celsius'],
                "threshold_celsius": self.high_temp_threshold
            })

        return telemetry