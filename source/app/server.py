import ssl
import os
import gc
import uasyncio as asyncio

from microdot import Microdot, Request, send_file
from app.security import SecurityManager
from app.player import AudioPlayer

player = AudioPlayer(sck_pin=4, ws_pin=5, sd_pin=6)

def init_server(config):
    max_size = config.get('max_file_size', 4194304)
    Request.max_content_length = max_size
    Request.max_body_size = max_size

    app = Microdot()
    app.max_content_length = max_size
    app.max_body_size = max_size

    security = SecurityManager(ttl_seconds=60)

    def get_free_space():
        try:
            stat = os.statvfs('/')
            return stat[0] * stat[4]
        except Exception:
            return 0

    def get_media_size():
        total = 0
        media_dir = config.get('media_dir', '/media')
        try:
            for f in os.listdir(media_dir):
                total += os.stat(f"{media_dir}/{f}")[6]
        except Exception:
            pass
        return total

    def get_available_space():
        return get_free_space() + get_media_size()

    def clear_media():
        media_dir = config.get('media_dir', '/media')
        try:
            files = os.listdir(media_dir)
            print(f"[MEDIA] Удаление файлов из {media_dir}: {files}")
            for f in files:
                os.remove(f"{media_dir}/{f}")
        except Exception as e:
            print("[MEDIA ERROR] Ошибка очистки:", e)

    @app.before_request
    async def log_request(request):
        gc.collect()
        print(f"[HTTP IN] {request.method} {request.path} | Free RAM: {gc.mem_free()} B")

    @app.after_request
    async def cleanup_connection(request, response):
        response.headers['Connection'] = 'close'
        gc.collect()
        return response

    @app.errorhandler(413)
    async def payload_too_large(request):
        print(f"[ERROR 413] Превышен лимит {max_size} байт")
        return f'Ошибка: Файл превышает максимальный размер ({max_size // (1024*1024)} МБ)!', 413

    @app.errorhandler(500)
    async def internal_error(exception):
        print(f"[ERROR 500] Внутренняя ошибка сервера: {exception}")
        return f'Внутренняя ошибка сервера: {exception}', 500

    @app.errorhandler(Exception)
    async def generic_error(request, exception):
        print(f"[SERVER WARNING] Перехвачено исключение: {type(exception).__name__} -> {exception}")
        gc.collect()
        return 'Ошибка соединения с сервером', 500

    @app.route('/')
    async def index(request):
        index_path = config.get('html_index_path', 'app/www/index.html')
        return send_file(index_path)

    @app.route('/www/<path:path>')
    async def serve_www(request, path):
        file_path = f'app/www/{path}'
        try:
            os.stat(file_path)
            return send_file(file_path)
        except OSError:
            return 'File not found', 404

    @app.route('/api/info')
    async def api_info(request):
        data = {
            'availableBytes': get_available_space(),
            'maxFileBytes': max_size,
            'allowedExtensions': config.get('allowed_extensions', ['mp3', 'wav']),
            'isPlaying': player.is_playing
        }
        return data, 200, {'Content-Type': 'application/json'}

    @app.route('/api/play', methods=['POST'])
    async def play_sound(request):
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if not is_auth_ok:
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

        media_dir = config.get('media_dir', '/media')
        target = config.get('target_filename', 'bell.wav')
        filepath = f"{media_dir}/{target}"

        try:
            os.stat(filepath)
        except OSError:
            return {'error': 'Файл на ESP32 не найден! Сначала загрузите аудио.'}, 404, {'Content-Type': 'application/json'}

        asyncio.create_task(player.play(filepath))
        return {'status': 'playing'}, 200, {'Content-Type': 'application/json'}

    @app.route('/api/stop', methods=['POST'])
    async def stop_sound(request):
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if not is_auth_ok:
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

        player.stop()
        return {'status': 'stopped'}, 200, {'Content-Type': 'application/json'}

    @app.route('/api/get-nonce')
    async def get_nonce(request):
        nonce = security.generate_nonce()
        return {'nonce': nonce}, 200, {'Content-Type': 'application/json'}

    @app.route('/api/verify-auth', methods=['POST'])
    async def verify_auth(request):
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if is_auth_ok:
            return {'status': 'ok'}, 200, {'Content-Type': 'application/json'}
        else:
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

    @app.route('/upload', methods=['POST'])
    async def upload(request):
        print("[UPLOAD ROUTE] Обработчик /upload вызван")

        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)

        if not is_auth_ok:
            print(f"[AUTH ERROR] {auth_msg}")
            return f"Ошибка авторизации: {auth_msg}", 401

        original_filename = request.headers.get('X-File-Name', '')
        allowed_exts = [ext.lower().lstrip('.') for ext in config.get('allowed_extensions', ['mp3', 'wav'])]

        if original_filename:
            file_ext = original_filename.split('.')[-1].lower() if '.' in original_filename else ''
            if file_ext not in allowed_exts:
                print(f"[UPLOAD ERROR] Запрещенный тип файла: .{file_ext}")
                return f"Ошибка: Запрещенный тип файла (разрешены: {', '.join(allowed_exts)})!", 400

        content_length = int(request.headers.get('Content-Length', 0))
        
        if content_length > max_size:
            print(f"[UPLOAD ERROR] Заявленный размер {content_length} B > {max_size} B")
            return f'Ошибка: Файл превышает разрешенный лимит {max_size // (1024*1024)} МБ!', 400

        clear_media()
        free_bytes = get_free_space()

        if content_length > free_bytes:
            print(f"[UPLOAD ERROR] Недостаточно места ({content_length} B > {free_bytes} B)")
            return 'Ошибка: Недостаточно места на диске!', 400

        media_dir = config.get('media_dir', '/media')
        target_filename = config.get('target_filename', 'bell.wav')
        filepath = f"{media_dir}/{target_filename}"
        print(f"[UPLOAD ROUTE] Запись потока в {filepath} ({content_length} B)...")

        remaining = content_length
        chunk_size = 4096
        saved_bytes = 0

        try:
            with open(filepath, 'wb') as f:
                while remaining > 0:
                    to_read = min(chunk_size, remaining)
                    chunk = await request.stream.read(to_read)
                    if not chunk:
                        print(f"[UPLOAD WARNING] Поток прерван на {saved_bytes} B")
                        break
                    
                    if isinstance(chunk, str):
                        chunk = chunk.encode('latin-1')

                    f.write(chunk)
                    saved_bytes += len(chunk)
                    remaining -= len(chunk)
                    # Микрозадержка для дампа сокета Wi-Fi и предотвращения ECONNRESET (-104)
                    await asyncio.sleep_ms(1)

            print(f"[UPLOAD SUCCESS] Сохранено {saved_bytes} B в {filepath}")
            return f'Файл успешно сохранен как {target_filename}!', 200

        except OSError as e:
            print(f"[UPLOAD ERROR] Сбой передачи сокета ({e})")
            clear_media()
            return 'Ошибка передачи файла', 500

    @app.route('/<path:path>')
    async def catch_all(request, path):
        ap_ip = config.get('ap_ip', '192.168.4.1')
        proto = "https" if config.get('server_port', 80) == 443 else "http"
        return '', 302, {'Location': f"{proto}://{ap_ip}/"}

    return app

def start_server(app, host, port, cert_file='resources/cert.crt', key_file='resources/cert.key'):
    if port == 443:
        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(cert_file, key_file)
            print(f"[SSL] Запуск Microdot HTTPS на {host}:{port}...")
            app.run(host=host, port=port, ssl=ssl_context)
            return
        except Exception as e:
            print(f"[SSL ERROR] Ошибка загрузки SSL из {cert_file} ({e}). Переключение на HTTP (порт 80)...")
            port = 80

    print(f"[SERVER] Запуск Microdot HTTP на {host}:{port}...")
    app.run(host=host, port=port)