let savedPassword = "";
let savedMaxFileBytes = 0;
let savedAvailableBytes = 0;
let savedAllowedExtensions = ['mp3'];
let currentAudioUrl = null;

// Чистый SHA-256 (Web Crypto + алгоритмический фолбэк)
async function sha256Async(message) {
    if (window.crypto && crypto.subtle && crypto.subtle.digest) {
        const msgBuffer = new TextEncoder().encode(message);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
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
    return H.map(n => (n >>> 0).toString(16).padStart(8, '0')).join('');
}

function togglePassword() {
    const pwdInput = document.getElementById('pwdInput');
    const check = document.getElementById('showPwdCheck');
    if (pwdInput && check) {
        pwdInput.type = check.checked ? 'text' : 'password';
    }
}

async function loadView(viewName) {
    const container = document.getElementById('app-container');
    try {
        const response = await fetch('/www/' + viewName);
        if (!response.ok) {
            throw new Error(`Не удалось загрузить /www/${viewName} (Код: ${response.status})`);
        }
        container.innerHTML = await response.text();

        if (viewName === 'upload.html') {
            loadSystemInfo();
        }
    } catch (err) {
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
            loadView('upload.html');
        } else {
            const errData = await verifyResp.json();
            loginStatus.innerHTML = `<span style="color: #ef4444;">❌ ${errData.error || 'Неверный пароль'}</span>`;
        }
    } catch (err) {
        loginStatus.innerHTML = `<span style="color: #ef4444;">❌ Ошибка соединения</span>`;
    }
}

async function loadSystemInfo() {
    const diskInfo = document.getElementById('diskInfo');
    if (!diskInfo) return;
    try {
        const res = await fetch('/api/info');
        const data = await res.json();
        savedAvailableBytes = data.availableBytes || 0;
        savedMaxFileBytes = data.maxFileBytes || 0;
        savedAllowedExtensions = data.allowedExtensions || ['mp3'];

        const freeMB = (savedAvailableBytes / (1024 * 1024)).toFixed(2);
        const maxMB = (savedMaxFileBytes / (1024 * 1024)).toFixed(2);
        diskInfo.innerText = `💾 Доступно на диске: ${freeMB} МБ (макс. файл: ${maxMB} МБ)`;
        
        const fileInput = document.getElementById('fileInput');
        if (fileInput && savedAllowedExtensions.length) {
            fileInput.accept = savedAllowedExtensions.map(e => '.' + e.toLowerCase().replace(/^\./, '')).join(',');
        }
    } catch (e) {
        diskInfo.innerText = "💾 Память ESP32 готова к загрузке";
    }
}

// Вызывается при каждом выборе/смене файла
function handleFileSelect(event) {
    const file = event.target.files[0];
    const previewContainer = document.getElementById('audioPreviewContainer');
    const audioPreview = document.getElementById('audioPreview');
    const status = document.getElementById('status');

    // Освобождаем предыдущую ссылку из памяти
    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
        currentAudioUrl = null;
    }

    if (!file) {
        if (previewContainer) previewContainer.style.display = 'none';
        return;
    }

    // Проверка формата
    const fileExt = file.name.split('.').pop().toLowerCase();
    const allowed = savedAllowedExtensions.map(e => e.toLowerCase().replace(/^\./, ''));
    if (!allowed.includes(fileExt)) {
        if (previewContainer) previewContainer.style.display = 'none';
        status.innerHTML = `<span style="color: #ef4444;">❌ Недопустимый тип файла! Разрешены: .${allowed.join(', .')}</span>`;
        return;
    }

    // Проверка размера
    if (savedMaxFileBytes > 0 && file.size > savedMaxFileBytes) {
        if (previewContainer) previewContainer.style.display = 'none';
        const fileMB = (file.size / (1024 * 1024)).toFixed(2);
        const limitMB = (savedMaxFileBytes / (1024 * 1024)).toFixed(2);
        status.innerHTML = `<span style="color: #ef4444;">❌ Файл (${fileMB} МБ) превышает лимит сервера (${limitMB} МБ)!</span>`;
        return;
    }

    status.innerHTML = "";
    
    // Создаем локальный URL из оперативной памяти ПК/телефона
    currentAudioUrl = URL.createObjectURL(file);
    if (audioPreview && previewContainer) {
        audioPreview.src = currentAudioUrl;
        previewContainer.style.display = 'block';
    }
}

async function startUpload() {
    const fileInput = document.getElementById('fileInput');
    const status = document.getElementById('status');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');

    if (!fileInput.files.length) {
        status.innerHTML = `<span style="color: #ef4444;">❌ Выберите файл!</span>`;
        return;
    }

    const file = fileInput.files[0];

    const fileExt = file.name.split('.').pop().toLowerCase();
    const allowed = savedAllowedExtensions.map(e => e.toLowerCase().replace(/^\./, ''));
    if (!allowed.includes(fileExt)) {
        status.innerHTML = `<span style="color: #ef4444;">❌ Недопустимый тип файла! Разрешены: .${allowed.join(', .')}</span>`;
        return;
    }

    if (savedMaxFileBytes > 0 && file.size > savedMaxFileBytes) {
        const fileMB = (file.size / (1024 * 1024)).toFixed(2);
        const limitMB = (savedMaxFileBytes / (1024 * 1024)).toFixed(2);
        status.innerHTML = `<span style="color: #ef4444;">❌ Файл (${fileMB} МБ) превышает лимит сервера (${limitMB} МБ)!</span>`;
        return;
    }

    if (savedAvailableBytes > 0 && file.size > savedAvailableBytes) {
        const fileMB = (file.size / (1024 * 1024)).toFixed(2);
        const freeMB = (savedAvailableBytes / (1024 * 1024)).toFixed(2);
        status.innerHTML = `<span style="color: #ef4444;">❌ Файл (${fileMB} МБ) больше свободного места на диске (${freeMB} МБ)!</span>`;
        return;
    }

    status.innerText = "🔑 Подготовка токена...";

    try {
        const nonceResp = await fetch('/api/get-nonce');
        const nonceData = await nonceResp.json();
        const nonce = nonceData.nonce;

        const authHash = await sha256Async(savedPassword + nonce);

        status.innerText = "⏳ Загрузка файла...";
        progressBar.style.display = "block";
        progressFill.style.width = "0%";

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload', true);
        xhr.setRequestHeader('X-Auth-Nonce', nonce);
        xhr.setRequestHeader('X-Auth-Hash', authHash);
        xhr.setRequestHeader('X-File-Name', encodeURIComponent(file.name));

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
                loadSystemInfo();
            } else {
                status.innerHTML = `<span style="color: #ef4444;">❌ ${xhr.responseText}</span>`;
                progressFill.style.width = "0%";
            }
        };

        xhr.onerror = function() {
            status.innerHTML = `<span style="color: #ef4444;">❌ Сбой сети или файл не подходит по условиям</span>`;
        };

        xhr.send(file);

    } catch (err) {
        status.innerHTML = `<span style="color: #ef4444;">❌ Ошибка: ${err.message}</span>`;
    }
}

function logout() {
    savedPassword = "";
    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
        currentAudioUrl = null;
    }
    loadView('login.html');
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => loadView('login.html'));
} else {
    loadView('login.html');
}