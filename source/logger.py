import sys
import time
import io
import logging

class TimestampFormatter(logging.Formatter):
    """Кастомный форматировщик логов с поддержкой миллисекунд [YYYY-MM-DD HH:MM:SS.mmm]."""
    def format(self, record):
        t = time.localtime()
        ms = time.ticks_ms() % 1000
        timestamp = f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}.{ms:03d}"
        
        msg = getattr(record, 'message', str(record))
        levelname = getattr(record, 'levelname', 'INFO')
        name = getattr(record, 'name', 'root')

        return f"[{timestamp}] [{levelname}] [{name}] {msg}"

def log_exception(logger, exc, context_msg="Критическая ошибка execution"):
    """
    Принудительное извлечение полного Traceback исключения
    и запись его в логгер уровня ERROR.
    """
    buf = io.StringIO()
    sys.print_exception(exc, buf)
    trace_str = buf.getvalue()
    logger.error(f"{context_msg}:\n{trace_str.strip()}")

def setup_logging(level=logging.INFO):
    """Глобальная настройка корневого логгера для всего проекта."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for h in root_logger.handlers:
        try:
            h.close()
        except Exception:
            pass
    root_logger.handlers = []

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(TimestampFormatter())
    
    root_logger.addHandler(console_handler)
    return root_logger