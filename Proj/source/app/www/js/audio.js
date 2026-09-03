// ==========================================
// 2. ОБРАБОТКА И КОДИРОВАНИЕ АУДИО
// ==========================================
// Примечание: setStatusMessage() определена в app.js (загружается после
// этого файла). Это безопасно, т.к. функции этого файла вызываются только
// в обработчиках событий (onchange/onclick) уже после полной загрузки
// всех трёх скриптов, а не во время самого разбора audio.js.

let currentAudioUrl = null;
let convertedWavBlob = null;
let originalAudioBuffer = null; // Хранение исходного буфера для многократной обрезки

// Целевые параметры WAV-файла для ESP32: пониженная частота дискретизации
// и моно-звук уменьшают размер файла и нагрузку на I2S/DMA при воспроизведении.
const TARGET_SAMPLE_RATE = 32000;
const TARGET_CHANNELS = 1;

function getConvertedWavBlob() {
    return convertedWavBlob;
}

function clearAudioState() {
    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
        currentAudioUrl = null;
    }
    convertedWavBlob = null;
    originalAudioBuffer = null;
}

/**
 * Ресемплирует и сводит в моно исходный AudioBuffer через OfflineAudioContext,
 * приводя его к TARGET_SAMPLE_RATE / TARGET_CHANNELS перед кодированием в WAV.
 * Раньше в файл писались исходные частота дискретизации и число каналов файла —
 * теперь они всегда унифицированы под требования ESP32.
 * @param {AudioBuffer} audioBuffer - декодированный браузером исходный буфер
 * @returns {Promise<AudioBuffer>} буфер 32000 Гц, моно
 */
async function resampleToTargetFormat(audioBuffer) {
    console.log("[TRACE ENTER] resampleToTargetFormat", { srcSampleRate: audioBuffer.sampleRate, srcChannels: audioBuffer.numberOfChannels, targetSampleRate: TARGET_SAMPLE_RATE, targetChannels: TARGET_CHANNELS });
    const offlineCtx = new OfflineAudioContext(
        TARGET_CHANNELS,
        Math.ceil(audioBuffer.duration * TARGET_SAMPLE_RATE),
        TARGET_SAMPLE_RATE
    );

    const source = offlineCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(offlineCtx.destination);
    source.start();

    const renderedBuffer = await offlineCtx.startRendering();
    console.log("[TRACE EXIT] resampleToTargetFormat -> rendered", { duration: renderedBuffer.duration, sampleRate: renderedBuffer.sampleRate, channels: renderedBuffer.numberOfChannels });
    return renderedBuffer;
}

async function audioBufferToWavBlob(audioBuffer, maxSizeBytes) {
    console.log("[TRACE ENTER] audioBufferToWavBlob", { duration: audioBuffer.duration, channels: audioBuffer.numberOfChannels, sampleRate: audioBuffer.sampleRate, maxSizeBytes });
    try {
        // Приводим исходный буфер к 32000 Гц / моно перед кодированием.
        const targetBuffer = await resampleToTargetFormat(audioBuffer);

        const numOfChan = targetBuffer.numberOfChannels;
        const sampleRate = targetBuffer.sampleRate;
        const bytesPerFrame = numOfChan * 2;

        // Защита от некорректного/слишком маленького лимита размера файла:
        // WAV-заголовок сам по себе занимает 44 байта, поэтому при
        // maxSizeBytes <= 44 не должно получаться отрицательное число кадров.
        const maxDataBytes = Math.max(0, maxSizeBytes - 44);
        const maxFrames = Math.floor(maxDataBytes / bytesPerFrame);
        const framesToEncode = Math.min(targetBuffer.length, maxFrames);
        const dataChunkSize = framesToEncode * bytesPerFrame;
        const fileLength = dataChunkSize + 44;

        const buffer = new ArrayBuffer(fileLength);
        const view = new DataView(buffer);
        let pos = 0;

        function setUint16(data) { view.setUint16(pos, data, true); pos += 2; }
        function setUint32(data) { view.setUint32(pos, data, true); pos += 4; }

        setUint32(0x46464952); // "RIFF"
        setUint32(fileLength - 8);
        setUint32(0x45564157); // "WAVE"
        setUint32(0x20746d66); // "fmt "
        setUint32(16);
        setUint16(1);          // PCM
        setUint16(numOfChan);
        setUint32(sampleRate);
        setUint32(sampleRate * bytesPerFrame);
        setUint16(bytesPerFrame);
        setUint16(16);
        setUint32(0x61746164); // "data"
        setUint32(dataChunkSize);

        const channels = [];
        for (let i = 0; i < numOfChan; i++) {
            channels.push(targetBuffer.getChannelData(i));
        }

        for (let offset = 0; offset < framesToEncode; offset++) {
            for (let i = 0; i < numOfChan; i++) {
                let sample = Math.max(-1, Math.min(1, channels[i][offset]));
                sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0;
                view.setInt16(pos, sample, true);
                pos += 2;
            }
        }

        const blob = new Blob([buffer], { type: "audio/wav" });
        console.log("[TRACE EXIT] audioBufferToWavBlob -> blob size: " + blob.size + " B");
        return blob;
    } catch (err) {
        console.error("[TRACE EXIT] audioBufferToWavBlob -> error", err);
        return null;
    }
}

