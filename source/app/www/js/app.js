let savedPassword = "";
let savedMaxFileBytes = 4194304;
let savedAvailableBytes = 0;
let savedAllowedExtensions = ['mp3', 'wav'];
let currentAudioUrl = null;
let convertedWavBlob = null;

async function sha256Async(message) {
    console.log("[TRACE ENTER] sha256Async", message ? "(length: " + message.length + ")" : "");
    try {
        let result = "";
        if (window.crypto && crypto.subtle && crypto.subtle.digest) {
            const msgBuffer = new TextEncoder().encode(message);
            const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
            const hashArray = Array.from(new Uint8Array(hashBuffer));
            result = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
            console.log("[TRACE EXIT] sha256Async -> SubtleCrypto success");
            return result;
        }
        
        const K = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
        ];
        let H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
        
        const bytes = new TextEncoder().encode(message);
        const len = bytes.length * 8;
        const blocks = [];
        for (let i = 0; i < bytes.length; i++) {
            blocks[i >> 2] |= bytes[i] << (24 - (i % 4) * 8);
        }
        blocks[bytes.length >> 2] |= 0x80 << (24 - (bytes.length % 4) * 8);
        blocks[(((bytes.length + 8) >> 6) + 1) * 16 - 1] = len;

        for (let i = 0; i < blocks.length; i += 16) {
            const w = new Array(64);
            for (let t = 0; t < 16; t++) w[t] = blocks[i + t] | 0;
            for (let t = 16; t < 64; t++) {
                const s0 = ((w[t-15] >>> 7) | (w[t-15] << 25)) ^ ((w[t-15] >>> 18) | (w[t-15] << 14)) ^ (w[t-15] >>> 3);
                const s1 = ((w[t-2] >>> 17) | (w[t-2] << 15)) ^ ((w[t-2] >>> 19) | (w[t-2] << 13)) ^ (w[t-2] >>> 10);
                w[t] = (w[t-16] + s0 + w[t-7] + s1) | 0;
            }
            let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
            for (let t = 0; t < 64; t++) {
                const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
                const ch = (e & f) ^ ((~e) & g);
                const temp1 = (h + S1 + ch + K[t] + w[t]) | 0;
                const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
                const maj = (a & b) ^ (a & c) ^ (b & c);
                const temp2 = (S0 + maj) | 0;

                h = g; g = f; f = e; e = (d + temp1) | 0;
                d = c; c = b; b = a; a = (temp1 + temp2) | 0;
            }
            H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
            H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
        }
        result = H.map(n => (n >>> 0).toString(16).padStart(8, '0')).join('');
        console.log("[TRACE EXIT] sha256Async -> JS Fallback success");
        return result;
    } catch (err) {
        console.error("[TRACE EXIT] sha256Async -> error", err);
        return "";
    }
}

