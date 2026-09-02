import sys
import time
import io
import os
import logging
from util.config_manager import load_config

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
    """Неблокирующий обработчик вывода в USB CDC / Console."""
    def __init__(self):
        super().__init__()

    def emit(self, record):
        try:
            msg = self.format(record) + "\n"
            sys.stdout.write(msg)
        except Exception:
            pass


class SafeFileHandler(logging.Handler):
    """
    Кастомный обработчик файлов для встроенной библиотеки logging MicroPython.
    Удерживает постоянный поток файла и выполняет мгновенный flush() на диск.
    """
    def __init__(self, filename="/boot.log", max_size=65536):
        super().__init__()
        self.filename = filename
        self.max_size = max_size
        self._file = None
        self._check_rotation()
        self._open_stream()
        self._write_boot_marker()
        self.config = load_config()

    def _check_rotation(self):
        """Ротация файла с сохранением boot.log.old при превышении лимита размера."""
        try:
            if os.stat(self.filename)[6] > self.max_size:
                if self._file:
                    self._file.close()
                    self._file = None
                old_file = self.filename + ".old"
                try:
                    os.remove(old_file)
                except OSError:
                    pass
                try:
                    os.rename(self.filename, old_file)
                except OSError:
                    pass
        except OSError:
            pass

    def _open_stream(self):
        """Открытие и удержание постоянного дескриптора файла."""
        try:
            if not self._file:
                self._file = open(self.filename, "a")
        except Exception:
            self._file = None

    def _write_boot_marker(self):
        """Запись разделителя сессий при старте системы."""
        if self._file:
            try:
                self._file.write("\n=================== SYSTEM BOOT / POWER ON ===================\n")
                if self.config.get("flush_log_file", false):
                    self._file.flush()
            except Exception:
                pass

    def emit(self, record):
        """Стандартный метод обработчика logging для записи форматированного лога."""
        if not self._file:
            self._open_stream()

        if self._file:
            try:
                msg = self.format(record) + "\n"
                self._file.write(msg)
                if self.config.get("flush_log_file", False):
                    self._file.flush()  # Мгновенная фиксация во флеш-памяти на случай внезапного выключения                
            except Exception:
                # В случае сбоя ввода-вывода закрываем сокет для переоткрытия на следующем вызове
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None

    def close(self):
        """Корректное закрытие файлового потока стандартными средствами logging."""
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        super().close()


def log_exception(logger, exc, context_msg="Критическая ошибка execution"):
    """Запись полного трейсбэка исключения в логгер."""
    try:
        buf = io.StringIO()
        sys.print_exception(exc, buf)
        trace_str = buf.getvalue()
        logger.error(f"{context_msg}:\n{trace_str.strip()}")
    except Exception as e:
        logger.error(f"{context_msg}: {exc} (Сбой форматирования: {e})")


def setup_logging(level=logging.INFO):
    """Глобальная настройка сквозного логгера (консоль + кастомный обработчик boot.log)."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Очистка старых обработчиков
    for h in root_logger.handlers:
        try:
            h.close()
        except Exception:
            pass
    root_logger.handlers = []

    # Handler 1: Неблокирующий вывод в терминал
    stream_handler = SafeStreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(TimestampFormatter())
    root_logger.addHandler(stream_handler)

    # Handler 2: Кастомный файловый обработчик библиотеки logging
    file_handler = SafeFileHandler(filename="/boot.log", max_size=65536)
    file_handler.setLevel(level)
    file_handler.setFormatter(TimestampFormatter())
    root_logger.addHandler(file_handler)

    return root_logger