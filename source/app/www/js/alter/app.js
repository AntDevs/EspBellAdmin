document.addEventListener('DOMContentLoaded', () => {
    const pwd = initAuthSession();
    if (pwd) {
        loadView('main');
    } else {
        loadView('login');
    }
});

// Роутинг HTML шаблонов
async function loadView(viewName) {
    const container = document.getElementById('app-container');
    try {
        const res = await fetch(`/www/${viewName}.html`);
        if (!res.ok) throw new Error('Failed to load view');
        container.innerHTML = await res.text();
        
        if (viewName === 'main') {
            switchTab('upload');
        }
    } catch (e) {
        container.innerHTML = `<div class="card" style="color:red">Ошибка загрузки интерфейса: ${e.message}</div>`;
    }
}

// Управление вкладками
async function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    if(tabName === 'upload') document.getElementById('tabBtnAudio').classList.add('active');
    if(tabName === 'config') document.getElementById('tabBtnConfig').classList.add('active');

    const content = document.getElementById('tab-content');
    const res = await fetch(`/www/${tabName}.html`);
    content.innerHTML = await res.text();

    if (tabName === 'upload') initUploadView();
    if (tabName === 'config') initConfigView();
}

// Логика вкладки "Аудио"
let selectedFile = null;
let isEspPlaying = false;

async function initUploadView() {
    try {
        const res = await fetch('/api/info');
        if (res.ok) {
            const info = await res.json();
            document.getElementById('diskInfo').innerText = 
                `Свободно на ESP32: ${(info.availableBytes / 1024 / 1024).toFixed(2)} МБ (Макс. файл: ${(info.maxFileBytes / 1024 / 1024).toFixed(2)} МБ)`;
            isEspPlaying = info.isPlaying;
            updatePlayBtn();
        }
    } catch (e) {}
}

function handleFileSelect(e) {
    selectedFile = e.target.files[0];
    const audioPreview = document.getElementById('audioPreview');
    const container = document.getElementById('audioPreviewContainer');
    if (selectedFile) {
        audioPreview.src = URL.createObjectURL(selectedFile);
        container.style.display = 'block';
    } else {
        container.style.display = 'none';
        audioPreview.src = "";
    }
}

function updatePlayBtn() {
    const btn = document.getElementById('togglePlayBtn');
    if(btn) {
        btn.innerText = isEspPlaying ? '⏹ Остановить на ESP32' : '▶ Проверить на ESP32';
        btn.style.backgroundColor = isEspPlaying ? '#ef4444' : '#10b981';
    }
}

async function toggleEsp32Audio() {
    const endpoint = isEspPlaying ? '/api/stop' : '/api/play';
    const headers = await getAuthHeaders();
    const res = await fetch(endpoint, { method: 'POST', headers });
    if (res.ok) {
        isEspPlaying = !isEspPlaying;
        updatePlayBtn();
    } else {
        alert("Ошибка воспроизведения. Возможно неверный пароль или файла нет на устройстве.");
    }
}

async function startUpload() {
    if (!selectedFile) {
        alert('Пожалуйста, выберите аудиофайл.');
        return;
    }

    const status = document.getElementById('status');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');

    status.innerText = "Подготовка файла...";
    status.style.color = "#334155";
    progressBar.style.display = "block";
    progressFill.style.width = "10%";
    progressFill.style.backgroundColor = "#10b981";

    try {
        // Кодирование и оптимизация аудио с помощью audio.js
        const blob = await processAudioToWav(selectedFile, (msg, pct) => {
            status.innerText = msg;
            progressFill.style.width = `${pct}%`;
        });

        // Отправка на ESP32
        status.innerText = "Отправка на ESP32...";
        progressFill.style.width = "85%";
        
        const headers = await getAuthHeaders();
        let newFileName = selectedFile.name;
        if (!newFileName.toLowerCase().endsWith('.wav')) {
            newFileName = newFileName.substring(0, newFileName.lastIndexOf('.')) + '.wav';
        }
        
        headers['X-File-Name'] = newFileName;
        headers['Content-Length'] = blob.size;

        const uploadRes = await fetch('/upload', {
            method: 'POST',
            headers: headers,
            body: blob
        });

        if (uploadRes.ok) {
            progressFill.style.width = "100%";
            status.innerText = await uploadRes.text();
            status.style.color = "#10b981";
            initUploadView();
        } else {
            throw new Error(await uploadRes.text());
        }
    } catch (err) {
        progressFill.style.backgroundColor = "#ef4444";
        status.innerText = "Ошибка: " + err.message;
        status.style.color = "#ef4444";
    }
}

// Логика вкладки "Настройки"
async function initConfigView() {
    const headers = await getAuthHeaders();
    const res = await fetch('/api/config', { headers });
    if (res.ok) {
        const cfg = await res.json();
        document.getElementById('cfg_boot_mode').value = cfg.boot_mode;
        document.getElementById('cfg_repeat_count').value = cfg.repeat_count;
        document.getElementById('cfg_max_duration').value = cfg.max_play_duration_sec;
        document.getElementById('cfg_fade_out').value = cfg.fade_out_ms;
        document.getElementById('cfg_smart_timeout').value = cfg.smart_timeout_sec;
        document.getElementById('cfg_auth_smart_timeout').value = cfg.auth_smart_timeout_sec;
        document.getElementById('cfg_last_pos_sec').value = cfg.last_play_pos_sec;
        document.getElementById('cfg_resume_playback').checked = cfg.resume_playback;
        document.getElementById('cfg_wifi_ssid').value = cfg.wifi_ssid || '';
        document.getElementById('cfg_upload_password').value = cfg.upload_password || '';
    }
}

async function saveConfig(e) {
    e.preventDefault();
    const payload = {
        boot_mode: document.getElementById('cfg_boot_mode').value,
        repeat_count: parseInt(document.getElementById('cfg_repeat_count').value),
        max_play_duration_sec: parseInt(document.getElementById('cfg_max_duration').value),
        fade_out_ms: parseInt(document.getElementById('cfg_fade_out').value),
        smart_timeout_sec: parseInt(document.getElementById('cfg_smart_timeout').value),
        auth_smart_timeout_sec: parseInt(document.getElementById('cfg_auth_smart_timeout').value),
        last_play_pos_sec: parseFloat(document.getElementById('cfg_last_pos_sec').value),
        resume_playback: document.getElementById('cfg_resume_playback').checked,
        wifi_ssid: document.getElementById('cfg_wifi_ssid').value,
        upload_password: document.getElementById('cfg_upload_password').value
    };
    
    const wp = document.getElementById('cfg_wifi_password').value;
    if (wp) payload.wifi_password = wp;

    const headers = await getAuthHeaders();
    headers['Content-Type'] = 'application/json';

    const res = await fetch('/api/config', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(payload)
    });

    const status = document.getElementById('configStatus');
    if (res.ok) {
        status.innerText = "Настройки системы сохранены!";
        status.style.color = "#10b981";
        
        setCurrentPassword(payload.upload_password);
        document.getElementById('cfg_wifi_password').value = '';
    } else {
        const err = await res.json();
        status.innerText = "Ошибка: " + (err.error || "Неизвестная ошибка сервера");
        status.style.color = "#ef4444";
    }
}