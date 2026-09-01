import os
import json
import re
import time
import struct
import array
import logging
import uasyncio as asyncio
from machine import I2S, Pin

try:
    import mp3dec
except ImportError:
    mp3dec = None

log = logging.getLogger("AUDIO_UTILS")
_global_i2s = None

def load_config(config_file='config.json'):
    """Единая функция парсинга файла конфигурации config.json с очисткой комментариев."""
    log.info("[TRACE ENTER] load_config(config_file=%s)", config_file)
    try:
        with open(config_file, 'r') as f:
            lines = [l for l in f if not l.strip().startswith(('//', '#'))]
            raw_content = "".join(lines)
            cfg = json.loads(raw_content)
            log.info("[TRACE EXIT] load_config -> OK")
            return cfg
    except Exception as e:
        log.error(f"Ошибка чтения конфигурации {config_file}: {e}")
        log.info("[TRACE EXIT] load_config -> empty dict")
        return {}

def init_hardware_i2s(rate=44100, bits=16, channels=2, ibuf=8192, bck_pin=15, ws_pin=16, sd_pin=17, i2s_id=0):
    """Единая централизованная точка инициализации аппаратного контроллера I2S."""
    global _global_i2s
    log.info("[TRACE ENTER] init_hardware_i2s(rate=%s, bits=%s, channels=%s, ibuf=%s, pins=(%s,%s,%s,%s))",
             rate, bits, channels, ibuf, bck_pin, ws_pin, sd_pin, i2s_id)

    if _global_i2s:
        try:
            _global_i2s.deinit()
        except Exception:
            pass
        _global_i2s = None

    fmt = I2S.STEREO if channels == 2 else I2S.MONO
    log.info(f"Конфигурирование I2S (Rate={rate}Hz, Bits={bits}, Format={fmt}, Buffer={ibuf}B)...")

    _global_i2s = I2S(
        i2s_id,
        sck=Pin(bck_pin),
        ws=Pin(ws_pin),
        sd=Pin(sd_pin),
        mode=I2S.TX,
        bits=bits,
        format=fmt,
        rate=rate,
        ibuf=ibuf
    )

    try:
        _global_i2s.write(bytearray(2048))
    except Exception as e:
        log.warning(f"Ошибка прогрева I2S: {e}")

    log.info("[TRACE EXIT] init_hardware_i2s")
    return _global_i2s

def deinit_hardware_i2s():
    """Единая функция корректного закрытия шины I2S и освобождения DMA-каналов."""
    global _global_i2s
    log.info("[TRACE ENTER] deinit_hardware_i2s()")
    if _global_i2s:
        try:
            _global_i2s.deinit()
        except Exception:
            pass
        _global_i2s = None
    log.info("[TRACE EXIT] deinit_hardware_i2s")

def save_position_to_config(pos_bytes, pos_sec=0.0, config=None):
    """Сохранение позиции воспроизведения в config.json."""
    log.info("[TRACE ENTER] save_position_to_config(pos_bytes=%s, pos_sec=%s)", pos_bytes, pos_sec)
    if config is not None:
        config['last_play_pos_bytes'] = pos_bytes
        config['last_play_pos_sec'] = round(pos_sec, 2)
    try:
        with open('config.json', 'r') as fr:
            raw_content = fr.read()

        if re.search(r'"last_play_pos_bytes"\s*:\s*\d+', raw_content):
            raw_content = re.sub(r'"last_play_pos_bytes"\s*:\s*\d+', f'"last_play_pos_bytes": {pos_bytes}', raw_content)

        if re.search(r'"last_play_pos_sec"\s*:\s*\d+(\.\d+)?', raw_content):
            raw_content = re.sub(r'"last_play_pos_sec"\s*:\s*\d+(\.\d+)?', f'"last_play_pos_sec": {round(pos_sec, 2)}', raw_content)

        with open('config.json', 'w') as fw:
            fw.write(raw_content)
        log.info(f"Сохранена позиция воспроизведения в config.json: {pos_bytes} B ({round(pos_sec, 2)} сек)")
    except Exception as e:
        log.error(f"Не удалось сохранить позицию в config.json: {e}")
    log.info("[TRACE EXIT] save_position_to_config")

