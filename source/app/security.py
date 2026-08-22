import hashlib
import os
import time
import gc
import machine
import logging

# Логгер модуля безопасности
log = logging.getLogger("SECURITY")

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import ucryptolib
except ImportError:
    ucryptolib = None

class SecurityManager:
    """
    Менеджер безопасности системы:
    - Аппаратное шифрование/расшифровка конфиденциальных данных (AES-128 CBC)
    - Защита от атаки повторного воспроизведения (Replay Attack) через Nonce
    - Хеширование SHA-256 для проверки авторизации пользователей
    """
    def __init__(self, ttl_seconds=60):
        self.active_nonces = {}
        self.ttl = ttl_seconds

    def _get_aes_key_and_iv(self):
        """
        Генерация 128-битного ключа AES и вектора IV на основе HW ID чипа ESP32-S3.
        SHA-256 дает 32 байта: первые 16 байт — Key, следующие 16 байт — IV.
        """
        try:
            hw_id = machine.unique_id()
        except Exception:
            hw_id = b'esp32s3_default_hw_key'
            
        digest = hashlib.sha256(hw_id).digest()
        key = digest[:16]
        iv = digest[16:32]
        return key, iv

    def encrypt_str(self, plain_text):
        """
        Аппаратное шифрование строки через AES-128 CBC с PKCS7-заполнением.
        """
        if not plain_text or plain_text.startswith("ENC:"):
            return plain_text

        try:
            key, iv = self._get_aes_key_and_iv()
            raw = plain_text.encode('utf-8')
            
            # Выравнивание длины блока до 16 байт (PKCS7 padding)
            pad_len = 16 - (len(raw) % 16)
            padded = raw + bytes([pad_len] * pad_len)

            if ucryptolib:
                cipher = ucryptolib.aes(key, 2, iv)
                encrypted_bytes = cipher.encrypt(padded)
            else:
                encrypted_bytes = bytes([b ^ key[i % len(key)] for i, b in enumerate(padded)])

            encoded_str = binascii.b2a_base64(encrypted_bytes).decode('utf-8').strip()
            return "ENC:" + encoded_str
        except Exception as e:
            log.error(f"Сбой шифрования: {e}")
            return plain_text

    def decrypt_str(self, enc_text):
        """
        Расшифровка AES-128 CBC строки с защитой от смены чипа.
        """
        if not enc_text or not enc_text.startswith("ENC:"):
            return enc_text

        try:
            key, iv = self._get_aes_key_and_iv()
            raw_enc = binascii.a2b_base64(enc_text[4:])

            if ucryptolib:
                cipher = ucryptolib.aes(key, 2, iv)
                decrypted_padded = cipher.decrypt(raw_enc)
            else:
                decrypted_padded = bytes([b ^ key[i % len(key)] for i, b in enumerate(raw_enc)])

            pad_len = decrypted_padded[-1]
            if 1 <= pad_len <= 16:
                decrypted_bytes = decrypted_padded[:-pad_len]
            else:
                decrypted_bytes = decrypted_padded

            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            log.warning(f"Не удалось расшифровать пароль: {e}")
            return ""

    def _cleanup_expired(self):
        """Очистка просроченных токенов Nonce из оперативной памяти."""
        now = time.time()
        for nonce, ts in list(self.active_nonces.items()):
            if now - ts > self.ttl:
                del self.active_nonces[nonce]
        gc.collect()

    def generate_nonce(self):
        """Генерация одноразового криптографического токена Nonce."""
        self._cleanup_expired()
        random_bytes = os.urandom(8)
        nonce = binascii.hexlify(random_bytes).decode('utf-8')
        self.active_nonces[nonce] = time.time()
        return nonce

    def hash_sha256(self, text):
        """Вычисление хеш-суммы SHA-256 для строки."""
        if isinstance(text, str):
            text = text.encode('utf-8')
        h = hashlib.sha256(text)
        if hasattr(h, 'hexdigest'):
            return h.hexdigest()
        return binascii.hexlify(h.digest()).decode('utf-8')

    def verify_upload_auth(self, request, required_password):
        """Проверка авторизации входящего HTTP-запроса по сочетанию Nonce + SHA256 Hash."""
        required_password = self.decrypt_str(required_password)

        if not required_password:
            return True, "AUTH_DISABLED"

        user_nonce = request.headers.get('X-Auth-Nonce', '')
        user_hash = request.headers.get('X-Auth-Hash', '')

        if not user_nonce or user_nonce not in self.active_nonces:
            log.warning(f"Недействительный или просроченный токен Nonce: '{user_nonce}'")
            return False, "Недействительный или просроченный токен (Nonce)!"

        del self.active_nonces[user_nonce]
        expected_hash = self.hash_sha256(required_password + user_nonce)

        if user_hash.lower() == expected_hash.lower():
            log.info(f"Успешная авторизация (Nonce: {user_nonce})")
            return True, "OK"
        else:
            client_ip = getattr(request, 'client_addr', ('unknown', 0))[0]
            log.error(f"Попытка ввода неверного пароля с IP: {client_ip}")
            return False, "Неверный пароль!"