function togglePassword() {
    console.log("[TRACE ENTER] togglePassword");
    try {
        const pwdInput = document.getElementById('pwdInput');
        const check = document.getElementById('showPwdCheck');
        if (pwdInput && check) {
            pwdInput.type = check.checked ? 'text' : 'password';
        }
    } catch (err) {
        console.error("[TRACE EXIT] togglePassword -> error", err);
    }
    console.log("[TRACE EXIT] togglePassword");
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

async function loadView(viewName) {
    console.log("[TRACE ENTER] loadView", viewName);
    const container = document.getElementById('app-container');
    try {
        const response = await fetch('/www/' + viewName);
        if (!response.ok) {
            throw new Error(`Не удалось загрузить /www/${viewName} (Код: ${response.status})`);
        }
        container.innerHTML = await response.text();

        if (viewName === 'upload.html') {
            loadSystemInfo();
        } else if (viewName === 'config.html') {
            loadConfigData();
        }
        console.log("[TRACE EXIT] loadView -> success", viewName);
    } catch (err) {
        console.error("[TRACE EXIT] loadView -> error", err);
        container.innerHTML = `
            <div class="card">
                <div class="icon-header">⚠️</div>
                <h2>Ошибка загрузки экрана</h2>
                <p style="color: #ef4444; text-align: center; font-size: 14px; word-break: break-word;">${err.message}</p>
                <button onclick="loadView('${viewName}')">Повторить</button>
            </div>`;
    }
}

async function handleLogin(e) {
    console.log("[TRACE ENTER] handleLogin");
    e.preventDefault();
    const pwdInput = document.getElementById('pwdInput').value;
    const loginStatus = document.getElementById('loginStatus');

    loginStatus.innerText = "⏳ Проверка пароля...";

    try {
        const nonceResp = await fetch('/api/get-nonce');
        const nonceData = await nonceResp.json();
        const nonce = nonceData.nonce;

        const authHash = await sha256Async(pwdInput + nonce);

        const verifyResp = await fetch('/api/verify-auth', {
            method: 'POST',
            headers: {
                'X-Auth-Nonce': nonce,
                'X-Auth-Hash': authHash
            }
        });

        if (verifyResp.ok) {
            savedPassword = pwdInput;
            console.log("[TRACE EXIT] handleLogin -> Auth successful");
            loadView('upload.html');
        } else {
            const errData = await verifyResp.json();
            console.log("[TRACE EXIT] handleLogin -> Auth failed", errData);
            loginStatus.innerHTML = `<span style="color: #ef4444;">❌ ${errData.error || 'Неверный пароль'}</span>`;
        }
    } catch (err) {
        console.error("[TRACE EXIT] handleLogin -> Network error", err);
        loginStatus.innerHTML = `<span style="color: #ef4444;">❌ Ошибка соединения</span>`;
    }
}

async function loadSystemInfo() {
    console.log("[TRACE ENTER] loadSystemInfo");
    const diskInfo = document.getElementById('diskInfo');
    if (!diskInfo) {
        console.log("[TRACE EXIT] loadSystemInfo (no diskInfo element)");
        return;
    }
    try {
        const res = await fetch('/api/info');
        const data = await res.json();
        savedAvailableBytes = data.availableBytes || 0;
        savedMaxFileBytes = data.maxFileBytes || 4194304;
        savedAllowedExtensions = data.allowedExtensions || ['mp3', 'wav'];

        const freeMB = (savedAvailableBytes / (1024 * 1024)).toFixed(2);
        const maxMB = (savedMaxFileBytes / (1024 * 1024)).toFixed(2);
        diskInfo.innerText = `💾 Доступно на диске: ${freeMB} МБ (лимит конвертации: ${maxMB} МБ)`;
        
        const fileInput = document.getElementById('fileInput');
        if (fileInput && savedAllowedExtensions.length) {
            fileInput.accept = savedAllowedExtensions.map(e => '.' + e.toLowerCase().replace(/^\./, '')).join(',');
        }
        console.log("[TRACE EXIT] loadSystemInfo -> Loaded info", data);
    } catch (e) {
        console.error("[TRACE EXIT] loadSystemInfo -> Exception", e);
        diskInfo.innerText = "💾 Память ESP32 готова к загрузке";
    }
}

async function loadConfigData() {
    console.log("[TRACE ENTER] loadConfigData");
    const status = document.getElementById('configStatus');
    if (status) status.innerText = "⏳ Загрузка настроек...";

    try {
        const nonceResp = await fetch('/api/get-nonce');
        const nonceData = await nonceResp.json();
        const nonce = nonceData.nonce;
        const authHash = await sha256Async(savedPassword + nonce);

        const res = await fetch('/api/config', {
            headers: {
                'X-Auth-Nonce': nonce,
                'X-Auth-Hash': authHash
            }
        });

        if (res.ok) {
            const cfg = await res.json();
            console.log("[TRACE LOAD CONFIG DATA]", cfg);
            document.getElementById('cfg_boot_mode').value = cfg.boot_mode || 'music_first';
            document.getElementById('cfg_repeat_count').value = cfg.repeat_count || 1;
            document.getElementById('cfg_max_duration').value = cfg.max_play_duration_sec || 0;
            document.getElementById('cfg_fade_out').value = cfg.fade_out_ms || 1000;
            document.getElementById('cfg_smart_timeout').value = cfg.smart_timeout_sec || 7;
            document.getElementById('cfg_auth_smart_timeout').value = cfg.auth_smart_timeout_sec || 600;
            document.getElementById('cfg_last_pos_sec').value = cfg.last_play_pos_sec !== undefined ? cfg.last_play_pos_sec : 0;
            document.getElementById('cfg_resume_playback').checked = !!cfg.resume_playback;
            document.getElementById('cfg_wifi_ssid').value = cfg.wifi_ssid || '';
            document.getElementById('cfg_upload_password').value = savedPassword;
            if (status) status.innerText = "";
            console.log("[TRACE EXIT] loadConfigData -> Success");
        } else {
            console.warn("[TRACE EXIT] loadConfigData -> Response not OK");
            if (status) status.innerHTML = `<span style="color: #ef4444;">❌ Ошибка загрузки настроек</span>`;
        }
    } catch (e) {
        console.error("[TRACE EXIT] loadConfigData -> Error", e);
        if (status) status.innerHTML = `<span style="color: #ef4444;">❌ Сбой связи с ESP32</span>`;
    }
}

async function saveConfig(e) {
    console.log("[TRACE ENTER] saveConfig");
    e.preventDefault();
    const status = document.getElementById('configStatus');
    status.innerText = "🔑 Авторизация и запись...";

    try {
        const newUploadPwd = document.getElementById('cfg_upload_password').value;

        const payload = {
            boot_mode: document.getElementById('cfg_boot_mode').value,
            repeat_count: parseInt(document.getElementById('cfg_repeat_count').value),
            max_play_duration_sec: parseInt(document.getElementById('cfg_max_duration').value),
            fade_out_ms: parseInt(document.getElementById('cfg_fade_out').value),
            smart_timeout_sec: parseInt(document.getElementById('cfg_smart_timeout').value),
            auth_smart_timeout_sec: parseInt(document.getElementById('cfg_auth_smart_timeout').value),
            last_play_pos_sec: parseFloat(document.getElementById('cfg_last_pos_sec').value) || 0,
            resume_playback: document.getElementById('cfg_resume_playback').checked,
            wifi_ssid: document.getElementById('cfg_wifi_ssid').value,
            upload_password: newUploadPwd
        };

        const newWifiPwd = document.getElementById('cfg_wifi_password').value;
        if (newWifiPwd) {
            payload.wifi_password = newWifiPwd;
        }

        console.log("[TRACE SAVE CONFIG PAYLOAD]", payload);

        const nonceResp = await fetch('/api/get-nonce');
        const nonceData = await nonceResp.json();
        const nonce = nonceData.nonce;
        const authHash = await sha256Async(savedPassword + nonce);

        const res = await fetch('/api/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Auth-Nonce': nonce,
                'X-Auth-Hash': authHash
            },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            savedPassword = newUploadPwd;
            status.innerHTML = `<span style="color: #10b981;">✅ Настройки сохранены в config.json!</span>`;
            console.log("[TRACE EXIT] saveConfig -> Saved successfully");
        } else {
            const err = await res.json();
            status.innerHTML = `<span style="color: #ef4444;">❌ ${err.error || 'Ошибка записи'}</span>`;
            console.warn("[TRACE EXIT] saveConfig -> Failed", err);
        }
    } catch (err) {
        console.error("[TRACE EXIT] saveConfig -> Exception", err);
        status.innerHTML = `<span style="color: #ef4444;">❌ Ошибка сети при сохранении</span>`;
    }
}