def parse_wav_header(f):
    """Парсинг WAV-заголовков с фиксацией смещения data_offset и точной длины data_size."""
    log.info("[TRACE ENTER] parse_wav_header()")
    riff_hdr = f.read(12)
    if len(riff_hdr) < 12 or riff_hdr[:4] != b'RIFF' or riff_hdr[8:12] != b'WAVE':
        log.error("Файл не является валидным WAV!")
        log.info("[TRACE EXIT] parse_wav_header -> None")
        return None

    channels = 2
    rate = 44100
    bits = 16
    data_size = 0
    data_offset = 44

    while True:
        chunk_hdr = f.read(8)
        if len(chunk_hdr) < 8:
            break
        chunk_id = chunk_hdr[:4]
        chunk_size = struct.unpack('<I', chunk_hdr[4:8])[0]

        if chunk_id == b'fmt ':
            fmt_data = f.read(chunk_size)
            if len(fmt_data) >= 14:
                channels = struct.unpack('<H', fmt_data[2:4])[0]
                rate = struct.unpack('<I', fmt_data[4:8])[0]
                if len(fmt_data) >= 16:
                    bits = struct.unpack('<H', fmt_data[14:16])[0]
        elif chunk_id == b'data':
            data_size = chunk_size
            data_offset = f.tell()
            break
        else:
            try:
                f.seek(chunk_size, 1)
            except Exception:
                rem = chunk_size
                while rem > 0:
                    to_read = min(1024, rem)
                    f.read(to_read)
                    rem -= to_read

    res = (channels, rate, bits, data_size, data_offset)
    log.info("[TRACE EXIT] parse_wav_header -> channels=%s, rate=%s, bits=%s, data_size=%s, data_offset=%s",
             channels, rate, bits, data_size, data_offset)
    return res


    """Запись PCM в I2S с масштабированием знаковых сэмплов и автодублированием Mono->Stereo."""
    log.debug("[TRACE ENTER] write_pcm_with_gain(num_bytes=%s, gain=%s, channels=%s)", num_bytes, gain, channels)
    
    if not i2s or num_bytes <= 0:
        log.debug("[TRACE EXIT] write_pcm_with_gain (no i2s or num_bytes <= 0)")
        return

    num_bytes = num_bytes - (num_bytes % 2)
    if num_bytes <= 0:
        return

    try:
        # 1. БЫСТРЫЙ ПУТЬ (100% громкость, играет 95% времени трека)
        if gain >= 0.99:
            if channels == 2:
                i2s.write(memoryview(buf)[:num_bytes])
            else:
                out_buf = bytearray(num_bytes * 2)
                for i in range(0, num_bytes, 2):
                    out_buf[i*2] = buf[i]
                    out_buf[i*2+1] = buf[i+1]
                    out_buf[i*2+2] = buf[i]
                    out_buf[i*2+3] = buf[i+1]
                i2s.write(out_buf)
            log.debug("[TRACE EXIT] write_pcm_with_gain")
            return

        # 2. ПОЛНАЯ ТИШИНА
        if gain <= 0.001:
            if channels == 2:
                i2s.write(bytes(num_bytes))
            else:
                i2s.write(bytes(num_bytes * 2))
            log.debug("[TRACE EXIT] write_pcm_with_gain")
            return

        # 3. ПЛАВНОЕ ЗАТУХАНИЕ (Только последние 1-2 секунды трека)
        gain_int = int(gain * 256)
        
        if channels == 2:
            mv = memoryview(buf)[:num_bytes]
            try:
                # Сверхбыстрый C-уровень (memoryview cast)
                m = mv.cast('h')
                for i in range(len(m)):
                    m[i] = (m[i] * gain_int) >> 8
                i2s.write(mv)
            except AttributeError:
                # Резервный надежный способ для старых версий MicroPython
                b = bytearray(mv)
                for i in range(0, num_bytes, 2):
                    s = b[i] | (b[i+1] << 8)
                    if s > 32767:
                        s -= 65536
                    s = (s * gain_int) >> 8
                    b[i] = s & 0xFF
                    b[i+1] = (s >> 8) & 0xFF
                i2s.write(b)
        else:
            # Моно с затуханием (конвертируем в стерео)
            out_buf = bytearray(num_bytes * 2)
            b = memoryview(buf)[:num_bytes]
            for i in range(0, num_bytes, 2):
                s = b[i] | (b[i+1] << 8)
                if s > 32767:
                    s -= 65536
                s = (s * gain_int) >> 8
                
                low = s & 0xFF
                high = (s >> 8) & 0xFF
                
                out_buf[i*2] = low
                out_buf[i*2+1] = high
                out_buf[i*2+2] = low
                out_buf[i*2+3] = high
            i2s.write(out_buf)

    except Exception as e:
        log.warning(f"Ошибка записи PCM: {e}")
        
    log.debug("[TRACE EXIT] write_pcm_with_gain")
    
    """Оригинальная логика с оптимизированным затуханием (надежная версия)."""
    if not i2s or num_bytes <= 0:
        return

    # Выравнивание по четному числу байт
    num_bytes = num_bytes - (num_bytes % 2)
    if num_bytes <= 0:
        return

    try:
        # 1. БЫСТРЫЙ ПУТЬ (100% громкость, играет 95% времени трека)
        # Код скопирован из вашего оригинала, чтобы гарантировать идеальное звучание.
        if gain >= 0.99:
            if channels == 2:
                i2s.write(memoryview(buf)[:num_bytes])
            else:
                # Конвертация Моно -> Стерео без математики
                out_buf = bytearray(num_bytes * 2)
                for i in range(0, num_bytes, 2):
                    out_buf[i*2] = buf[i]
                    out_buf[i*2+1] = buf[i+1]
                    out_buf[i*2+2] = buf[i]
                    out_buf[i*2+3] = buf[i+1]
                i2s.write(out_buf)
            return

        # 2. ПОЛНАЯ ТИШИНА (Мгновенный выход)
        if gain <= 0.001:
            if channels == 2:
                i2s.write(bytes(num_bytes))
            else:
                i2s.write(bytes(num_bytes * 2))
            return

        # 3. ПЛАВНОЕ ЗАТУХАНИЕ (Только последние 1-2 секунды трека)
        gain_int = int(gain * 256)
        
        if channels == 2:
            mv = memoryview(buf)[:num_bytes]
            try:
                # Сверхбыстрый C-уровень: изменяет данные в памяти без циклов Python
                m = mv.cast('h')
                for i in range(len(m)):
                    m[i] = (m[i] * gain_int) >> 8
                i2s.write(mv)
            except AttributeError:
                # Резервный надежный способ, если прошивка не поддерживает cast()
                b = bytearray(mv)
                for i in range(0, num_bytes, 2):
                    s = b[i] | (b[i+1] << 8)
                    if s > 32767:
                        s -= 65536
                    s = (s * gain_int) >> 8
                    b[i] = s & 0xFF
                    b[i+1] = (s >> 8) & 0xFF
                i2s.write(b)
        else:
            # Моно с затуханием (конвертируем в стерео)
            out_buf = bytearray(num_bytes * 2)
            b = memoryview(buf)[:num_bytes]
            for i in range(0, num_bytes, 2):
                s = b[i] | (b[i+1] << 8)
                if s > 32767:
                    s -= 65536
                s = (s * gain_int) >> 8
                
                low = s & 0xFF
                high = (s >> 8) & 0xFF
                
                out_buf[i*2] = low
                out_buf[i*2+1] = high
                out_buf[i*2+2] = low
                out_buf[i*2+3] = high
            i2s.write(out_buf)

    except Exception as e:
        # Пропускаем ошибки записи
        pass

    """Запись PCM в I2S с обработкой IN-PLACE (без пауз Garbage Collector'а)."""
    log.info("[TRACE ENTER] write_pcm_with_gain()")
    if not i2s or num_bytes <= 0:
        return

    # Выравнивание по четному количеству байт (16 бит = 2 байта)
    num_bytes = num_bytes & ~1
    if num_bytes <= 0:
        return

    try:
        # 1. БЫСТРЫЙ ПУТЬ: полная громкость, стерео (играет 95% времени).
        # Никакой математики, отправляем напрямую в железо.
        if channels == 2 and gain >= 0.99:
            i2s.write(memoryview(buf)[:num_bytes])
            return

        # 2. ПОЛНАЯ ТИШИНА: отправляем нули.
        if gain <= 0.001:
            if channels == 1:
                i2s.write(bytes(num_bytes * 2))
            else:
                i2s.write(bytes(num_bytes))
            return

        # 3. ПЛАВНОЕ ЗАТУХАНИЕ (Fade-Out)
        # ВАЖНО: Мы переписываем значения прямо поверх старых байт в памяти (b = buf).
        # Это исключает выделение новой памяти и полностью убирает треск от GC.
        gain_int = int(gain * 256)
        b = buf  # локальная ссылка работает быстрее

        if channels == 2:
            # Быстрый цикл для Стерео
            for i in range(0, num_bytes, 2):
                # Читаем 16 бит (Little Endian)
                s = b[i] | (b[i+1] << 8)
                # Знаковое расширение
                if s > 32767:
                    s -= 65536
                
                # Применяем громкость быстрой математикой
                s = (s * gain_int) >> 8
                
                # Записываем обратно в тот же буфер (IN-PLACE)
                b[i] = s & 0xFF
                b[i+1] = (s >> 8) & 0xFF
            
            i2s.write(memoryview(b)[:num_bytes])
            
        else:
            # Для моно (Mono to Stereo) приходится создать буфер удваивания
            out_buf = bytearray(num_bytes * 2)
            for i in range(0, num_bytes, 2):
                s = b[i] | (b[i+1] << 8)
                if s > 32767:
                    s -= 65536
                    
                s = (s * gain_int) >> 8
                
                low = s & 0xFF
                high = (s >> 8) & 0xFF
                
                # Записываем в левый и правый каналы
                out_idx = i * 2
                out_buf[out_idx] = low
                out_buf[out_idx+1] = high
                out_buf[out_idx+2] = low
                out_buf[out_idx+3] = high
                
            i2s.write(out_buf)

    except Exception as e:
        log.warning(f"Ошибка записи PCM: {e}")
    log.debug("[TRACE EXIT] write_pcm_with_gain")



    """Запись PCM в I2S с быстрым масштабированием сэмплов и автодублированием Mono->Stereo."""
    if not i2s or num_bytes <= 0:
        return

    num_bytes = num_bytes - (num_bytes % 2)
    if num_bytes <= 0:
        return

    try:
        # 1. БЫСТРЫЙ ПУТЬ (играет 95% времени).
        # Если стерео и полная громкость, отправляем сырые байты без создания массивов.
        # Это исключает нагрузку на процессор и сборщик мусора (GC), мелодия будет идеальной.
        if channels == 2 and gain >= 0.99:
            i2s.write(memoryview(buf)[:num_bytes])
            return

        # 2. ПОЛНАЯ ТИШИНА: мгновенный выход.
        if gain <= 0.001:
            if channels == 1:
                i2s.write(bytearray(num_bytes * 2))
            else:
                i2s.write(bytearray(num_bytes))
            return

        # 3. ОБРАБОТКА (Fade-out или Моно -> Стерео):
        # Сюда код заходит только в последние 1-2 секунды трека или если файл моно.
        samples = array.array('h', memoryview(buf)[:num_bytes])
        gain_int = int(gain * 256)

        if channels == 1:
            # Конвертация моно в стерео
            out_samples = array.array('h', [0] * (len(samples) * 2))
            if gain >= 0.99:
                for i in range(len(samples)):
                    s = samples[i]
                    out_samples[i * 2] = s
                    out_samples[i * 2 + 1] = s
            else:
                for i in range(len(samples)):
                    s = (samples[i] * gain_int) >> 8
                    out_samples[i * 2] = s
                    out_samples[i * 2 + 1] = s
            i2s.write(out_samples)
            
        else:
            # Стерео с плавным затуханием (быстрая математика)
            for i in range(len(samples)):
                samples[i] = (samples[i] * gain_int) >> 8
            i2s.write(samples)
            
    except Exception as e:
        log.warning(f"Ошибка записи PCM: {e}")

    """Запись PCM в I2S с быстрым масштабированием сэмплов и автодублированием Mono->Stereo."""
    if not i2s or num_bytes <= 0:
        return

    num_bytes = num_bytes - (num_bytes % 2)
    if num_bytes <= 0:
        return

    try:
        # Нативный (C-уровень) парсинг массива байт в 16-битные знаковые целые числа (signed short).
        # Little-Endian на ESP32 идеально совпадает с форматом WAV. Это работает мгновенно.
        samples = array.array('h', memoryview(buf)[:num_bytes])

        if channels == 1:
            # Конвертация моно в стерео
            out_samples = array.array('h', [0] * (len(samples) * 2))
            
            if gain < 0.99:
                # Переход к целочисленной математике (0.0 - 1.0 -> 0 - 256)
                gain_int = int(gain * 256)
                for i in range(len(samples)):
                    # Сдвиг >> 8 эквивалентен делению на 256, но работает значительно быстрее
                    s = (samples[i] * gain_int) >> 8
                    out_samples[i * 2] = s
                    out_samples[i * 2 + 1] = s
            else:
                for i in range(len(samples)):
                    s = samples[i]
                    out_samples[i * 2] = s
                    out_samples[i * 2 + 1] = s
            
            i2s.write(out_samples)
            
        else:
            # Обработка стерео
            if gain >= 0.99:
                # Громкость 100% — пишем напрямую, без циклов
                i2s.write(samples)
            elif gain <= 0.001:
                # Тишина
                i2s.write(bytearray(num_bytes))
            else:
                # Быстрое применение затухания через целочисленную математику
                gain_int = int(gain * 256)
                for i in range(len(samples)):
                    samples[i] = (samples[i] * gain_int) >> 8
                
                # I2S умеет напрямую принимать объекты array
                i2s.write(samples)
                
    except Exception as e:
        log.warning(f"Ошибка записи PCM: {e}")

    """Запись PCM в I2S с масштабированием знаковых сэмплов и автодублированием Mono->Stereo."""
    log.debug("[TRACE ENTER] write_pcm_with_gain(num_bytes=%s, gain=%s, channels=%s)", num_bytes, gain, channels)
    if not i2s or num_bytes <= 0:
        log.debug("[TRACE EXIT] write_pcm_with_gain (no i2s or num_bytes <= 0)")
        return

    num_bytes = num_bytes - (num_bytes % 2)
    if num_bytes <= 0:
        return

    try:
        if channels == 1:
            num_samples = num_bytes // 2
            out_buf = bytearray(num_bytes * 2)

            for i in range(num_samples):
                idx = i * 2
                s = buf[idx] | (buf[idx + 1] << 8)
                if s & 0x8000:
                    s -= 65536

                if gain < 0.99:
                    s = int(s * gain)

                if s < 0:
                    s += 65536

                b_low = s & 0xFF
                b_high = (s >> 8) & 0xFF

                out_idx = i * 4
                out_buf[out_idx] = b_low
                out_buf[out_idx + 1] = b_high
                out_buf[out_idx + 2] = b_low
                out_buf[out_idx + 3] = b_high

            i2s.write(out_buf)
        else:
            if gain >= 0.99:
                i2s.write(memoryview(buf)[:num_bytes])
            elif gain <= 0.001:
                i2s.write(bytearray(num_bytes))
            else:
                pcm_data = bytearray(memoryview(buf)[:num_bytes])
                num_samples = num_bytes // 2

                for i in range(num_samples):
                    idx = i * 2
                    s = pcm_data[idx] | (pcm_data[idx + 1] << 8)
                    if s & 0x8000:
                        s -= 65536

                    s = int(s * gain)

                    if s < 0:
                        s += 65536

                    pcm_data[idx] = s & 0xFF
                    pcm_data[idx + 1] = (s >> 8) & 0xFF

                i2s.write(pcm_data)
    except Exception as e:
        log.warning(f"Ошибка записи PCM: {e}")
    log.debug("[TRACE EXIT] write_pcm_with_gain")
