import network
import socket
import time

# 1. Настройка Wi-Fi AP
def setup_ap(ssid="ESP32-Config", password="anton123"):
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
    time.sleep(0.1)
    ap.active(True)
    ap.config(essid=ssid, password=password, authmode=network.AUTH_WPA2_PSK)
    
    while not ap.active():
        time.sleep(0.1)
        
    print(f"Точка доступа запущенa: {ssid}")
    print("IP-адрес:", ap.ifconfig()[0])
    return ap

# 2. HTML-форма
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta charset="utf-8">
    <title>ESP32 Storage</title>
</head>
<body style="font-family: sans-serif; padding: 20px; text-align: center;">
    <h2>Загрузка файла на ESP32</h2>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="file" name="file" required><br><br>
        <button type="submit" style="padding: 10px 20px;">Загрузить</button>
    </form>
</body>
</html>
"""

setup_ap()

# 3. Запуск веб-сервера
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', 80))
s.listen(5)

print("Веб-сервер готов к приему подключений на http://192.168.4.1")

while True:
    try:
        conn, addr = s.accept()
        conn.settimeout(3.0)
        print(f"Подключение от {addr[0]}")
        
        request = b""
        try:
            request = conn.recv(1024)
        except:
            pass

        req_str = request.decode('utf-8', 'ignore')
        
        if "POST /upload" in req_str:
            # Простейший разбор POST-запроса и сохранение
            filename = "uploaded_file"
            if 'filename="' in req_str:
                filename = req_str.split('filename="')[1].split('"')[0]

            # Ищем начало бинарного тела
            body_start = request.find(b'\r\n\r\n')
            if body_start != -1:
                content = request[body_start + 4:]
                with open('/' + filename, 'wb') as f:
                    f.write(content)

            response = f"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<h1>Файл '{filename}' загружен!</h1><a href='/'>Назад</a>"
            conn.sendall(response.encode('utf-8'))
        else:
            # Для любых GET запросов отдаем форму
            response = f"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(HTML_PAGE)}\r\n\r\n{HTML_PAGE}"
            conn.sendall(response.encode('utf-8'))

        conn.close()
    except Exception as e:
        print("Ошибка обработки:", e)
        try:
            conn.close()
        except:
            pass
