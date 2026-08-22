import json
import os
import _thread
import time
import socket
import network
import gc
import logging
import uasyncio as asyncio
import sys
import io

from logger import setup_logging
from app.security import SecurityManager
from hal.power_manager import power_mgr

# Инициализация глобального системного логгера для главного файла управления[cite: 8]
setup_logging(logging.INFO)
log = logging.getLogger("MAIN")

# Менеджер безопасности для AES-128 шифрования/расшифровки паролей[cite: 8]
security_mgr = SecurityManager()

def load_config():
    """
    Загрузка конфигурации из файла config.json.[cite: 8]
    Поддерживает фильтрацию однострочных комментариев (// и #),[cite: 8]
    а также автоматически шифрует открытые пароли с помощью AES-128[cite: 8]
    при первом запуске с сохранением структуры файла и комментариев.[cite: 8]
    """
    try:
        with open('config.json', 'r') as f:
            lines = f.readlines()

        # Предварительная очистка строк от комментариев // и # для корректной работы json.loads[cite: 8]
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('//') or stripped.startswith('#'):
                continue
            clean_lines.append(line)

        raw_json_str = "".join(clean_lines)
        cfg = json.loads(raw_json_str)
        log.info("Файл config.json успешно загружен и очищен от комментариев.")
        
        # Проверка и автоматическое шифрование полей, указанных в encrypted_fields[cite: 8]
        pass_keys = cfg.get('encrypted_fields', ['wifi_password', 'upload_password', 'ap_password'])
        updated = False
        unencrypted_vals = {}
        
        for k in pass_keys:
            val = cfg.get(k, '')
            # Если значение заполнено и еще не зашифровано (не начинается с "ENC:")[cite: 8]
            if val and not str(val).startswith("ENC:"):
                unencrypted_vals[k] = str(val)
                cfg[k] = security_mgr.encrypt_str(str(val))
                updated = True

        # Если были обнаружены открытые пароли — перезаписываем конфиг с их зашифрованными версиями[cite: 8]
        if updated:
            try:
                # Считываем исходный текст файла с диска, чтобы не затереть комментарии //[cite: 8]
                with open('config.json', 'r') as fr:
                    raw_content = fr.read()

                # Точечная замена открытых строк паролей на зашифрованные токены[cite: 8]
                for k, raw_val in unencrypted_vals.items():
                    raw_content = raw_content.replace(f'"{raw_val}"', f'"{cfg[k]}"')

                with open('config.json', 'w') as fw:
                    fw.write(raw_content)
                log.info("Пароли зашифрованы AES-128 (все комментарии в config.json сохранены).")
            except Exception as ex:
                log.error(f"Не удалось обновить config.json: {ex}")

        return cfg
    except Exception as e:
        log.error(f"Ошибка чтения config.json: {e}")
        # Дефолтная конфигурация на случай отсутствия или повреждения config.json[cite: 8]
        return {
            "boot_mode": "default",
            "repeat_count": 1,
            "max_play_duration_sec": 0,
            "fade_out_ms": 1000,
            "wifi_ssid": "",
            "wifi_password": "",
            "upload_password": "admin",
            "ap_ssid": "ESP32-Config",
            "ap_password": "anton123",
            "encrypted_fields": ["wifi_password", "upload_password", "ap_password"],
            "allowed_extensions": ["mp3", "wav"],
            "hostname": "bell555",
            "cert_path": "resources/cert.crt",
            "key_path": "resources/cert.key",
            "html_index_path": "app/www/index.html",
            "media_dir": "/media",
            "target_filename": "bell.wav",
            "max_file_size": 4194304,
            "server_host": "0.0.0.0",
            "server_port": 80,
            "ap_ip": "192.168.4.1"
        }

def setup_network(config):
    """
    Настройка сетевых интерфейсов ESP32-S3.[cite: 8]
    Сначала совершается попытка подключения к домашнему роутеру (STA-режим).[cite: 8]
    В случае неудачи или отсутствия настроек активируется собственная точка доступа (AP-режим).[cite: 8]
    """
    hostname = config.get('hostname', 'bell555')
    try:
        network.hostname(hostname)
        log.info(f"Установлено сетевое имя устройства (mDNS): {hostname}")
    except Exception:
        pass

    time.sleep(1)
    sta_ssid = config.get('wifi_ssid', '')
    raw_sta_pass = config.get('wifi_password', '')
    # Расшифровка пароля Wi-Fi из ключа ENC:...[cite: 8]
    sta_pass = security_mgr.decrypt_str(raw_sta_pass)
    
    # Режим клиента домашней сети (Station Mode)[cite: 8]
    if sta_ssid and (not raw_sta_pass or sta_pass != ""):
        sta = network.WLAN(network.STA_IF)
        sta.active(False)
        time.sleep(0.1)
        sta.active(True)

        # Отключение энергосберегающего режима Wi-Fi для устранения задержек сети и разрывов сокета[cite: 8]
        try:
            sta.config(pm=network.WLAN.PM_NONE)
        except Exception:
            pass

        try:
            sta.config(dhcp_hostname=hostname)
        except Exception:
            pass

        log.info(f"Подключение к роутеру '{sta_ssid}'...")
        sta.connect(sta_ssid, sta_pass)
        
        # Ожидание подключения до 12 секунд[cite: 8]
        for _ in range(120):
            if sta.isconnected():
                ip = sta.ifconfig()[0]
                log.info(f"Подключено к роутеру! Выделенный IP: {ip}")
                return 'STA', ip
            time.sleep(0.1)
        
        log.warning("Подключение к роутеру не удалось. Переход в режим локальной точки доступа (AP)...")
        sta.active(False)

    # Режим аварийной/стартовой точки доступа (Access Point Mode)[cite: 8]
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
    time.sleep(0.1)
    ap.active(True)
    
    try:
        ap.config(pm=network.WLAN.PM_NONE)
    except Exception:
        pass

    ap_ssid = config.get('ap_ssid', 'ESP32-Config')
    raw_ap_pass = config.get('ap_password', 'anton123')
    ap_pass = security_mgr.decrypt_str(raw_ap_pass) or "anton123"

    ap.config(essid=ap_ssid, password=ap_pass, authmode=network.AUTH_WPA2_PSK)
    
    while not ap.active():
        time.sleep(0.1)
        
    ip = ap.ifconfig()[0]
    log.info(f"Режим точки доступа запущен: '{ap_ssid}'. IP устройства: {ip}")
    return 'AP', ip

