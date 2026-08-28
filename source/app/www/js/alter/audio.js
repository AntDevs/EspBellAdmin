// Обработка и ресемплинг аудио в 32000 Гц Mono WAV
async function processAudioToWav(file, onProgress) {
    if (onProgress) onProgress("Декодирование аудио браузером...", 30);
    const arrayBuffer = await file.arrayBuffer();
    
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const decodedBuffer = await audioCtx.decodeAudioData(arrayBuffer);

    if (onProgress) onProgress("Оптимизация (32000 Hz, Моно)...", 50);
    const TARGET_SAMPLE_RATE = 32000;
    const TARGET_CHANNELS = 1; // Mono для снижения нагрузки на ESP32
    
    const offlineCtx = new OfflineAudioContext(
        TARGET_CHANNELS, 
        Math.ceil(decodedBuffer.duration * TARGET_SAMPLE_RATE), 
        TARGET_SAMPLE_RATE
    );

    const source = offlineCtx.createBufferSource();
    source.buffer = decodedBuffer;
    source.connect(offlineCtx.destination);
    source.start();

    const renderedBuffer = await offlineCtx.startRendering();

    if (onProgress) onProgress("Формирование WAV-файла...", 70);
    const wavBytes = encodeWAV(renderedBuffer);
    return new Blob([wavBytes], { type: 'audio/wav' });
}

// Генератор WAV формата из сырого PCM буфера (16-bit PCM Mono/Stereo)
function encodeWAV(audioBuffer) {
    const numChannels = audioBuffer.numberOfChannels;
    const sampleRate = audioBuffer.sampleRate;
    const format = 1; // PCM
    const bitDepth = 16;
    
    // Получаем Float32 массив аудиоданных (-1.0 .. 1.0)
    const result = audioBuffer.getChannelData(0);

    const buffer = new ArrayBuffer(44 + result.length * 2);
    const view = new DataView(buffer);

    const writeString = (view, offset, string) => {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    };

    // Заполнение WAV заголовков
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + result.length * 2, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); 
    view.setUint16(20, format, true); 
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * (bitDepth / 8), true); // ByteRate
    view.setUint16(32, numChannels * (bitDepth / 8), true); // BlockAlign
    view.setUint16(34, bitDepth, true);
    writeString(view, 36, 'data');
    view.setUint32(40, result.length * 2, true);

    // Конвертация Float32 в Int16 PCM
    let offset = 44;
    for (let i = 0; i < result.length; i++, offset += 2) {
        let s = Math.max(-1, Math.min(1, result[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return buffer;
}