async function handleFileSelect(event) {
    console.log("[TRACE ENTER] handleFileSelect", event.target.files[0] ? event.target.files[0].name : "No file");
    const file = event.target.files[0];
    const previewContainer = document.getElementById('audioPreviewContainer');
    const audioPreview = document.getElementById('audioPreview');
    const status = document.getElementById('status');
    const previewLabel = document.getElementById('previewLabel');

    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
        currentAudioUrl = null;
    }
    convertedWavBlob = null;

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
        const nonceResp = await fetch('/api/get-nonce');
        const nonceData = await nonceResp.json();
        const nonce = nonceData.nonce;

        const authHash = await sha256Async(savedPassword + nonce);

        status.innerText = "⏳ Загрузка WAV файла на ESP32...";
        progressBar.style.display = "block";
        progressFill.style.width = "0%";

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload', true);
        xhr.setRequestHeader('X-Auth-Nonce', nonce);
        xhr.setRequestHeader('X-Auth-Hash', authHash);
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

async function playOnEsp32() {
    console.log("[TRACE ENTER] playOnEsp32");
    const status = document.getElementById('status');
    status.innerText = "🔑 Подготовка авторизации...";

    try {
        const nonceResp = await fetch('/api/get-nonce');
        const nonceData = await nonceResp.json();
        const nonce = nonceData.nonce;

        const authHash = await sha256Async(savedPassword + nonce);

        const resp = await fetch('/api/play', {
            method: 'POST',
            headers: {
                'X-Auth-Nonce': nonce,
                'X-Auth-Hash': authHash
            }
        });

        const result = await resp.json();
        if (resp.ok) {
            status.innerHTML = `<span style="color: #10b981;">▶ Воспроизведение заведено на ESP32</span>`;
            console.log("[TRACE EXIT] playOnEsp32 -> Playing started");
        } else {
            status.innerHTML = `<span style="color: #ef4444;">❌ ${result.error || 'Ошибка воспроизведения'}</span>`;
            console.warn("[TRACE EXIT] playOnEsp32 -> Server rejected play request", result);
        }
    } catch (err) {
        console.error("[TRACE EXIT] playOnEsp32 -> Exception", err);
        status.innerHTML = `<span style="color: #ef4444;">❌ Сбой соединения с ESP32</span>`;
    }
}

