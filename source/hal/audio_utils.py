import json
import re
import struct
import array
import logging

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
    """Общий парсинг WAV-заголовков с пропуском непроизводимых метаданных."""
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

def write_pcm_with_gain(i2s, buf, num_bytes, gain):
    """Общая функция записи PCM данных в I2S с масштабированием громкости."""
    log.debug("[TRACE ENTER] write_pcm_with_gain(num_bytes=%s, gain=%s)", num_bytes, gain)
    if not i2s:
        log.debug("[TRACE EXIT] write_pcm_with_gain (no i2s)")
        return
    try:
        if gain >= 0.99:
            i2s.write(buf[:num_bytes])
        elif gain <= 0.01:
            i2s.write(bytearray(num_bytes))
        else:
            arr = array.array('h', memoryview(buf)[:num_bytes])
            for i in range(len(arr)):
                arr[i] = int(arr[i] * gain)
            i2s.write(arr)
    except Exception as e:
        log.warning(f"Ошибка записи PCM: {e}")
    log.debug("[TRACE EXIT] write_pcm_with_gain")