import machine

def write_pcm_with_gain(i2s, buf, num_bytes, gain, channels=2, _mono_cache=[bytearray(8192)]):
    """Аппаратное изменение громкости без нагрузки на CPU и без выделения памяти."""
    try:
        log.debug("[TRACE ENTER] write_pcm_with_gain(num_bytes=%s, gain=%s, channels=%s)", num_bytes, gain, channels)
    except:
        pass

    if not i2s or num_bytes <= 0:
        return

    # Выравнивание по четному числу байт (защита от сбоев 16-битного аудио)
    num_bytes = num_bytes & ~1
    if num_bytes <= 0:
        return

    try:
        mv = memoryview(buf)[:num_bytes]

        # 1. Расчет сдвига громкости
        # В MicroPython нет плавного float-затухания без циклов. Мы делаем ступенчатое 
        # логарифмическое затухание (по -6dB). Для уха это звучит даже естественнее.
        shift = 0
        if gain <= 0.001:
            shift = -16  # Полная тишина (сдвигаем все биты)
        elif gain < 0.99:
            temp_gain = gain
            while temp_gain < 0.75 and shift > -15:
                temp_gain *= 2.0
                shift -= 1

        # 2. АППАРАТНОЕ ЗАТУХАНИЕ (C-уровень, 0% CPU)
        if shift < 0:
            # Сдвигает биты прямо в оперативной памяти без участия Python-циклов
            machine.I2S.shift(buf=mv, bits=16, shift=shift)

        # 3. Отправка в I2S
        if channels == 2:
            i2s.write(mv)
        else:
            # Для моно мы предотвращаем выделение памяти (сохраняем буфер в кэше)
            # Это спасет от заиканий при загрузке моно-звуков
            if len(_mono_cache[0]) < num_bytes * 2:
                _mono_cache[0] = bytearray(num_bytes * 2)
            
            mb = memoryview(_mono_cache[0])
            for i in range(0, num_bytes, 2):
                mb[i*2]   = mv[i]
                mb[i*2+1] = mv[i+1]
                mb[i*2+2] = mv[i]
                mb[i*2+3] = mv[i+1]
                
            i2s.write(mb[:num_bytes * 2])

    except Exception as e:
        try:
            log.warning(f"Ошибка записи PCM: {e}")
        except:
            pass            
    log.debug("[TRACE EXIT] write_pcm_with_gain")