async function stopOnEsp32() {
    console.log("[TRACE ENTER] stopOnEsp32");
    const status = document.getElementById('status');
    try {
        const nonceResp = await fetch('/api/get-nonce');
        const nonceData = await nonceResp.json();
        const nonce = nonceData.nonce;

        const authHash = await sha256Async(savedPassword + nonce);

        const resp = await fetch('/api/stop', {
            method: 'POST',
            headers: {
                'X-Auth-Nonce': nonce,
                'X-Auth-Hash': authHash
            }
        });

        if (resp.ok) {
            status.innerHTML = `<span style="color: #475569;">⏹ Воспроизведение остановлено</span>`;
            console.log("[TRACE EXIT] stopOnEsp32 -> Playback stopped");
        }
    } catch (err) {
        console.error("[TRACE EXIT] stopOnEsp32 -> Exception", err);
        status.innerHTML = `<span style="color: #ef4444;">❌ Сбой соединения с ESP32</span>`;
    }
}

async function logout() {
    console.log("[TRACE ENTER] logout");
    try {
        await fetch('/api/logout', { method: 'POST' });
        console.log("[TRACE EXIT] logout -> Reset server timeout success");
    } catch (err) {
        console.error("[TRACE EXIT] logout -> Error notifying server", err);
    }

    savedPassword = "";
    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
        currentAudioUrl = null;
    }
    convertedWavBlob = null;
    console.log("[TRACE EXIT] logout");
    loadView('login.html');
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        console.log("[TRACE ENTER] DOMContentLoaded event listener");
        loadView('login.html');
        console.log("[TRACE EXIT] DOMContentLoaded event listener");
    });
} else {
    console.log("[TRACE ENTER] Direct script load initial view");
    loadView('login.html');
    console.log("[TRACE EXIT] Direct script load initial view");
}