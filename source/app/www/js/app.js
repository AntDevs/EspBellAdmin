// ==========================================
// 3. ОСНОВНОЙ СКРИПТ ПРИЛОЖЕНИЯ
// ==========================================

let savedMaxFileBytes = 4194304;
let savedAvailableBytes = 0;
let savedAllowedExtensions = ['mp3', 'wav'];
let isEsp32Playing = false;

function updatePlayButtonUI(isPlaying) {
    console.log("[TRACE ENTER] updatePlayButtonUI", isPlaying);
    try {
        const btn = document.getElementById('togglePlayBtn');
        if (btn) {
            if (isPlaying) {
                btn.innerHTML = "⏹ Стоп";
                btn.style.backgroundColor = "#ef4444";
                btn.className = "btn-secondary";
                btn.style.marginTop = "0";
            } else {
                btn.innerHTML = "▶ Проиграть";
                btn.style.backgroundColor = "#10b981";
                btn.className = "";
                btn.style.marginTop = "0";
            }
        }
    } catch (err) {
        console.error("[TRACE EXIT] updatePlayButtonUI -> error", err);
    }
    console.log("[TRACE EXIT] updatePlayButtonUI");
}

async function toggleEsp32Audio() {
    console.log("[TRACE ENTER] toggleEsp32Audio", { isEsp32Playing });
    try {
        if (!isEsp32Playing) {
            await playOnEsp32();
        } else {
            await stopOnEsp32();
        }
    } catch (err) {
        console.error("[TRACE EXIT] toggleEsp32Audio -> error", err);
    }
    console.log("[TRACE EXIT] toggleEsp32Audio");
}

async function loadMainView(defaultTab = 'upload') {
    console.log("[TRACE ENTER] loadMainView", defaultTab);
    const container = document.getElementById('app-container');
    try {
        const response = await fetch('/www/main.html');
        if (!response.ok) {
            throw new Error(`Не удалось загрузить /www/main.html (Код: ${response.status})`);
        }
        container.innerHTML = await response.text();
        console.log("[TRACE EXIT] loadMainView -> main layout loaded");
        await switchTab(defaultTab);
    } catch (err) {
        console.error("[TRACE EXIT] loadMainView -> error", err);
        container.innerHTML = `
            <div class="card">
                <div class="icon-header">⚠️</div>
                <h2>Ошибка загрузки контейнера</h2>
                <p style="color: #ef4444; text-align: center; font-size: 14px; word-break: break-word;">${err.message}</p>
                <button onclick="loadMainView('${defaultTab}')">Повторить</button>
            </div>`;
    }
}

async function switchTab(tabName) {
    console.log("[TRACE ENTER] switchTab", tabName);
    const tabContent = document.getElementById('tab-content');
    const tabBtnAudio = document.getElementById('tabBtnAudio');
    const tabBtnConfig = document.getElementById('tabBtnConfig');

    if (!tabContent) {
        console.warn("[TRACE EXIT] switchTab -> tab-content container not found, loading main view");
        await loadMainView(tabName);
        return;
    }

    if (tabBtnAudio && tabBtnConfig) {
        if (tabName === 'upload') {
            tabBtnAudio.classList.add('active');
            tabBtnConfig.classList.remove('active');
        } else if (tabName === 'config') {
            tabBtnConfig.classList.add('active');
            tabBtnAudio.classList.remove('active');
        }
    }

    const fileName = tabName + '.html';
    try {
        const response = await fetch('/www/' + fileName);
        if (!response.ok) {
            throw new Error(`Не удалось загрузить /www/${fileName} (Код: ${response.status})`);
        }
        tabContent.innerHTML = await response.text();

        if (tabName === 'upload') {
            loadSystemInfo();
        } else if (tabName === 'config') {
            loadConfigData();
        }
        console.log("[TRACE EXIT] switchTab -> success", tabName);
    } catch (err) {
        console.error("[TRACE EXIT] switchTab -> error", err);
        tabContent.innerHTML = `
            <div style="padding: 20px; text-align: center;">
                <p style="color: #ef4444; font-size: 14px;">${err.message}</p>
                <button onclick="switchTab('${tabName}')">Повторить</button>
            </div>`;
    }
}

