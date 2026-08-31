import gc
import logging
from logger import setup_logging

# Инициализация только самого необходимого минимума для старта
setup_logging(logging.INFO)
log = logging.getLogger("MAIN")

def main():
    """Главная точка входа приложения."""
    log.info("[TRACE ENTER] main()")
    gc.collect()
    
    # Фиксируем удержание питания сразу в главном методе управления
    # anton 2
    # power_mgr.hold_power()

    # 1. Быстрая загрузка конфигурации
    # Импорт модуля конфигурации происходит здесь, чтобы минимизировать время загрузки
    from app.config_manager import load_config, setup_system_directories
    config = load_config()
    setup_system_directories()

    # 1. ФАЗА АВТОНОМНОГО СТАРТОВОГО ВОСПРОИЗВЕДЕНИЯ (OFFLINE / MUSIC FIRST)
    # Выполняется строго до загрузки любых тяжелых сетевых библиотек
    if config.get('boot_mode') == 'music_first':
        from hal.boot_player import run_boot_audio
        run_boot_audio(config)
        gc.collect()

    # 2. ФАЗА ЗАГРУЗКИ СЕТИ И ASYNCIO
    log.info("Загрузка тяжелых сетевых и асинхронных модулей...")
    
    # Отложенный импорт тяжелых компонентов
    import _thread
    import uasyncio as asyncio
    from app.network_manager import setup_network, dns_thread, handle_async_exception
    from hal.power_manager import power_mgr
    from hal.indicator import start_led_loop
    from app.server import init_server, start_server

    log.info("Инициализация сетевых интерфейсов и веб-сервера Microdot...")
    mode, ip = setup_network(config)

    # Запуск DNS Captive Portal в отдельном потоке при работе в режиме точки доступа
    if mode == 'AP':
        _thread.start_new_thread(dns_thread, (ip,))

    # Настройка асинхронного цикла
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(handle_async_exception)

    # 1. Единый запуск аппаратной задачи автоотключения (не зависит от asyncio)
    timeout_sec = config.get('smart_timeout_sec', 7)
    power_mgr.set_config(config)
    power_mgr.start_hardware_timeout(mode, timeout_sec=timeout_sec)

    # 2. Единый запуск фоновой задачи управления светодиодом WS2812
    loop.create_task(start_led_loop(config))

    # Ленивый импорт веб-сервера и UI-плеера после завершения работы автономного HAL плеера
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

    # Старт основного бесконечного цикла веб-сервера
    start_server(app, host, port, cert_file=cert_path, key_file=key_path)
    log.info("[TRACE EXIT] main()")

if __name__ == '__main__':
    main()