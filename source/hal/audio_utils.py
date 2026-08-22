import json
import re
import struct
import array
import time
import logging
import uasyncio as asyncio

try:
    import mp3dec
except ImportError:
    mp3dec = None

log = logging.getLogger("AUDIO_UTILS")

def save_position_to_config(pos_bytes, pos_sec=0.0, config=None):
    """Общая функция сохранения позиции воспроизведения в config.json и оперативную память."""
    log.info("[TRACE ENTER] save_position_to_config(pos_bytes=%s, pos_sec=%s)", pos_bytes, pos_sec)
    if config is not None:
        config['last_play_pos_bytes'] = pos_bytes
        config['last_play_pos_sec'] = round(pos_sec, 2)
    try:
        with open('config.json', 'r') as fr:
            raw_content = fr.read()

        raw_content = re.sub(r'"last_play_pos_bytes"\s*:\s*\d+', f'"last_play_pos_bytes": {pos_bytes}', raw_content)
        
        if re.search(r'"last_play_pos_sec"\s*:\s*\d+(\.\d+)?', raw_content):
            raw_content = re.sub(r'"last_play_pos_sec"\s*:\s*\d+(\.\d+)?', f'"last_play_pos_sec": {round(pos_sec, 2)}', raw_content)

        with open('config.json', 'w') as fw:
            fw.write(raw_content)
        log.info(f"Сохранена позиция воспроизведения: {pos_bytes} B ({round(pos_sec, 2)} сек)")
    except Exception as e:
        log.error(f"Не удалось сохранить позицию в config.json: {e}")
    log.info("[TRACE EXIT] save_position_to_config")

def parse_wav_header(f):
    """Общий парсинг WAV-заголовков с фиксацией смещения и точного размера PCM-данных."""
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
    log.info("[TRACE EXIT] parse_wav_header -> channels=%s, rate=%s, bits=%s, data_size=%s, data_offset=%s", channels, rate, bits, data_size, data_offset)
    return res

def write_pcm_with_gain(i2s, buf, num_bytes, gain, channels=2):
    """
    Запись PCM в I2S с математическим масштабированием 16-битных сэмплов и поддержкой дублирования Mono->Stereo.
    """
    log.debug("[TRACE ENTER] write_pcm_with_gain(num_bytes=%s, gain=%s, channels=%s)", num_bytes, gain, channels)
    if not i2s or num_bytes <= 0:
        log.debug("[TRACE EXIT] write_pcm_with_gain (no i2s or num_bytes <= 0)")
        return

    num_bytes = num_bytes - (num_bytes % 2)
    if num_bytes <= 0:
        return

    try:
        if channels == 1:
            # Преобразование Mono 16-bit -> Stereo 16-bit для корректной работы ЦАП PCM5102A
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
            # Stereo 16-bit
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

async def stream_wav(f, init_i2s_cb, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=0, start_pos_sec=0.0, stop_checker=None, yield_ms=0, pos_container=None):
    """Единая функция проигрывания WAV потока с поддержкой позиционирования, затухания и проверок остановки."""
    log.info("[TRACE ENTER] stream_wav(start_pos_bytes=%s, start_pos_sec=%s, max_ms=%s, fade_ms=%s)", start_pos_bytes, start_pos_sec, max_ms, fade_out_ms)
    wav_fmt = parse_wav_header(f)
    if not wav_fmt:
        log.error("Файл не является валидным WAV!")
        log.info("[TRACE EXIT] stream_wav -> False")
        return False, 0, 0.0

    channels, rate, bits, data_size, data_offset = wav_fmt
    log.info(f"Параметры WAV: {rate} Hz, {bits} bit, channels={channels}, data={data_size} B")

    bytes_per_sec = rate * channels * (bits // 8) if (rate and channels and bits) else 176400
    frame_align = channels * (bits // 8)
    
    # Для моно-файлов инициализируем шину I2S в режиме Stereo для PCM5102A
    i2s_obj = init_i2s_cb(rate=rate, bits=bits, channels=2 if channels == 1 else channels)

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

async def stream_mp3(f, file_size, init_i2s_cb, start_ticks, max_ms, fade_out_ms, is_last_repeat, start_pos_bytes=0, start_pos_sec=0.0, stop_checker=None, yield_ms=0, pos_container=None):
    """Единая функция проигрывания MP3 потока с использованием C-модуля mp3dec."""
    log.info("[TRACE ENTER] stream_mp3(file_size=%s, start_pos_bytes=%s, start_pos_sec=%s)", file_size, start_pos_bytes, start_pos_sec)
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

    i2s_obj = init_i2s_cb(rate=44100, bits=16, channels=2)
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