async function handleFileSelect(event) {
    console.log("[TRACE ENTER] handleFileSelect", event.target.files[0] ? event.target.files[0].name : "No file");
    const file = event.target.files[0];
    const previewContainer = document.getElementById('audioPreviewContainer');
    const cropContainer = document.getElementById('cropContainer');
    const status = document.getElementById('status');

    clearAudioState();

    if (!file) {
        if (previewContainer) previewContainer.style.display = 'none';
        if (cropContainer) cropContainer.style.display = 'none';
        console.log("[TRACE EXIT] handleFileSelect (file cleared)");
        return;
    }

    setStatusLoading(status, 'Декодирование файла...');
    // На время конвертации блокируем повторный выбор файла, чтобы не запустить
    // два параллельных декодирования одного и того же input'а.
    event.target.disabled = true;

    try {
        const arrayBuffer = await file.arrayBuffer();
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

        // Сохраняем оригинал для возможности повторной обрезки без передекодирования
        originalAudioBuffer = audioBuffer;

        // Инициализируем UI обрезки
        if (cropContainer) {
            cropContainer.style.display = 'block';
            const duration = audioBuffer.duration;
            const startInput = document.getElementById('cropStart');
            const endInput = document.getElementById('cropEnd');
            startInput.value = 0;
            startInput.max = duration.toFixed(2);
            endInput.value = duration.toFixed(2);
            endInput.max = duration.toFixed(2);
        }

        // Выполняем обрезку и ресемплинг по умолчанию (весь файл)
        await applyCrop();
        console.log("[TRACE EXIT] handleFileSelect -> Decode completed successfully");
    } catch (e) {
        console.error("[TRACE EXIT] handleFileSelect -> Error", e);
        setStatusMessage(status, `❌ Ошибка чтения аудио: ${e.message}`, 'error');
        if (previewContainer) previewContainer.style.display = 'none';
        if (cropContainer) cropContainer.style.display = 'none';
    } finally {
        event.target.disabled = false;
    }
}