async function loadView(viewName) {
    console.log("[TRACE ENTER] loadView", viewName);
    if (viewName !== 'login.html') {
        const tabName = viewName.replace('.html', '');
        await loadMainView(tabName);
        console.log("[TRACE EXIT] loadView -> redirected to loadMainView", tabName);
        return;
    }
    const container = document.getElementById('app-container');
    try {
        const response = await fetch('/www/' + viewName);
        if (!response.ok) {
            throw new Error(`Не удалось загрузить /www/${viewName} (Код: ${response.status})`);
        }
        container.innerHTML = await response.text();
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
        setSavedPassword(pwdInput);
        const headers = await getAuthHeaders();

        const verifyResp = await fetch('/api/verify-auth', {
            method: 'POST',
            headers: headers
        });

        if (verifyResp.ok) {
            console.log("[TRACE EXIT] handleLogin -> Auth successful");
            loadMainView('upload');
        } else {
            clearSavedPassword();
            const errData = await verifyResp.json();
            console.log("[TRACE EXIT] handleLogin -> Auth failed", errData);
            loginStatus.innerHTML = `<span style="color: #ef4444;">❌ ${errData.error || 'Неверный пароль'}</span>`;
        }
    } catch (err) {
        clearSavedPassword();
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

        isEsp32Playing = !!data.isPlaying;
        updatePlayButtonUI(isEsp32Playing);

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
        const headers = await getAuthHeaders();

        const res = await fetch('/api/config', { headers });

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
            document.getElementById('cfg_upload_password').value = getSavedPassword();
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

        const headers = await getAuthHeaders();
        headers['Content-Type'] = 'application/json';

        const res = await fetch('/api/config', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            setSavedPassword(newUploadPwd);
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

async function playOnEsp32() {
    console.log("[TRACE ENTER] playOnEsp32");
    const status = document.getElementById('status');
    status.innerText = "🔑 Подготовка авторизации...";

    try {
        const headers = await getAuthHeaders();

        const resp = await fetch('/api/play', {
            method: 'POST',
            headers: headers
        });

        const result = await resp.json();
        if (resp.ok) {
            status.innerHTML = `<span style="color: #10b981;">▶ Воспроизведение заведено на ESP32</span>`;
            isEsp32Playing = true;
            updatePlayButtonUI(true);
            console.log("[TRACE EXIT] playOnEsp32 -> Playing started");
        } else {
            status.innerHTML = `<span style="color: #ef4444;">❌ ${result.error || 'Ошибка воспроизведения'}</span>`;
            isEsp32Playing = false;
            updatePlayButtonUI(false);
            console.warn("[TRACE EXIT] playOnEsp32 -> Server rejected play request", result);
        }
    } catch (err) {
        console.error("[TRACE EXIT] playOnEsp32 -> Exception", err);
        status.innerHTML = `<span style="color: #ef4444;">❌ Сбой соединения с ESP32</span>`;
        isEsp32Playing = false;
        updatePlayButtonUI(false);
    }
}

async function stopOnEsp32() {
    console.log("[TRACE ENTER] stopOnEsp32");
    const status = document.getElementById('status');
    try {
        const headers = await getAuthHeaders();

        const resp = await fetch('/api/stop', {
            method: 'POST',
            headers: headers
        });

        if (resp.ok) {
            status.innerHTML = `<span style="color: #475569;">⏹ Воспроизведение остановлено</span>`;
            console.log("[TRACE EXIT] stopOnEsp32 -> Playback stopped");
        }
    } catch (err) {
        console.error("[TRACE EXIT] stopOnEsp32 -> Exception", err);
        status.innerHTML = `<span style="color: #ef4444;">❌ Сбой соединения с ESP32</span>`;
    } finally {
        isEsp32Playing = false;
        updatePlayButtonUI(false);
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

    clearSavedPassword();
    clearAudioState();
    isEsp32Playing = false;
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