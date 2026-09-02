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


def get_network_list():
    log.info("[Enter] get_network_list Сканирование Wi-Fi сети...")
    sta = network.WLAN(network.STA_IF)
    active_was = sta.active()
    if not active_was:
        sta.active(True)
        time.sleep(0.1)
    try:
        scanned_nets = sta.scan()
        # Сортировка по уровню сигнала RSSI (индекс 3) по убыванию
        scanned_nets.sort(key=lambda x: x[3], reverse=True)
        log.info(f"get_network_list Сканирование Wi-Fi сети завершено. Найдено {scanned_nets} сетей.")
    except Exception as e:
        log.error(f"get_network_list Ошибка сканирования: {e}")
        scanned_nets = []
    if not active_was:
        sta.active(False)
        
    result = []
    seen_ssids = set() # Трекаем уже добавленные имена сетей
    
    for net in scanned_nets:
        ssid_str = net[0].decode('utf-8', 'ignore') if isinstance(net[0], bytes) else str(net[0])
        
        # Отсеиваем скрытые сети (пустой SSID) и дубликаты
        if ssid_str and ssid_str not in seen_ssids:
            seen_ssids.add(ssid_str)
            result.append({
                'ssid': ssid_str,
                'rssi': net[3],
                'authmode': net[4]
            })
            
    log.info("[Exit] get_network_list Сканирование Wi-Fi сети: %s", result)
    return result


def find_best_network(sta, wifi_networks):
    """
    Отдельная функция поиска наилучшей Wi-Fi сети путем сканирования эфира
    и сопоставления со списком известных сетей по уровню сигнала (RSSI).
    """
    log.info("[Enter] find_best_network выбора оптимальной Wi-Fi сети...")

    if len(wifi_networks) == 0:
        log.warning("[Exit] find_best_network Нет известных Wi-Fi сетей для подключения.")
        return None, None

    if len(wifi_networks) == 1:
        net = wifi_networks[0]
        sta_ssid = net.get('ssid')
        raw_sta_pass = net.get('password', '')
        log.info(f"В конфигурации задана единственная сеть '{sta_ssid}'. Подключение без поиска...")
        sta_pass = security_mgr.decrypt_str(raw_sta_pass) if str(raw_sta_pass).startswith("ENC:") else raw_sta_pass
        log.info("[Exit] find_best_network выбора оптимальной Wi-Fi сети: %s", sta_ssid)
        return sta_ssid, sta_pass
    
    # scanned_nets = sta.scan()
    # scanned_nets.sort(key=lambda x: x[3], reverse=True)
    scanned_nets = get_network_list()   

    # Поиск первой известной сети с наилучшим сигналом
    for net in scanned_nets:            
        # scanned_ssid = net[0].decode('utf-8', 'ignore') if isinstance(net[0], bytes) else str(net[0])
        match = next((item for item in wifi_networks if item.get('ssid') == net.get('ssid')), None)
        log.info(f"find_best_network Сканированная сеть: '{match}' (RSSI: {net.get('rssi')} dBm).")

        if match:
            sta_ssid = match['ssid']
            raw_sta_pass = match.get('password', '')
            log.info(f"find_best_network Найдена сеть: '{sta_ssid}'. Попытка подключения...")
            sta_pass = security_mgr.decrypt_str(raw_sta_pass) if str(raw_sta_pass).startswith("ENC:") else raw_sta_pass
            log.info("[Exit] find_best_network выбора оптимальной Wi-Fi сети: %s", sta_ssid)
            return sta_ssid, sta_pass
            
    log.warning("[Exit] find_best_network Не удалось найти известные сети в радиусе действия.")
    return None, None

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
    netMode, ip = initWifiMode(config)
    if ip == None:
        netMode, ip = initHotPoinMode(config)

    log.info(f"[TRACE Exit] setup_network() -> '{netMode}', '{ip}'" )
    return netMode, ip

def initWifiMode(config):
    log.warning("[TRACE ENTER] initWifiMode")

    wifi_networks = config.get('wifi_networks', [])

    if len(wifi_networks) == 0:
        log.warning("[Exit] initWifiMode Нет известных Wi-Fi сетей для подключения.")
        return None, None

    sta = network.WLAN(network.STA_IF)
    sta.active(False)
    time.sleep(0.1)
    sta.active(True)

    sta_ssid, sta_pass = find_best_network(sta, wifi_networks)
    if not sta_ssid:
        sta.active(False)
        return None, None

    # Отключение энергосберегающего режима Wi-Fi для устранения задержек сети и разрывов сокета
    try:
        sta.config(pm=network.WLAN.PM_NONE)
    except Exception:
        pass

    hostname = config.get('hostname', 'bell555')
    try:
        sta.config(dhcp_hostname=hostname)
    except Exception:
        pass

    log.info(f"initWifiMode Подключение к роутеру '{sta_ssid}'...")
    sta.connect(sta_ssid, sta_pass)
    
    wifi_timeout_sec = config.get('wifi_connect_timeout_sec', 12)
    wifi_check_delay_ms = config.get('wifi_check_delay_ms', 100)
    max_retries = int((wifi_timeout_sec * 1000) / wifi_check_delay_ms)
    
    # Ожидание подключения с использованием конфигурационных задержек
    for _ in range(max_retries):
        if sta.isconnected():
            ip = sta.ifconfig()[0]
            log.info(f"initWifiMode Подключено к роутеру! Выделенный IP: {ip}")
            log.info("[TRACE EXIT] initWifiMode -> STA, %s", ip)            
            return 'STA', ip
        time.sleep_ms(wifi_check_delay_ms)

    sta.active(False)
    log.info("[TRACE EXIT] initWifiMode -> STA, None")
    return None, None

def initHotPoinMode(config):
    # Режим аварийной/стартовой точки доступа (Access Point Mode)
    log.info("[TRACE ENTER] initHotPoinMode -> AP")
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
    ap_pass = security_mgr.decrypt_str(raw_ap_pass) if str(raw_ap_pass).startswith("ENC:") else raw_ap_pass
    if not ap_pass:
        ap_pass = "anton123"

    ap.config(essid=ap_ssid, password=ap_pass, authmode=network.AUTH_WPA2_PSK)
    
    while not ap.active():
        time.sleep(0.1)
        
    ip = ap.ifconfig()[0]
    log.info(f"Режим точки доступа запущен: '{ap_ssid}'. IP устройства: {ip}")
    log.info("[TRACE EXIT] initHotPoinMode -> AP, %s", ip)    
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