def dns_thread(ip_str):
    """
    Фоновый UDP DNS-сервер для поддержки Captive Portal в режиме точки доступа (AP).[cite: 8]
    Перенаправляет любые доменные запросы подключающихся смартфонов на IP-адрес ESP32.[cite: 8]
    """
    udps = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udps.settimeout(1.0)
    udps.bind(('0.0.0.0', 53))
    ip_bytes = bytes([int(x) for x in ip_str.split('.')])

    while True:
        try:
            data, addr = udps.recvfrom(512)
            if data:
                # Формирование DNS-ответа[cite: 8]
                response = data[:2] + b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00' + data[12:]
                response += b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04' + ip_bytes
                udps.sendto(response, addr)
        except Exception:
            time.sleep(0.05)
        finally:
            gc.collect()

def handle_async_exception(loop, context):
    """
    Перехватчик необработанных исключений асинхронного цикла uasyncio.[cite: 8]
    Игнорирует безопасные сетевые ошибки разрыва HTTPS/TLS сокетов клиентом[cite: 8]
    и записывает подробный трейсбэк (trace) для всех остальных сбоев.
    """
    exception = context.get('exception')
    if isinstance(exception, OSError):
        err_code = exception.args[0] if exception.args else None
        err_str = str(exception)
        # Игнорируем сетевые сбросы соединений (ECONNRESET, MBEDTLS_ERR_NET_CONN_RESET)[cite: 8]
        if err_code in (-30592, -104, 104) or 'MBEDTLS' in err_str:
            return
            
    tb_str = ""
    if exception:
        try:
            buf = io.StringIO()
            sys.print_exception(exception, buf)
            tb_str = buf.getvalue()
        except Exception:
            tb_str = str(exception)

    log.error(f"Асинхронное исключение в event loop: {context.get('message', 'Unhandled exception')}\n{tb_str}")

def main():
    """Главная точка входа приложения."""
    gc.collect()
    config = load_config()

    # Проверка и авто-создание структуры необходимых системных и HAL папок[cite: 8]
    required_dirs = ['media', 'resources', 'app', 'app/www', 'app/www/css', 'app/www/js', 'hal']
    for directory in required_dirs:
        try:
            os.mkdir(directory)
        except OSError:
            pass

    # 1. ФАЗА АВТОНОМНОГО СТАРТОВОГО ВОСПРОИЗВЕДЕНИЯ (OFFLINE / MUSIC FIRST)[cite: 8]
    # Вызов модуля уровня HAL до запуска сети и веб-сервера[cite: 8]
    if config.get('boot_mode') == 'music_first':
        from hal.boot_player import run_boot_audio
        run_boot_audio(config)
        gc.collect()

    # 2. ФАЗА ИНИЦИАЛИЗАЦИИ СЕТИ И ВЕБ-ПРИЛОЖЕНИЯ[cite: 8]
    # Запускается только после полного окончания стартовой аудиокомпозиции[cite: 8]
    log.info("Инициализация сетевых интерфейсов и веб-сервера Microdot...")
    mode, ip = setup_network(config)

    # Запуск DNS Captive Portal в отдельном потоке при работе в режиме точки доступа[cite: 8]
    if mode == 'AP':
        _thread.start_new_thread(dns_thread, (ip,))

    loop = asyncio.get_event_loop()
    loop.set_exception_handler(handle_async_exception)

    # Запуск фонового Smart Timeout для автоматического обесточивания системы
    timeout_sec = config.get('smart_timeout_sec', 5)
    loop.create_task(power_mgr.start_smart_timeout(mode, timeout_sec=timeout_sec))

    # Ленивый импорт веб-сервера и UI-плеера после завершения работы автономного HAL плеера[cite: 8]
    from app.server import init_server, start_server

    app = init_server(config)
    host = config.get('server_host', '0.0.0.0')
    port = config.get('server_port', 80)
    hostname = config.get('hostname', 'bell555')
    
    cert_path = config.get('cert_path', 'resources/cert.crt')
    key_path = config.get('key_path', 'resources/cert.key')

    proto = "https" if port == 443 else "http"
    log.info(f"Запуск Microdot веб-сервера на {host}:{port}...")
    if mode == 'STA':
        log.info(f"Доступ к панели управления по IP: {proto}://{ip}")
        log.info(f"Доступ к панели управления по имени: {proto}://{hostname} или {proto}://{hostname}.local")
    else:
        log.info(f"Подключитесь к Wi-Fi '{config.get('ap_ssid', 'ESP32-Config')}' и откройте адрес: {proto}://{ip}")

    # Старт основного бесконечного цикла веб-сервера[cite: 8]
    start_server(app, host, port, cert_file=cert_path, key_file=key_path)

if __name__ == '__main__':
    main()