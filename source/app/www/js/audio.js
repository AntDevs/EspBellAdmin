// ==========================================
// 2. ОБРАБОТКА И КОДИРОВАНИЕ АУДИО
// ==========================================

let currentAudioUrl = null;
let convertedWavBlob = null;

function getConvertedWavBlob() {
    return convertedWavBlob;
}

function clearAudioState() {
    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
        currentAudioUrl = null;
    }
    convertedWavBlob = null;
}

function audioBufferToWavBlob(audioBuffer, maxSizeBytes) {
    console.log("[TRACE ENTER] audioBufferToWavBlob", { duration: audioBuffer.duration, channels: audioBuffer.numberOfChannels, sampleRate: audioBuffer.sampleRate, maxSizeBytes });
    try {
        const numOfChan = audioBuffer.numberOfChannels;
        const sampleRate = audioBuffer.sampleRate;
        const bytesPerFrame = numOfChan * 2;
        
        const maxDataBytes = maxSizeBytes - 44;
        const maxFrames = Math.floor(maxDataBytes / bytesPerFrame);
        const framesToEncode = Math.min(audioBuffer.length, maxFrames);
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
            channels.push(audioBuffer.getChannelData(i));
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
    const audioPreview = document.getElementById('audioPreview');
    const status = document.getElementById('status');
    const previewLabel = document.getElementById('previewLabel');

    clearAudioState();

    if (!file) {
        if (previewContainer) previewContainer.style.display = 'none';
        console.log("[TRACE EXIT] handleFileSelect (file cleared)");
        return;
    }

    status.innerHTML = "⏳ Декодирование и конвертация файла в WAV...";

    try {
        const arrayBuffer = await file.arrayBuffer();
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

        const maxBytes = savedMaxFileBytes > 0 ? savedMaxFileBytes : 4194304;
        convertedWavBlob = audioBufferToWavBlob(audioBuffer, maxBytes);
        
        const sizeMB = (convertedWavBlob.size / (1024 * 1024)).toFixed(2);
        const durationSec = (convertedWavBlob.size / (audioBuffer.sampleRate * audioBuffer.numberOfChannels * 2)).toFixed(1);

        currentAudioUrl = URL.createObjectURL(convertedWavBlob);
        if (audioPreview && previewContainer) {
            audioPreview.src = currentAudioUrl;
            previewContainer.style.display = 'block';
        }

        if (previewLabel) {
            previewLabel.innerText = `Предпросмотр WAV (${durationSec} сек, ${sizeMB} МБ):`;
        }

        status.innerHTML = `<span style="color: #10b981;">✅ Конвертировано в WAV (${durationSec} сек, ${sizeMB} МБ)</span>`;
        console.log("[TRACE EXIT] handleFileSelect -> Conversion completed successfully");

    } catch (e) {
        console.error("[TRACE EXIT] handleFileSelect -> Error", e);
        status.innerHTML = `<span style="color: #ef4444;">❌ Ошибка конвертации аудио: ${e.message}</span>`;
        if (previewContainer) previewContainer.style.display = 'none';
    }
}

async function startUpload() {
    console.log("[TRACE ENTER] startUpload");
    const status = document.getElementById('status');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');

    if (!convertedWavBlob) {
        status.innerHTML = `<span style="color: #ef4444;">❌ Выберите корректный аудиофайл!</span>`;
        console.warn("[TRACE EXIT] startUpload -> No blob to upload");
        return;
    }

    status.innerText = "🔑 Подготовка токена...";

    try {
        const headers = await getAuthHeaders();
        if (!headers['X-Auth-Nonce']) {
            throw new Error("Не удалось получить заголовки авторизации");
        }

        status.innerText = "⏳ Загрузка WAV файла на ESP32...";
        progressBar.style.display = "block";
        progressFill.style.width = "0%";

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload', true);
        xhr.setRequestHeader('X-Auth-Nonce', headers['X-Auth-Nonce']);
        xhr.setRequestHeader('X-Auth-Hash', headers['X-Auth-Hash']);
        xhr.setRequestHeader('X-File-Name', 'bell.wav');

        xhr.upload.onprogress = function(e) {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                progressFill.style.width = percent + "%";
                status.innerText = `⏳ Передача: ${percent}%`;
            }
        };

        xhr.onload = function() {
            if (xhr.status === 200) {
                status.innerHTML = `<span style="color: #10b981;">✅ ${xhr.responseText}</span>`;
                console.log("[TRACE EXIT] startUpload -> XHR Upload 200 OK");
                loadSystemInfo();
            } else {
                status.innerHTML = `<span style="color: #ef4444;">❌ ${xhr.responseText}</span>`;
                console.warn("[TRACE EXIT] startUpload -> XHR Upload Error", xhr.status);
                progressFill.style.width = "0%";
            }
        };

        xhr.onerror = function() {
            console.error("[TRACE EXIT] startUpload -> XHR Network error");
            status.innerHTML = `<span style="color: #ef4444;">❌ Сбой сети при передаче файла</span>`;
        };

        xhr.send(convertedWavBlob);

    } catch (err) {
        console.error("[TRACE EXIT] startUpload -> Exception", err);
        status.innerHTML = `<span style="color: #ef4444;">❌ Ошибка: ${err.message}</span>`;
    }
}