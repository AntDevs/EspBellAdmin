import sys
import time
import io
import logging


class TimestampFormatter(logging.Formatter):
    """Кастомный форматировщик логов с поддержкой миллисекунд [YYYY-MM-DD HH:MM:SS.mmm]."""
    def format(self, record):
        try:
            t = time.localtime()
            ms = time.ticks_ms() % 1000
            timestamp = f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}.{ms:03d}"
            
            msg = getattr(record, 'message', str(record))
            levelname = getattr(record, 'levelname', 'INFO')
            name = getattr(record, 'name', 'root')

            return f"[{timestamp}] [{levelname}] [{name}] {msg}"
        except Exception as e:
            return f"[TIMESTAMP ERROR: {e}] {record}"


class SafeStreamHandler(logging.Handler):
    """
    Неблокирующий обработчик логов MicroPython.
    Защищает ESP32-S3 от зависания из-за переполнения буфера USB CDC,
    когда USB-кабель не подключен к компьютеру.
    """
    def __init__(self):
        super().__init__()

    def emit(self, record):
        try:
            msg = self.format(record) + "\n"
            sys.stdout.write(msg)
        except Exception:
            # Игнорируем ошибки записи в переполненный или недоступный буфер stdout/USB
            pass


def log_exception(logger, exc, context_msg="Критическая ошибка execution"):
    """
    Принудительное извлечение полного Traceback исключения
    и запись его в логгер уровня ERROR.
    """
    try:
        buf = io.StringIO()
        sys.print_exception(exc, buf)
        trace_str = buf.getvalue()
        logger.error(f"{context_msg}:\n{trace_str.strip()}")
    except Exception as e:
        logger.error(f"{context_msg}: {exc} (Сбой форматирования трейсбэка: {e})")


def setup_logging(level=logging.INFO):
    """Глобальная настройка корневого логгера для всего проекта."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Очистка старых обработчиков прямым обнулением списка в MicroPython
    for h in root_logger.handlers:
        try:
            h.close()
        except Exception:
            pass
    root_logger.handlers = []

    safe_handler = SafeStreamHandler()
    safe_handler.setLevel(level)
    safe_handler.setFormatter(TimestampFormatter())
    
    root_logger.addHandler(safe_handler)
    return root_logger