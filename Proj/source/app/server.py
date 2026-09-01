import ssl
import os
import gc
import json
import re
import logging
import uasyncio as asyncio
from hal.power_manager import power_mgr


from microdot import Microdot, Request, Response, send_file
# from microdot import Microdot, Request, Response, send_file
from microdot.cors import CORS 
from app.security import SecurityManager
from app.player import AudioPlayer

log = logging.getLogger("SERVER")

player = AudioPlayer()

def init_server(config):
    """Инициализация роутов и настроек веб-сервера Microdot."""
    log.info("[TRACE ENTER] init_server(config_keys=%s)", list(config.keys()))
    max_size = config.get('max_file_size', 4194304)
    Request.max_content_length = max_size
    Request.max_body_size = max_size

    player.config = config

    app = Microdot()

    cors = CORS(
        app, 
        allowed_origins=['http://localhost:3000'],  # Replace with your frontend domain
        allowed_methods=['GET', 'POST', 'OPTIONS'], # Explicitly include POST and OPTIONS
        allowed_headers=['Content-Type', 'Authorization'] # Add headers your frontend sends
    )

    app.max_content_length = max_size
    app.max_body_size = max_size

    security = SecurityManager(ttl_seconds=60)

    def get_free_space():
        log.info("[TRACE ENTER] get_free_space()")
        try:
            stat = os.statvfs('/')
            res = stat[0] * stat[4]
        except Exception as e:
            log.error(f"Ошибка получения свободного места: {e}")
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
        except Exception as e:
            log.error(f"Ошибка подсчета размера файлов media: {e}")
        log.info("[TRACE EXIT] get_media_size -> %s B", total)
        return total

    def get_available_space():
        log.info("[TRACE ENTER] get_available_space()")
        try:
            res = get_free_space() + get_media_size()
        except Exception as e:
            log.error(f"Ошибка расчета доступного места: {e}")
            res = 0
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
        try:
            res = security.decrypt_str(val)
            if isinstance(res, (tuple, list)):
                out = str(res[1]) if len(res) > 1 else str(res[0])
            else:
                out = str(res)
        except Exception as e:
            log.error(f"Ошибка в safe_decrypt: {e}")
            out = ""
        log.info("[TRACE EXIT] safe_decrypt")
        return out

    # =========================================================================
    # 1. ОБРАБОТКА ВХОДЯЩИХ ЗАПРОСОВ, PREFLIGHT OPTIONS И CORS
    # =========================================================================
    def get_allowed_origin(request):
        """
        Проверка заголовка Origin.
        При наличии Origin сервер возвращает точную строку запрашивающего домена
        для поддержки любых cross-domain клиентов (Android, Web, dev-серверы),
        что также удовлетворяет требованию Access-Control-Allow-Credentials.
        """
        origin = request.headers.get('Origin') or request.headers.get('origin') or ''
        log.info("[TRACE ENTER] get_allowed_origin(origin=%s)", origin)

        allowed = config.get('allowed_origins', ['*'])

        # Если в конфиге разрешены все ('*'), или origin совпадает, или origin передан клиентом
        if '*' in allowed or not allowed or origin in allowed or origin:
            res_origin = origin if origin else '*'
            log.info("[TRACE EXIT] get_allowed_origin(origin=%s) -> allowed", res_origin)
            return res_origin

        log.info("[TRACE EXIT] get_allowed_origin -> *")
        return '*'


    def set_allowed_origin_headers(request, response):
        log.info("[TRACE ENTER] set_allowed_origin_headers (uri=%s, method=%s)", request.path, request.method)
        try:
            allowed_origin = get_allowed_origin(request)

            if allowed_origin and allowed_origin != '*':
                response.headers['Access-Control-Allow-Origin'] = allowed_origin
                response.headers['Access-Control-Allow-Credentials'] = 'true'
            else:
                response.headers['Access-Control-Allow-Origin'] = '*'

            # ---> ДОБАВЛЯЕМ ПРОВЕРКУ PNA <---
            if request.headers.get('Access-Control-Request-Private-Network') or request.headers.get('access-control-request-private-network'):
                response.headers['Access-Control-Allow-Private-Network'] = 'true'

            req_headers = request.headers.get('Access-Control-Request-Headers') or request.headers.get('access-control-request-headers')
            if req_headers:
                response.headers['Access-Control-Allow-Headers'] = req_headers
            else:
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Auth-Nonce, X-Auth-Hash, X-Auth-Token, X-File-Name, Authorization'

            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Expose-Headers'] = '*'
            response.headers['Connection'] = 'close'
        except Exception as e:
            log.error(f"Ошибка в set_allowed_origin_headers: {e}")

    def set_allowed_origin_headersOld(request, response):
        log.info("[TRACE ENTER] set_allowed_origin_headers (uri=%s, method=%s)", request.path, request.method)
        try:
            allowed_origin = get_allowed_origin(request)

            if allowed_origin and allowed_origin != '*':
                response.headers['Access-Control-Allow-Origin'] = allowed_origin
                response.headers['Access-Control-Allow-Credentials'] = 'true'
            else:
                response.headers['Access-Control-Allow-Origin'] = '*'

            req_headers = request.headers.get('Access-Control-Request-Headers') or request.headers.get('access-control-request-headers')
            if req_headers:
                response.headers['Access-Control-Allow-Headers'] = req_headers
            else:
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Auth-Nonce, X-Auth-Hash, X-Auth-Token, X-File-Name, Authorization'

            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Expose-Headers'] = '*'
            response.headers['Access-Control-Allow-Private-Network'] = 'true'
            response.headers['Connection'] = 'close'
        except Exception as e:
            log.error(f"Ошибка в set_allowed_origin_headers: {e}")
        log.info("[TRACE EXIT] set_allowed_origin_headers allowed_origin=%s (uri=%s, method=%s)",
                 allowed_origin, request.path, request.method)

    @app.before_request
    async def process_before_request(request):
        log.info("[TRACE ENTER] process_before_request(uri=%s, method=%s)", request.path, request.method)
        try:
            gc.collect()
            power_mgr.notify_activity()
        except Exception as e:
            log.error(f"Ошибка в notify_activity: {e}")

        
        if request.method == 'OPTIONS':            
            res = Response('', status_code=204)            
            set_allowed_origin_headers(request, res)
            # res.headers['Access-Control-Max-Age'] = '86400'
            return res

    @app.after_request    
    async def cleanup_and_cors(request, response):
        """Эквивалент Mapping("/**") для всех исходящих ответов сервера."""
        try:
            set_allowed_origin_headers(request, response)        
            gc.collect()
        except Exception as e:
            log.error(f"Ошибка в cleanup_and_cors: {e}")
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

    # =========================================================================
    # 2. РАЗДАЧА HTML И СТАТИЧЕСКИХ ФАЙЛОВ
    # =========================================================================
    @app.route('/')
    async def index(request):
        log.info("[TRACE ENTER] index()")
        try:
            index_path = config.get('html_index_path', 'app/www/index.html')
            res = send_file(index_path)
        except Exception as e:
            log.error(f"Ошибка отдачи index.html: {e}")
            res = 'Internal Error', 500
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
        except Exception as e:
            log.error(f"Ошибка доступа к статическому файлу {file_path}: {e}")
            res = 'Error', 500
        log.info("[TRACE EXIT] serve_www")
        return res

    # =========================================================================
    # 3. REST API ЭНДПОИНТЫ
    # =========================================================================
    @app.route('/api/info')
    async def api_info(request):
        log.info("[TRACE ENTER] api_info()")
        try:
            data = {
                'availableBytes': get_available_space(),
                'maxFileBytes': max_size,
                'allowedExtensions': config.get('allowed_extensions', ['mp3', 'wav']),
                'isPlaying': player.is_playing,
                'freeHeap': gc.mem_free(),
                'device': 'ESP32-S3'
            }
            res = data, 200, {'Content-Type': 'application/json'}
        except Exception as e:
            log.error(f"Ошибка запроса api_info: {e}")
            res = {'error': str(e)}, 500, {'Content-Type': 'application/json'}
        log.info("[TRACE EXIT] api_info")
        return res

    @app.route('/api/trigger-bell', methods=['POST', 'OPTIONS'])
    async def api_trigger_bell(request):
        log.info("[TRACE ENTER] api_trigger_bell()")
        try:
            media_dir = config.get('media_dir', '/media')
            target = config.get('target_filename', 'bell.wav')
            filepath = f"{media_dir}/{target}"
            
            try:
                os.stat(filepath)
            except OSError:
                log.info("[TRACE EXIT] trigger_bell -> 404 File Not Found")
                return {'error': 'Файл bell.wav не найден во Flash-памяти!'}, 404, {'Content-Type': 'application/json'}

            asyncio.create_task(player.play(filepath))
            log.info("[TRACE EXIT] trigger_bell -> 200 OK")
            return {'status': 'triggered', 'message': 'Doorbell ringing'}, 200, {'Content-Type': 'application/json'}
        except Exception as e:
            log.error(f"Ошибка вызова звонка: {e}")
            return {'error': str(e)}, 500, {'Content-Type': 'application/json'}

    @app.route('/api/config', methods=['GET'])
    async def get_config_api(request):
        log.info("[TRACE ENTER] get_config_api()")
        try:
            required_password = config.get('upload_password', '')
            is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
            if not is_auth_ok:
                log.info("[TRACE EXIT] get_config_api -> 401 Unauthorized")
                return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}

            safe_cfg = {
                'boot_mode': config.get('boot_mode', 'music_first'),
                'smart_timeout_sec': config.get('smart_timeout_sec', 7),
                'auth_smart_timeout_sec': config.get('auth_smart_timeout_sec', 600),
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
            res = safe_cfg, 200, {'Content-Type': 'application/json'}
        except Exception as e:
            log.error(f"Ошибка чтения конфигурации: {e}")
            res = {'error': str(e)}, 500, {'Content-Type': 'application/json'}
        log.info("[TRACE EXIT] get_config_api -> 200 OK")
        return res

    @app.route('/api/config', methods=['POST', 'OPTIONS'])
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
                'boot_mode', 'smart_timeout_sec', 'auth_smart_timeout_sec', 'repeat_count',
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
                        if key in ['repeat_count', 'max_play_duration_sec', 'fade_out_ms', 'smart_timeout_sec', 'auth_smart_timeout_sec', 'last_play_pos_bytes']:
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

    @app.route('/api/play', methods=['POST', 'OPTIONS'])
    async def play_sound(request):
        """Ознакомительное воспроизведение из UI."""
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

    @app.route('/api/stop', methods=['POST', 'OPTIONS'])
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
        try:
            nonce = security.generate_nonce()
            res = {'nonce': nonce}, 200, {'Content-Type': 'application/json'}
        except Exception as e:
            log.error(f"Ошибка генерации nonce: {e}")
            res = {'error': str(e)}, 500, {'Content-Type': 'application/json'}
        log.info("[TRACE EXIT] get_nonce")
        return res

    @app.route('/api/verify-auth', methods=['OPTIONS'])
    async def verify_auth(request):
        """Переключение в авторизованный режим: таймаут 600 сек."""
        log.info("[TRACE ENTER] verify_auth() OPTIONS")
        return Response('', 204)

    @app.route('/api/verify-auth', methods=['POST'])
    async def verify_auth(request):
        """Переключение в авторизованный режим: таймаут 600 сек."""
        log.info("[TRACE ENTER] verify_auth() POST")
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)
        if is_auth_ok:
            auth_timeout = config.get('auth_smart_timeout_sec', 600)
            power_mgr.set_timeout(auth_timeout)
            log.info("[TRACE EXIT] verify_auth -> ok (timeout: %s s)", auth_timeout)
            return {'status': 'ok'}, 200, {'Content-Type': 'application/json'}
        else:
            log.info("[TRACE EXIT] verify_auth -> error")
            return {'error': auth_msg}, 401, {'Content-Type': 'application/json'}


    @app.route('/api/logout', methods=['POST', 'OPTIONS'])
    async def logout_api(request):
        """Возврат в стартовый режим."""
        log.info("[TRACE ENTER] logout_api()")
        try:
            default_timeout = config.get('smart_timeout_sec', 7)
            power_mgr.set_timeout(default_timeout)
            log.info("[TRACE EXIT] logout_api -> ok (timeout: %s s)", default_timeout)
            return {'status': 'ok'}, 200, {'Content-Type': 'application/json'}
        except Exception as e:
            log.error(f"Ошибка сброса таймаута при выходе: {e}")
            log.info("[TRACE EXIT] logout_api -> exception")
            return {'error': f'Ошибка выхода: {e}'}, 500, {'Content-Type': 'application/json'}

    @app.route('/api/logs')
    async def view_logs(request):
        """Просмотр сохраненного лога работы системы boot.log."""
        try:
            with open('/boot.log', 'r') as f:
                content = f.read()
            return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        except OSError:
            return 'Файл логов /boot.log не найден', 404

    # =========================================================================
    # 5. НАДЕЖНАЯ ПОТОКОВАЯ ЗАГРУЗКА АУДИОФАЙЛА (БЕЗ РАЗРЫВА СОКЕТА)
    # =========================================================================
    @app.route('/upload', methods=['POST', 'OPTIONS'])
    async def upload(request):
        log.info("Обработчик POST /upload вызван")

        # Определение CORS заголовков локально для Response
        allowed_origin = get_allowed_origin(request)
        if allowed_origin and allowed_origin != '*':
            CORS_HEADERS = {
                'Access-Control-Allow-Origin': allowed_origin,
                'Access-Control-Allow-Credentials': 'true'
            }
        else:
            CORS_HEADERS = {'Access-Control-Allow-Origin': '*'}

        # 1. Определение размера передаваемого файла
        content_length = getattr(request, 'content_length', 0) or 0
        if not content_length:
            try:
                content_length = int(request.headers.get('content-length', 0) or request.headers.get('Content-Length', 0))
            except (ValueError, TypeError):
                content_length = 0

        log.info("Ожидаемый размер загрузки: %s байт", content_length)

        # 2. Проверка авторизации
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)

        if not is_auth_ok:
            log.warning("Ошибка авторизации загрузки: %s. Очистка входного потока...", auth_msg)
            # Вычитываем остаток потока, чтобы сокет не сбросил TCP RST в браузер
            try:
                while content_length > 0:
                    dummy = await request.stream.read(min(2048, content_length))
                    if not dummy:
                        break
                    content_length -= len(dummy)
            except Exception:
                pass
            return Response(f"Ошибка авторизации: {auth_msg}", status_code=401, headers=CORS_HEADERS)

        # 3. Имя файла и проверка расширения
        original_filename = request.headers.get('x-file-name', '') or request.headers.get('X-File-Name', '')
        if not original_filename and 'filename' in request.args:
            original_filename = request.args.get('filename', '')

        allowed_exts = [ext.lower().lstrip('.') for ext in config.get('allowed_extensions', ['mp3', 'wav'])]
        if original_filename and '.' in original_filename:
            file_ext = original_filename.split('.')[-1].lower()
            if file_ext not in allowed_exts:
                log.error("Запрещенный тип файла: .%s", file_ext)
                # Дренаж сокета перед ответом
                try:
                    while content_length > 0:
                        dummy = await request.stream.read(min(2048, content_length))
                        if not dummy:
                            break
                        content_length -= len(dummy)
                except Exception:
                    pass
                return Response(f"Ошибка: Запрещенный тип файла (разрешены: {', '.join(allowed_exts)})!", status_code=400, headers=CORS_HEADERS)

        # 4. Проверка лимитов размера
        if content_length > max_size:
            log.error("Заявленный размер %s B > лимита %s B", content_length, max_size)
            return Response(f'Ошибка: Файл превышает лимит {max_size // (1024*1024)} МБ!', status_code=400, headers=CORS_HEADERS)

        # 5. Очистка старых медиа ПЕРЕД проверкой свободного места, чтобы учесть освободившееся пространство
        clear_media()

        free_bytes = get_free_space()
        if content_length > 0 and content_length > free_bytes:
            log.error("Недостаточно места на Flash (%s B > %s B)", content_length, free_bytes)
            return Response('Ошибка: Недостаточно места во Flash-памяти!', status_code=400, headers=CORS_HEADERS)

        # 6. Открытие файла на запись
        media_dir = config.get('media_dir', '/media')
        target_filename = config.get('target_filename', 'bell.wav')
        filepath = f"{media_dir}/{target_filename}"
        log.info("Потоковая запись аудио в %s...", filepath)

        saved_bytes = 0
        chunk_size = 2048

        try:
            with open(filepath, 'wb') as f:
                if content_length > 0:
                    remaining = content_length
                    while remaining > 0:
                        to_read = min(chunk_size, remaining)
                        chunk = await request.stream.read(to_read)
                        if not chunk:
                            break
                        if isinstance(chunk, str):
                            chunk = chunk.encode('latin-1')
                        f.write(chunk)
                        saved_bytes += len(chunk)
                        remaining -= len(chunk)
                        await asyncio.sleep_ms(1)
                else:
                    # Если Content-Length не был указан, читаем до закрытия потока
                    while True:
                        chunk = await request.stream.read(chunk_size)
                        if not chunk:
                            break
                        if isinstance(chunk, str):
                            chunk = chunk.encode('latin-1')
                        f.write(chunk)
                        saved_bytes += len(chunk)
                        await asyncio.sleep_ms(1)

            # Сброс позиции воспроизведения
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

            gc.collect()
            log.info("Файл успешно сохранен (%s B) в %s", saved_bytes, filepath)
            return Response(f'Файл успешно сохранен как {target_filename} ({saved_bytes} B)!', status_code=200, headers=CORS_HEADERS)

        except OSError as e:
            log.error("Сбой сокета при потоковой записи: %s", e)
            clear_media()
            return Response(f'Ошибка записи файла: {e}', status_code=500, headers=CORS_HEADERS)

    @app.route('/upload-old', methods=['POST', 'OPTIONS'])
    async def upload_old(request):
        log.info("[TRACE ENTER] upload()")

        # 1. Определение размера передаваемого файла
        content_length = getattr(request, 'content_length', 0) or 0
        if not content_length:
            try:
                content_length = int(request.headers.get('content-length', 0) or request.headers.get('Content-Length', 0))
            except (ValueError, TypeError):
                content_length = 0

        log.info("Ожидаемый размер загрузки: %s байт", content_length)

        # 2. Проверка авторизации
        required_password = config.get('upload_password', '')
        is_auth_ok, auth_msg = security.verify_upload_auth(request, required_password)

        if not is_auth_ok:
            log.warning(f"Ошибка авторизации загрузки: {auth_msg}")
            log.info("[TRACE EXIT] upload -> 401 Unauthorized")
            return f"Ошибка авторизации: {auth_msg}", 401

        original_filename = request.headers.get('X-File-Name', '')
        if not original_filename and 'filename' in request.args:
            original_filename = request.args.get('filename', '')

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