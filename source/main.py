import json
import os
import _thread
import time
import socket
import network
import gc
import uasyncio as asyncio
from app.server import init_server, start_server
from app.security import SecurityManager

security_mgr = SecurityManager()

def load_config():
    try:
        with open('config.json', 'r') as f:
            cfg = json.load(f)
            print("[CONFIG] Файл config.json загружен.")
            
            pass_keys = cfg.get('encrypted_fields', ['wifi_password', 'upload_password', 'ap_password'])
            updated = False
            
            for k in pass_keys:
                val = cfg.get(k, '')
                if val and not str(val).startswith("ENC:"):
                    cfg[k] = security_mgr.encrypt_str(str(val))
                    updated = True

            if updated:
                try:
                    with open('config.json', 'w') as fw:
                        json.dump(cfg, fw)
                    print("[SECURITY] Все указанные в encrypted_fields пароли зашифрованы AES-128.")
                except Exception as ex:
                    print(f"[SECURITY ERROR] Не удалось перезаписать config.json: {ex}")

            return cfg
    except Exception as e:
        print(f"[CONFIG ERROR] Ошибка чтения config.json: {e}")
        return {
            "wifi_ssid": "",
            "wifi_password": "",
            "upload_password": "admin",
            "ap_ssid": "ESP32-Config",
            "ap_password": "anton123",
            "encrypted_fields": ["wifi_password", "upload_password", "ap_password"],
            "allowed_extensions": ["mp3"],
            "hostname": "bell555",
            "cert_path": "resources/cert.crt",
            "key_path": "resources/cert.key",
            "html_index_path": "app/www/index.html",
            "media_dir": "/media",
            "target_filename": "bell.mp3",
            "max_file_size": 4194304,
            "server_host": "0.0.0.0",
            "server_port": 80,
            "ap_ip": "192.168.4.1"
        }

def setup_network(config):
    hostname = config.get('hostname', 'bell555')
    try:
        network.hostname(hostname)
        print(f"[NET] Установлено имя устройства: {hostname}")
    except Exception:
        pass

    time.sleep(2)
    sta_ssid = config.get('wifi_ssid', '')
    raw_sta_pass = config.get('wifi_password', '')
    sta_pass = security_mgr.decrypt_str(raw_sta_pass)
    
    if sta_ssid and (not raw_sta_pass or sta_pass != ""):
        sta = network.WLAN(network.STA_IF)
        sta.active(False)
        time.sleep(0.1)
        sta.active(True)

        try:
            sta.config(pm=network.WLAN.PM_NONE)
        except Exception:
            pass

        try:
            sta.config(dhcp_hostname=hostname)
        except Exception:
            pass

        print(f"[WIFI] Подключение к роутеру '{sta_ssid}'...")
        sta.connect(sta_ssid, sta_pass)
        
        for _ in range(120):
            if sta.isconnected():
                ip = sta.ifconfig()[0]
                print(f"[WIFI SUCCESS] Подключено к роутеру! IP: {ip}")
                return 'STA', ip
            time.sleep(0.1)
        
        print("[WIFI WARNING] Подключение не удалось. Запуск локальной точки доступа (AP)...")
        sta.active(False)

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
    print(f"[WIFI] Режим AP запущен: '{ap_ssid}'. IP: {ip}")
    return 'AP', ip

def dns_thread(ip_str):
    udps = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udps.settimeout(1.0)
    udps.bind(('0.0.0.0', 53))
    ip_bytes = bytes([int(x) for x in ip_str.split('.')])

    while True:
        try:
            data, addr = udps.recvfrom(512)
            if data:
                response = data[:2] + b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00' + data[12:]
                response += b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04' + ip_bytes
                udps.sendto(response, addr)
        except Exception:
            time.sleep(0.05)
        finally:
            gc.collect()

def handle_async_exception(loop, context):
    exception = context.get('exception')
    if isinstance(exception, OSError):
        err_code = exception.args[0] if exception.args else None
        err_str = str(exception)
        if err_code in (-30592, -104, 104) or 'MBEDTLS' in err_str:
            return
            
    print(f"[ASYNC EXCEPTION] {context.get('message', 'Unhandled exception')}: {exception}")

def main():
    gc.collect()
    config = load_config()

    required_dirs = ['media', 'resources', 'app', 'app/www', 'app/www/css', 'app/www/js']
    for directory in required_dirs:
        try:
            os.mkdir(directory)
        except OSError:
            pass

    mode, ip = setup_network(config)

    if mode == 'AP':
        _thread.start_new_thread(dns_thread, (ip,))

    loop = asyncio.get_event_loop()
    loop.set_exception_handler(handle_async_exception)

    app = init_server(config)
    host = config.get('server_host', '0.0.0.0')
    port = config.get('server_port', 80)
    hostname = config.get('hostname', 'bell555')
    
    cert_path = config.get('cert_path', 'resources/cert.crt')
    key_path = config.get('key_path', 'resources/cert.key')

    proto = "https" if port == 443 else "http"
    print(f"[SERVER] Запуск Microdot на {host}:{port}...")
    if mode == 'STA':
        print(f"[INFO] Доступ по IP: {proto}://{ip}")
        print(f"[INFO] Доступ по домену: {proto}://{hostname} или {proto}://{hostname}.local")
    else:
        print(f"[INFO] Подключитесь к Wi-Fi '{config.get('ap_ssid', 'ESP32-Config')}' и откройте: {proto}://{ip}")

    start_server(app, host, port, cert_file=cert_path, key_file=key_path)

if __name__ == '__main__':
    main()