async function applyCrop() {
    console.log("[TRACE ENTER] applyCrop");
    const status = document.getElementById('status');
    const previewContainer = document.getElementById('audioPreviewContainer');
    const audioPreview = document.getElementById('audioPreview');
    const previewLabel = document.getElementById('previewLabel');
    const cropBtn = document.getElementById('cropBtn');

    if (!originalAudioBuffer) {
        console.warn("[TRACE EXIT] applyCrop -> no originalAudioBuffer");
        return;
    }

    if (cropBtn) cropBtn.disabled = true;
    setStatusLoading(status, 'Обрезка и ресемплинг файла (32000 Гц, моно)...');

    let start = parseFloat(document.getElementById('cropStart').value) || 0;
    let end = parseFloat(document.getElementById('cropEnd').value) || originalAudioBuffer.duration;

    if (start < 0) start = 0;
    if (end > originalAudioBuffer.duration) end = originalAudioBuffer.duration;
    
    if (start >= end) {
        setStatusMessage(status, '❌ Начало отрезка должно быть раньше конца', 'error');
        if (cropBtn) cropBtn.disabled = false;
        console.warn("[TRACE EXIT] applyCrop -> invalid range");
        return;
    }

    try {
        const sampleRate = originalAudioBuffer.sampleRate;
        const channels = originalAudioBuffer.numberOfChannels;
        const startOffset = Math.floor(start * sampleRate);
        const endOffset = Math.floor(end * sampleRate);
        const frameCount = endOffset - startOffset;

        if (frameCount <= 0) {
            throw new Error("Длина выбранного отрезка слишком мала");
        }

        // Создаем новый AudioBuffer для нужного отрезка
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const croppedBuffer = audioCtx.createBuffer(channels, frameCount, sampleRate);

        for (let i = 0; i < channels; i++) {
            const channelData = originalAudioBuffer.getChannelData(i);
            const croppedData = croppedBuffer.getChannelData(i);
            for (let j = 0; j < frameCount; j++) {
                croppedData[j] = channelData[startOffset + j];
            }
        }

        const maxBytes = savedMaxFileBytes > 0 ? savedMaxFileBytes : 4194304;
        
        // Передаем обрезанный кусок на ресемплинг и кодировку в WAV
        convertedWavBlob = await audioBufferToWavBlob(croppedBuffer, maxBytes);
        
        if (!convertedWavBlob) {
            throw new Error("Не удалось сформировать WAV-файл");
        }

        const sizeMB = (convertedWavBlob.size / (1024 * 1024)).toFixed(2);
        const durationSec = (convertedWavBlob.size / (TARGET_SAMPLE_RATE * TARGET_CHANNELS * 2)).toFixed(1);

        if (currentAudioUrl) {
            URL.revokeObjectURL(currentAudioUrl);
        }
        currentAudioUrl = URL.createObjectURL(convertedWavBlob);
        
        if (audioPreview && previewContainer) {
            audioPreview.src = currentAudioUrl;
            previewContainer.style.display = 'block';
        }

        if (previewLabel) {
            previewLabel.innerText = `Предпросмотр WAV (${durationSec} сек, ${sizeMB} МБ):`;
        }

        setStatusMessage(status, `✅ Конвертировано в WAV (${durationSec} сек, ${sizeMB} МБ)`, 'success');
        console.log("[TRACE EXIT] applyCrop -> Success");
    } catch (e) {
        console.error("[TRACE EXIT] applyCrop -> Error", e);
        setStatusMessage(status, `❌ Ошибка обрезки: ${e.message}`, 'error');
    } finally {
        if (cropBtn) cropBtn.disabled = false;
    }
}

async function startUpload() {
    console.log("[TRACE ENTER] startUpload");
    const status = document.getElementById('status');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');
    const uploadBtn = document.getElementById('uploadBtn');

    if (!convertedWavBlob) {
        setStatusMessage(status, '❌ Выберите корректный аудиофайл!', 'error');
        console.warn("[TRACE EXIT] startUpload -> No blob to upload");
        return;
    }

    setButtonLoading(uploadBtn, true, 'Загрузка...');
    setStatusLoading(status, 'Подготовка токена...');

    try {
        const headers = await getAuthHeaders();
        if (!headers['X-Auth-Nonce']) {
            throw new Error("Не удалось получить заголовки авторизации");
        }

        setStatusLoading(status, 'Загрузка WAV файла на ESP32...');
        progressBar.style.display = "block";
        progressFill.style.width = "0%";

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload', true);
        xhr.setRequestHeader('X-Auth-Nonce', headers['X-Auth-Nonce']);
        xhr.setRequestHeader('X-Auth-Hash', headers['X-Auth-Hash']);
        xhr.setRequestHeader('X-File-Name', 'bell.wav');

        xhr.upload.onprogress = function(e) {
            if (e.lengthComputable) {
                // Здесь без спиннера намеренно: сам прогресс-бар (progressFill)
                // уже является индикатором загрузки для этого этапа.
                const percent = Math.round((e.loaded / e.total) * 100);
                progressFill.style.width = percent + "%";
                setStatusMessage(status, `⏳ Передача: ${percent}%`);
            }
        };

        xhr.onload = function() {
            setButtonLoading(uploadBtn, false);
            if (xhr.status === 200) {
                setStatusMessage(status, `✅ ${xhr.responseText}`, 'success');
                console.log("[TRACE EXIT] startUpload -> XHR Upload 200 OK");
                loadSystemInfo();
            } else {
                setStatusMessage(status, `❌ ${xhr.responseText}`, 'error');
                console.warn("[TRACE EXIT] startUpload -> XHR Upload Error", xhr.status);
                progressFill.style.width = "0%";
            }
        };

        xhr.onerror = function() {
            console.error("[TRACE EXIT] startUpload -> XHR Network error");
            setButtonLoading(uploadBtn, false);
            setStatusMessage(status, '❌ Сбой сети при передаче файла', 'error');
        };

        xhr.send(convertedWavBlob);

    } catch (err) {
        console.error("[TRACE EXIT] startUpload -> Exception", err);
        setButtonLoading(uploadBtn, false);
        setStatusMessage(status, `❌ Ошибка: ${err.message}`, 'error');
    }
}