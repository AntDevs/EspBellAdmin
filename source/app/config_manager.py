import json
import os
import logging

log = logging.getLogger("CONFIG")

def load_config():
    """Загрузка конфигурации с отложенной инициализацией криптографии."""
    log.info("[TRACE ENTER] load_config()")
    try:
        with open('config.json', 'r') as f:
            lines = f.readlines()

        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('//') or stripped.startswith('#'):
                continue
            clean_lines.append(line)

        raw_json_str = "".join(clean_lines)
        cfg = json.loads(raw_json_str)
        log.info("Файл config.json быстро загружен.")
        
        pass_keys = cfg.get('encrypted_fields', ['wifi_password', 'upload_password', 'ap_password'])
        unencrypted_vals = {}
        
        # Легкая проверка необходимости шифрования без инициализации AES
        for k in pass_keys:
            val = cfg.get(k, '')
            if val and not str(val).startswith("ENC:"):
                unencrypted_vals[k] = str(val)

        # Подгружаем SecurityManager только если реально нужно зашифровать новые пароли
        if unencrypted_vals:
            from app.security import SecurityManager
            security_mgr = SecurityManager()
            
            for k, raw_val in unencrypted_vals.items():
                cfg[k] = security_mgr.encrypt_str(raw_val)
                
            try:
                with open('config.json', 'r') as fr:
                    raw_content = fr.read()
                for k, raw_val in unencrypted_vals.items():
                    raw_content = raw_content.replace(f'"{raw_val}"', f'"{cfg[k]}"')
                with open('config.json', 'w') as fw:
                    fw.write(raw_content)
                log.info("Новые пароли зашифрованы.")
            except Exception as ex:
                log.error(f"Не удалось обновить config.json: {ex}")

        log.info("[TRACE EXIT] load_config")
        return cfg
    except Exception as e:
        log.error(f"Ошибка чтения config.json: {e}")
        # Дефолтный словарь ...
        return {"boot_mode": "default", "smart_timeout_sec": 7} # Сокращено для примера

def setup_system_directories():
    """Создание структуры системных папок."""
    required_dirs = ['media', 'resources', 'app', 'app/www', 'app/www/css', 'app/www/js', 'hal']
    for directory in required_dirs:
        try:
            os.mkdir(directory)
        except OSError:
            pass