async def stream_wav(f, ibuf, pins, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=0, start_pos_sec=0.0, stop_checker=None, yield_ms=0, pos_container=None):
    """Потоковое воспроизведение WAV файлов."""
    log.info("[TRACE ENTER] stream_wav(start_pos_bytes=%s, start_pos_sec=%s, max_ms=%s, fade_ms=%s)",
             start_pos_bytes, start_pos_sec, max_ms, fade_out_ms)
    wav_fmt = parse_wav_header(f)
    if not wav_fmt:
        log.error("Файл не является валидным WAV!")
        log.info("[TRACE EXIT] stream_wav -> False")
        return False, 0, 0.0

    channels, rate, bits, data_size, data_offset = wav_fmt
    log.info(f"Параметры WAV: {rate} Hz, {bits} bit, channels={channels}, data={data_size} B")

    bytes_per_sec = rate * channels * (bits // 8) if (rate and channels and bits) else 176400
    frame_align = channels * (bits // 8)
    
    bck, ws, sd, i2s_id = pins
    i2s_obj = init_hardware_i2s(
        rate=rate, bits=bits,
        channels=2 if channels == 1 else channels,
        ibuf=ibuf, bck_pin=bck, ws_pin=ws, sd_pin=sd, i2s_id=i2s_id
    )

    if start_pos_bytes == 0 and start_pos_sec > 0:
        start_pos_bytes = data_offset + int(start_pos_sec * bytes_per_sec)

    if start_pos_bytes > data_offset and start_pos_bytes < (data_offset + data_size):
        seek_pos = data_offset + ((start_pos_bytes - data_offset) // frame_align) * frame_align
        f.seek(seek_pos)
        log.info(f"Возобновление WAV с позиции {seek_pos} B / {start_pos_sec} сек")

    bytes_per_ms = bytes_per_sec / 1000.0
    buf = bytearray(4096)
    bytes_read_total = f.tell() - data_offset

    cur_pos_b = f.tell()
    cur_pos_s = max(0.0, (cur_pos_b - data_offset) / bytes_per_sec)

    while True:
        if stop_checker and stop_checker():
            log.info("Воспроизведение WAV прервано внешней командой stop_checker.")
            break

        elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)

        if max_ms > 0 and elapsed_ms >= max_ms:
            log.info(f"Достигнут лимит времени воспроизведения ({max_ms} ms)")
            break

        remaining_pcm = data_size - bytes_read_total
        if remaining_pcm <= 0:
            log.info("Достигнут конец PCM-данных (data_size). Завершение проигрывания.")
            cur_pos_b = 0
            cur_pos_s = 0.0
            break

        to_read = min(len(buf), remaining_pcm)
        to_read = (to_read // frame_align) * frame_align
        if to_read == 0:
            break

        num_read = f.readinto(memoryview(buf)[:to_read])
        if not num_read:
            cur_pos_b = 0
            cur_pos_s = 0.0
            break

        bytes_read_total += num_read
        cur_pos_b = data_offset + bytes_read_total
        cur_pos_s = bytes_read_total / bytes_per_sec

        if pos_container is not None:
            pos_container.current_pos_bytes = cur_pos_b
            pos_container.current_pos_sec = cur_pos_s

        gain = 1.0

        if max_ms > 0 and fade_out_ms > 0:
            rem_ms = max_ms - elapsed_ms
            if rem_ms <= fade_out_ms:
                gain = max(0.0, min(1.0, rem_ms / fade_out_ms))
        elif is_last_repeat and fade_out_ms > 0 and data_size > 0:
            bytes_left = data_size - bytes_read_total
            ms_left = bytes_left / bytes_per_ms
            if ms_left <= fade_out_ms:
                gain = max(0.0, min(1.0, ms_left / fade_out_ms))

        write_pcm_with_gain(i2s_obj, buf, num_read, gain, channels=channels)

        if yield_ms > 0:
            await asyncio.sleep_ms(yield_ms)

    log.info("[TRACE EXIT] stream_wav -> True")
    return True, cur_pos_b, cur_pos_s

async def stream_mp3(f, file_size, ibuf, pins, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=0, start_pos_sec=0.0, stop_checker=None, yield_ms=0, pos_container=None):
    """Потоковое воспроизведение MP3 файлов через mp3dec."""
    log.info("[TRACE ENTER] stream_mp3(file_size=%s, start_pos_bytes=%s, start_pos_sec=%s)",
             file_size, start_pos_bytes, start_pos_sec)
    if not mp3dec:
        log.error("C-модуль mp3dec не найден в прошивке!")
        log.info("[TRACE EXIT] stream_mp3 -> False")
        return False, 0, 0.0

    log.info(f"Параметры MP3 файла: размер {file_size} B")
    bytes_per_sec = 16000

    if start_pos_bytes == 0 and start_pos_sec > 0:
        start_pos_bytes = int(start_pos_sec * bytes_per_sec)

    if start_pos_bytes > 0 and start_pos_bytes < file_size:
        f.seek(start_pos_bytes)
        log.info(f"Возобновление MP3 с позиции {start_pos_bytes} B / {start_pos_sec} сек")

    bck, ws, sd, i2s_id = pins
    i2s_obj = init_hardware_i2s(
        rate=44100, bits=16, channels=2,
        ibuf=ibuf, bck_pin=bck, ws_pin=ws, sd_pin=sd, i2s_id=i2s_id
    )
    decoder = mp3dec.Decoder()
    pcm_buf = bytearray(4096)
    bytes_read_from_file = f.tell()

    cur_pos_b = f.tell()
    cur_pos_s = cur_pos_b / bytes_per_sec

    while True:
        if stop_checker and stop_checker():
            log.info("Воспроизведение MP3 прервано внешней командой stop_checker.")
            break

        elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)

        if max_ms > 0 and elapsed_ms >= max_ms:
            log.info(f"Достигнут лимит времени воспроизведения ({max_ms} ms)")
            break

        cur_pos_b = f.tell()
        cur_pos_s = cur_pos_b / bytes_per_sec

        if pos_container is not None:
            pos_container.current_pos_bytes = cur_pos_b
            pos_container.current_pos_sec = cur_pos_s

        chunk = f.read(1024)
        if not chunk:
            cur_pos_b = 0
            cur_pos_s = 0.0
            break

        bytes_read_from_file += len(chunk)
        decoder.write(chunk)

        while decoder.has_pcm():
            if stop_checker and stop_checker():
                break

            pcm_bytes = decoder.read_pcm(pcm_buf)
            if pcm_bytes > 0:
                elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)
                gain = 1.0

                if max_ms > 0 and fade_out_ms > 0:
                    rem_ms = max_ms - elapsed_ms
                    if rem_ms <= fade_out_ms:
                        gain = max(0.0, min(1.0, rem_ms / fade_out_ms))
                elif is_last_repeat and fade_out_ms > 0 and file_size > 0:
                    file_bytes_left = file_size - bytes_read_from_file
                    ms_left = file_bytes_left / 16.0
                    if ms_left <= fade_out_ms:
                        gain = max(0.0, min(1.0, ms_left / fade_out_ms))

                write_pcm_with_gain(i2s_obj, pcm_buf, pcm_bytes, gain, channels=2)

                if yield_ms > 0:
                    await asyncio.sleep_ms(yield_ms)

    log.info("[TRACE EXIT] stream_mp3 -> True")
    return True, cur_pos_b, cur_pos_s

async def play_audio_track(mode='boot', filepath=None, ibuf=8192, stop_checker=None, yield_ms=1, pos_container=None, config=None, **kwargs):
    """
    Интегрированная функция управления воспроизведением.
    Самостоятельно вычитывает пины и параметры из config.json.
    """
    log.info("[TRACE ENTER] play_audio_track(mode=%s, filepath=%s, ibuf=%s)", mode, filepath, ibuf)

    if config is None:
        config = load_config()

    # Считывание назначений пинов из конфигурации (с безопасными фолбэками)
    bck = config.get('i2s_bck_pin', 15)
    ws = config.get('i2s_ws_pin', 16)
    sd = config.get('i2s_sd_pin', 17)
    i2s_id = config.get('i2s_id', 0)
    pins = (bck, ws, sd, i2s_id)

    if filepath is None:
        media_dir = config.get('media_dir', '/media')
        target = config.get('target_filename', 'bell.wav')
        filepath = f"{media_dir}/{target}"

    try:
        file_size = os.stat(filepath)[6]
    except OSError:
        log.error(f"Файл {filepath} не найден!")
        log.info("[TRACE EXIT] play_audio_track -> False (file not found)")
        return False

    max_duration_sec = kwargs.get('max_duration_sec', config.get('max_play_duration_sec', 0))
    fade_out_ms = kwargs.get('fade_out_ms', config.get('fade_out_ms', 1000))
    resume_playback = kwargs.get('resume_playback', config.get('resume_playback', True))
    start_pos_bytes = kwargs.get('start_pos_bytes', config.get('last_play_pos_bytes', 0))
    start_pos_sec = kwargs.get('start_pos_sec', config.get('last_play_pos_sec', 0.0))

    if mode == 'boot':
        repeat_count = kwargs.get('repeat_count', config.get('repeat_count', 1))
    else:
        repeat_count = kwargs.get('repeat_count', 1)

    initial_seek_bytes = start_pos_bytes if resume_playback else 0
    initial_seek_sec = start_pos_sec if resume_playback else 0.0

    if pos_container is not None:
        pos_container.current_pos_bytes = initial_seek_bytes
        pos_container.current_pos_sec = initial_seek_sec

    max_ms = int(max_duration_sec * 1000) if max_duration_sec > 0 else 0
    start_ticks = time.ticks_ms()

    log.info(f"Открытие аудиофайла {filepath} [{mode.upper()} MODE]...")
    log.info(f"Пины I2S: BCK={bck}, WS={ws}, SD={sd}, ID={i2s_id}")
    log.info(f"Параметры сессии: повторов={repeat_count}, лимит={max_duration_sec}s, fade={fade_out_ms}ms, resume={resume_playback}, start_pos={initial_seek_bytes}B ({initial_seek_sec}s)")

    final_pos_bytes = initial_seek_bytes
    final_pos_sec = initial_seek_sec

    try:
        for rep in range(repeat_count):
            if stop_checker and stop_checker():
                log.info("Цикл повторов прерван внешним сигналом остановки.")
                break

            elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ticks)
            if max_ms > 0 and elapsed_ms >= max_ms:
                log.info("Прерывание цикла повторов по лимиту времени.")
                break

            is_last_repeat = (rep == repeat_count - 1)
            current_seek_b = initial_seek_bytes if rep == 0 else 0
            current_seek_s = initial_seek_sec if rep == 0 else 0.0
            log.info(f"Запуск итерации проигрывания {rep + 1}/{repeat_count}...")

            with open(filepath, "rb") as f:
                if filepath.lower().endswith(".wav"):
                    res, final_pos_bytes, final_pos_sec = await stream_wav(
                        f, ibuf, pins, start_ticks, max_ms, fade_out_ms, is_last_repeat,
                        start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s,
                        stop_checker=stop_checker, yield_ms=yield_ms, pos_container=pos_container
                    )
                else:
                    res, final_pos_bytes, final_pos_sec = await stream_mp3(
                        f, file_size, ibuf, pins, start_ticks, max_ms, fade_out_ms, is_last_repeat,
                        start_pos_bytes=current_seek_b, start_pos_sec=current_seek_s,
                        stop_checker=stop_checker, yield_ms=yield_ms, pos_container=pos_container
                    )

    except Exception as e:
        log.error(f"Ошибка в цикле play_audio_track: {e}")
    finally:
        if resume_playback:
            save_position_to_config(final_pos_bytes, final_pos_sec, config)
        deinit_hardware_i2s()
        log.info("Воспроизведение аудиофайла полностью завершено, I2S освобожден.")

    log.info("[TRACE EXIT] play_audio_track -> True")
    return True