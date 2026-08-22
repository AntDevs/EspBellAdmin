import ssl
import os
import gc
import json
import re
import logging
import uasyncio as asyncio
from hal.power_manager import power_mgr

from microdot import Microdot, Request, send_file
from app.security import SecurityManager
from app.player import AudioPlayer

# Логгер модуля веб-сервера
log = logging.getLogger("SERVER")

# Единый экземпляр проигрывателя для работы с UI (пины вычитываются из config.json)
player = AudioPlayer()

def init_server(config):
    """Инициализация роутов и настроек веб-сервера Microdot."""
    log.info("[TRACE ENTER] init_server(config_keys=%s)", list(config.keys()))
    max_size = config.get('max_file_size', 4194304)
    Request.max_content_length = max_size
    Request.max_body_size = max_size

    # Привязываем объект конфигурации к плееру для автоматического чтения настроек
    player.config = config

    app = Microdot()
    app.max_content_length = max_size
    app.max_body_size = max_size

    security = SecurityManager(ttl_seconds=60)

    def get_free_space():
        log.info("[TRACE ENTER] get_free_space()")
        try:
            stat = os.statvfs('/')
            res = stat[0] * stat[4]
        except Exception:
            res = 0
        log.info("[TRACE EXIT] get_free_space -> %s B", res)
        return res

    def get_media_size():
        log.info("[TRACE ENTER] get_media_size()")
        total = 0
        media_dir = config.get('media_dir', '/media')
        try:
            for f in os.listdir(media_dir):
                total += os.stat(f"{media_dir}/{f}")[6]
        except Exception:
            pass
        log.info("[TRACE EXIT] get_media_size -> %s B", total)
        return total

    def get_available_space():
        log.info("[TRACE ENTER] get_available_space()")
        res = get_free_space() + get_media_size()
        log.info("[TRACE EXIT] get_available_space -> %s B", res)
        return res

    def clear_media():
        log.info("[TRACE ENTER] clear_media()")
        media_dir = config.get('media_dir', '/media')
        try:
            files = os.listdir(media_dir)
            log.info(f"Удаление файлов из {media_dir}: {files}")
            for f in files:
                os.remove(f"{media_dir}/{f}")
        except Exception as e:
            log.error(f"Ошибка очистки media: {e}")
        log.info("[TRACE EXIT] clear_media()")

    def safe_decrypt(val):
        log.info("[TRACE ENTER] safe_decrypt(val_len=%s)", len(str(val)))
        res = security.decrypt_str(val)
        if isinstance(res, (tuple, list)):
            out = str(res[1]) if len(res) > 1 else str(res[0])
        else:
            out = str(res)
        log.info("[TRACE EXIT] safe_decrypt")
        return out

    @app.before_request
    async def log_request(request):
        log.info("[TRACE ENTER] log_request(path=%s, method=%s)", request.path, request.method)
        gc.collect()
        power_mgr.notify_activity()
        log.info(f"{request.method} {request.path} | Free RAM: {gc.mem_free()} B")
        log.info("[TRACE EXIT] log_request")

    @app.after_request
    async def cleanup_connection(request, response):
        log.info("[TRACE ENTER] cleanup_connection(path=%s)", request.path)
        response.headers['Connection'] = 'close'
        gc.collect()
        log.info("[TRACE EXIT] cleanup_connection")
        return response

    @app.errorhandler(413)
    async def payload_too_large(request):
        log.info("[TRACE ENTER] payload_too_large")
        log.error(f"Превышен лимит размера файла {max_size} байт")
        res = f'Ошибка: Файл превышает максимальный размер ({max_size // (1024*1024)} МБ)!', 413
        log.info("[TRACE EXIT] payload_too_large")
        return res

    @app.errorhandler(500)
    async def internal_error(exception):
        log.info("[TRACE ENTER] internal_error(exception=%s)", exception)
        log.error(f"Внутренняя ошибка сервера: {exception}")
        res = f'Внутренняя ошибка сервера: {exception}', 500
        log.info("[TRACE EXIT] internal_error")
        return res

    @app.errorhandler(Exception)
    async def generic_error(request, exception):
        log.info("[TRACE ENTER] generic_error(exception=%s)", exception)
        log.warning(f"Перехвачено исключение: {type(exception).__name__} -> {exception}")
        gc.collect()
        res = 'Ошибка соединения с сервером', 500
        log.info("[TRACE EXIT] generic_error")
        return res

    @app.route('/')
    async def index(request):
        log.info("[TRACE ENTER] index()")
        index_path = config.get('html_index_path', 'app/www/index.html')
        res = send_file(index_path)
        log.info("[TRACE EXIT] index")
        return res

    @app.route('/www/<path:path>')
    async def serve_www(request, path):
        log.info("[TRACE ENTER] serve_www(path=%s)", path)
        file_path = f'app/www/{path}'
        try:
            os.stat(file_path)
            res = send_file(file_path)
        except OSError:
            res = 'File not found', 404
        log.info("[TRACE EXIT] serve_www")
        return res

    @app.route('/api/info')
    async def api_info(request):
        log.info("[TRACE ENTER] api_info()")
        data = {
            'availableBytes': get_available_space(),
            'maxFileBytes': max_size,
            'allowedExtensions': config.get('allowed_extensions', ['mp3', 'wav']),
            'isPlaying': player.is_playing
        }
        res = data, 200, {'Content-Type': 'application/json'}
        log.info("[TRACE EXIT] api_info")
        return res

    # REST API для чтения параметров конфигурации
    @app.route('/api/config', methods=['GET'])
    async def get_config_api(request):
        log.info("[TRACE ENTER] get_config_api()")
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if not is_auth_ok:
            log.info("[TRACE EXIT] get_config_api -> 401 Unauthorized")
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

        safe_cfg = {
            'boot_mode': config.get('boot_mode', 'music_first'),
            'smart_timeout_sec': config.get('smart_timeout_sec', 7),
            'repeat_count': config.get('repeat_count', 1),
            'max_play_duration_sec': config.get('max_play_duration_sec', 0),
            'fade_out_ms': config.get('fade_out_ms', 1000),
            'resume_playback': config.get('resume_playback', True),
            'last_play_pos_bytes': config.get('last_play_pos_bytes', 0),
            'last_play_pos_sec': config.get('last_play_pos_sec', 0),
            'wifi_ssid': config.get('wifi_ssid', ''),
            'upload_password': safe_decrypt(config.get('upload_password', '')),
            'ap_ssid': config.get('ap_ssid', 'ESP32-Config'),
            'ap_password': safe_decrypt(config.get('ap_password', 'anton123'))
        }
        log.info("[TRACE EXIT] get_config_api -> 200 OK")
        return safe_cfg, 200, {'Content-Type': 'application/json'}

    # REST API для обновления и сохранения параметров в config.json с сохранением комментариев
    @app.route('/api/config', methods=['POST'])
    async def save_config_api(request):
        log.info("[TRACE ENTER] save_config_api()")
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if not is_auth_ok:
            log.info("[TRACE EXIT] save_config_api -> 401 Unauthorized")
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

        try:
            body = request.json
            if not body:
                log.info("[TRACE EXIT] save_config_api -> 400 Bad Request")
                return {'error': 'Пустые данные конфигурации'}, 400, {'Content-Type': 'application/json'}

            with open('config.json', 'r') as fr:
                raw_content = fr.read()

            updatable = [
                'boot_mode', 'smart_timeout_sec', 'repeat_count',
                'max_play_duration_sec', 'fade_out_ms', 'resume_playback',
                'last_play_pos_bytes', 'last_play_pos_sec',
                'wifi_ssid', 'wifi_password', 'upload_password', 'ap_ssid', 'ap_password'
            ]

            enc_fields = config.get('encrypted_fields', ['wifi_password', 'upload_password', 'ap_password'])

            for key in updatable:
                if key in body:
                    val = body[key]
                    if val is None:
                        continue

                    if key == 'last_play_pos_sec':
                        final_val = float(val)
                        bytes_calc = int(final_val * 176400)
                        config['last_play_pos_bytes'] = bytes_calc
                        if re.search(r'"last_play_pos_bytes"\s*:\s*\d+', raw_content):
                            raw_content = re.sub(r'"last_play_pos_bytes"\s*:\s*\d+', f'"last_play_pos_bytes": {bytes_calc}', raw_content)

                    elif key in enc_fields and str(val) and not str(val).startswith("ENC:"):
                        enc_res = security.encrypt_str(str(val))
                        if isinstance(enc_res, (tuple, list)):
                            final_val = str(enc_res[1]) if len(enc_res) > 1 else str(enc_res[0])
                        else:
                            final_val = str(enc_res)
                    else:
                        if key in ['repeat_count', 'max_play_duration_sec', 'fade_out_ms', 'smart_timeout_sec', 'last_play_pos_bytes']:
                            final_val = int(val)
                        elif key == 'resume_playback':
                            final_val = bool(val)
                        else:
                            final_val = val

                    config[key] = final_val

                    if isinstance(final_val, bool):
                        bool_str = "true" if final_val else "false"
                        if re.search(r'"' + key + r'"\s*:\s*(true|false)', raw_content):
                            raw_content = re.sub(r'"' + key + r'"\s*:\s*(true|false)', f'"{key}": {bool_str}', raw_content)
                    elif isinstance(final_val, (int, float)):
                        if re.search(r'"' + key + r'"\s*:\s*\d+(\.\d+)?', raw_content):
                            raw_content = re.sub(r'"' + key + r'"\s*:\s*\d+(\.\d+)?', f'"{key}": {final_val}', raw_content)
                    else:
                        str_val = str(final_val)
                        if re.search(r'"' + key + r'"\s*:\s*"[^"]*"', raw_content):
                            raw_content = re.sub(r'"' + key + r'"\s*:\s*"[^"]*"', f'"{key}": "{str_val}"', raw_content)

            with open('config.json', 'w') as fw:
                fw.write(raw_content)

            log.info("Настройки успешно сохранены в config.json!")
            log.info("[TRACE EXIT] save_config_api -> 200 OK")
            return {'status': 'saved'}, 200, {'Content-Type': 'application/json'}

        except Exception as e:
            log.error(f"Ошибка сохранения config.json: {e}")
            log.info("[TRACE EXIT] save_config_api -> 500 Exception")
            return {'error': f'Ошибка сохранения: {e}'}, 500, {'Content-Type': 'application/json'}

    @app.route('/api/play', methods=['POST'])
    async def play_sound(request):
        """
        Ознакомительное воспроизведение из UI.
        Запускается в режиме 'ui' (1 повтор, «как есть», без лимитов и затуханий).
        """
        log.info("[TRACE ENTER] play_sound()")
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if not is_auth_ok:
            log.info("[TRACE EXIT] play_sound -> 401 Unauthorized")
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

        media_dir = config.get('media_dir', '/media')
        target = config.get('target_filename', 'bell.wav')
        filepath = f"{media_dir}/{target}"

        try:
            os.stat(filepath)
        except OSError:
            log.info("[TRACE EXIT] play_sound -> 404 File Not Found")
            return {'error': 'Файл на ESP32 не найден! Сначала загрузите аудио.'}, 404, {'Content-Type': 'application/json'}

        log.info("[UI PLAY] Ознакомительное воспроизведение аудио из UI.")

        asyncio.create_task(player.play(filepath))
        log.info("[TRACE EXIT] play_sound -> 200 playing task started")
        return {'status': 'playing'}, 200, {'Content-Type': 'application/json'}

    @app.route('/api/stop', methods=['POST'])
    async def stop_sound(request):
        """Остановка воспроизведения по запросу из веб-панели."""
        log.info("[TRACE ENTER] stop_sound()")
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if not is_auth_ok:
            log.info("[TRACE EXIT] stop_sound -> 401 Unauthorized")
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

        log.info("[UI STOP] Получен сигнал остановки воспроизведения из веб-интерфейса.")
        player.stop()
        log.info("[TRACE EXIT] stop_sound -> 200 stopped")
        return {'status': 'stopped'}, 200, {'Content-Type': 'application/json'}

    @app.route('/api/get-nonce')
    async def get_nonce(request):
        log.info("[TRACE ENTER] get_nonce()")
        nonce = security.generate_nonce()
        res = {'nonce': nonce}, 200, {'Content-Type': 'application/json'}
        log.info("[TRACE EXIT] get_nonce -> %s", nonce)
        return res

    @app.route('/api/verify-auth', methods=['POST'])
    async def verify_auth(request):
        log.info("[TRACE ENTER] verify_auth()")
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if is_auth_ok:
            log.info("[TRACE EXIT] verify_auth -> ok")
            return {'status': 'ok'}, 200, {'Content-Type': 'application/json'}
        else:
            log.info("[TRACE EXIT] verify_auth -> error")
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

    @app.route('/upload', methods=['POST'])
    async def upload(request):
        log.info("[TRACE ENTER] upload()")
        log.info("Обработчик /upload вызван")

        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)

        if not is_auth_ok:
            log.warning(f"Ошибка авторизации загрузки: {auth_msg}")
            log.info("[TRACE EXIT] upload -> 401 Unauthorized")
            return f"Ошибка авторизации: {auth_msg}", 401

        original_filename = request.headers.get('X-File-Name', '')
        allowed_exts = [ext.lower().lstrip('.') for ext in config.get('allowed_extensions', ['mp3', 'wav'])]

        if original_filename:
            file_ext = original_filename.split('.')[-1].lower() if '.' in original_filename else ''
            if file_ext not in allowed_exts:
                log.error(f"Запрещенный тип файла: .{file_ext}")
                log.info("[TRACE EXIT] upload -> 400 Extension forbidden")
                return f"Ошибка: Запрещенный тип файла (разрешены: {', '.join(allowed_exts)})!", 400

        content_length = int(request.headers.get('Content-Length', 0))
        
        if content_length > max_size:
            log.error(f"Заявленный размер {content_length} B > {max_size} B")
            log.info("[TRACE EXIT] upload -> 400 File too large")
            return f'Ошибка: Файл превышает разрешенный лимит {max_size // (1024*1024)} МБ!', 400

        clear_media()
        free_bytes = get_free_space()

        if content_length > free_bytes:
            log.error(f"Недостаточно места на диске ({content_length} B > {free_bytes} B)")
            log.info("[TRACE EXIT] upload -> 400 Out of disk space")
            return 'Ошибка: Недостаточно места на диске!', 400

        media_dir = config.get('media_dir', '/media')
        target_filename = config.get('target_filename', 'bell.wav')
        filepath = f"{media_dir}/{target_filename}"
        log.info(f"Запись потока в {filepath} ({content_length} B)...")

        remaining = content_length
        chunk_size = 4096
        saved_bytes = 0

        try:
            with open(filepath, 'wb') as f:
                while remaining > 0:
                    to_read = min(chunk_size, remaining)
                    chunk = await request.stream.read(to_read)
                    if not chunk:
                        log.warning(f"Поток прерван на {saved_bytes} B")
                        break
                    
                    if isinstance(chunk, str):
                        chunk = chunk.encode('latin-1')

                    f.write(chunk)
                    saved_bytes += len(chunk)
                    remaining -= len(chunk)
                    await asyncio.sleep_ms(1)

            config['last_play_pos_bytes'] = 0
            config['last_play_pos_sec'] = 0
            try:
                with open('config.json', 'r') as fr:
                    raw_content = fr.read()
                raw_content = re.sub(r'"last_play_pos_bytes"\s*:\s*\d+', '"last_play_pos_bytes": 0', raw_content)
                raw_content = re.sub(r'"last_play_pos_sec"\s*:\s*\d+(\.\d+)?', '"last_play_pos_sec": 0', raw_content)
                with open('config.json', 'w') as fw:
                    fw.write(raw_content)
            except Exception:
                pass

            log.info(f"Файл успешно сохранен ({saved_bytes} B) в {filepath}")
            log.info("[TRACE EXIT] upload -> 200 OK")
            return f'Файл успешно сохранен как {target_filename}!', 200

        except OSError as e:
            log.error(f"Сбой передачи сокета: {e}")
            clear_media()
            log.info("[TRACE EXIT] upload -> 500 Network error")
            return 'Ошибка передачи файла', 500

    @app.route('/<path:path>')
    async def catch_all(request, path):
        log.info("[TRACE ENTER] catch_all(path=%s)", path)
        ap_ip = config.get('ap_ip', '192.168.4.1')
        proto = "https" if config.get('server_port', 80) == 443 else "http"
        res = '', 302, {'Location': f"{proto}://{ap_ip}/"}
        log.info("[TRACE EXIT] catch_all -> 302 Redirect")
        return res

    log.info("[TRACE EXIT] init_server -> app ready")
    return app

def start_server(app, host, port, cert_file='resources/cert.crt', key_file='resources/cert.key'):
    log.info("[TRACE ENTER] start_server(host=%s, port=%s)", host, port)
    if port == 443:
        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(cert_file, key_file)
            log.info(f"Запуск Microdot HTTPS на {host}:{port}...")
            app.run(host=host, port=port, ssl=ssl_context)
            log.info("[TRACE EXIT] start_server (HTTPS)")
            return
        except Exception as e:
            log.error(f"Ошибка загрузки SSL из {cert_file} ({e}). Переключение на HTTP (порт 80)...")
            port = 80

    log.info(f"Запуск Microdot HTTP на {host}:{port}...")
    app.run(host=host, port=port)
    log.info("[TRACE EXIT] start_server (HTTP)")