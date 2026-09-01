import socket
import network
import time
import gc
import sys
import io
import logging
from app.security import SecurityManager

log = logging.getLogger("NETWORK")

security_mgr = SecurityManager()

def setup_network(config):
    """
    Настройка сетевых интерфейсов ESP32-S3.
    Сначала совершается попытка подключения к домашнему роутеру (STA-режим).
    В случае неудачи или отсутствия настроек активируется собственная точка доступа (AP-режим).
    """
    log.info("[TRACE ENTER] setup_network()")
    hostname = config.get('hostname', 'bell555')
    try:
        network.hostname(hostname)
        log.info(f"Установлено сетевое имя устройства (mDNS): {hostname}")
    except Exception:
        pass

    time.sleep(1)
    sta_ssid = config.get('wifi_ssid', '')
    raw_sta_pass = config.get('wifi_password', '')
    # Расшифровка пароля Wi-Fi из ключа ENC:...
    sta_pass = security_mgr.decrypt_str(raw_sta_pass)
    
    # Режим клиента домашней сети (Station Mode)
    if sta_ssid and (not raw_sta_pass or sta_pass != ""):
        sta = network.WLAN(network.STA_IF)
        sta.active(False)
        time.sleep(0.1)
        sta.active(True)

        # Отключение энергосберегающего режима Wi-Fi для устранения задержек сети и разрывов сокета
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
        
        wifi_timeout_sec = config.get('wifi_connect_timeout_sec', 12)
        wifi_check_delay_ms = config.get('wifi_check_delay_ms', 100)
        max_retries = int((wifi_timeout_sec * 1000) / wifi_check_delay_ms)
        
        # Ожидание подключения с использованием конфигурационных задержек
        for _ in range(max_retries):
            if sta.isconnected():
                ip = sta.ifconfig()[0]
                log.info(f"Подключено к роутеру! Выделенный IP: {ip}")
                log.info("[TRACE EXIT] setup_network -> STA, %s", ip)
                return 'STA', ip
            time.sleep_ms(wifi_check_delay_ms)
        
        log.warning("Подключение к роутеру не удалось. Переход в режим локальной точки доступа (AP)...")
        sta.active(False)

    # Режим аварийной/стартовой точки доступа (Access Point Mode)
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
    log.info("[TRACE EXIT] setup_network -> AP, %s", ip)
    return 'AP', ip

def dns_thread(ip_str):
    """
    Фоновый UDP DNS-сервер для поддержки Captive Portal в режиме точки доступа (AP).
    Перенаправляет любые доменные запросы подключающихся смартфонов на IP-адрес ESP32.
    """
    log.info("[TRACE ENTER] dns_thread(ip_str=%s)", ip_str)
    udps = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udps.settimeout(1.0)
    udps.bind(('0.0.0.0', 53))
    ip_bytes = bytes([int(x) for x in ip_str.split('.')])

    while True:
        try:
            data, addr = udps.recvfrom(512)
            if data:
                # Формирование DNS-ответа
                response = data[:2] + b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00' + data[12:]
                response += b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04' + ip_bytes
                udps.sendto(response, addr)
        except Exception:
            time.sleep(0.05)
        finally:
            gc.collect()

def handle_async_exception(loop, context):
    """
    Перехватчик необработанных исключений асинхронного цикла uasyncio.
    Игнорирует безопасные сетевые ошибки разрыва HTTPS/TLS сокетов клиентом
    и записывает подробный трейсбэк (trace) для всех остальных сбоев.
    """
    log.info("[TRACE ENTER] handle_async_exception(context=%s)", context)
    exception = context.get('exception')
    if isinstance(exception, OSError):
        err_code = exception.args[0] if exception.args else None
        err_str = str(exception)
        # Игнорируем сетевые сбросы соединений (ECONNRESET, MBEDTLS_ERR_NET_CONN_RESET)
        if err_code in (-30592, -104, 104) or 'MBEDTLS' in err_str:
            log.info("[TRACE EXIT] handle_async_exception (ignored socket reset)")
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
    log.info("[TRACE EXIT] handle_async_exception")