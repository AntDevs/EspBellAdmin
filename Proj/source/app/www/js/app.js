// ==========================================
// 3. ОСНОВНОЙ СКРИПТ ПРИЛОЖЕНИЯ
// ==========================================

let savedMaxFileBytes = 4194304;
let savedAvailableBytes = 0;
let savedAllowedExtensions = ['mp3', 'wav'];
let isEsp32Playing = false;

// ==========================================
// ОБЩИЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (устраняют дублирование кода)
// ==========================================

// Цветовая палитра статусных сообщений — вынесена в одно место,
// чтобы не повторять одни и те же HEX-коды в каждой функции.
const STATUS_COLORS = {
    success: '#10b981',
    error: '#ef4444',
    neutral: '#475569'
};

/**
 * Единая точка вывода статусных сообщений в UI.
 * Раньше в каждой функции повторялась одна и та же конструкция
 * `el.innerHTML = '<span style="color: ...">...</span>'`.
 * Поведение и внешний вид сообщений остаются прежними.
 * @param {HTMLElement|string} elementOrId - элемент или его id
 * @param {string} message - текст (может содержать эмодзи), без HTML-инъекций извне
 * @param {'success'|'error'|'neutral'|null} type - тип оформления, либо null для обычного текста без цвета
 */
function setStatusMessage(elementOrId, message, type = null) {
    const el = typeof elementOrId === 'string' ? document.getElementById(elementOrId) : elementOrId;
    if (!el) return;
    if (type && STATUS_COLORS[type]) {
        el.innerHTML = `<span style="color: ${STATUS_COLORS[type]};">${message}</span>`;
    } else {
        el.innerText = message;
    }
}

/**
 * Обёртка над fetch(), которая автоматически добавляет заголовки авторизации
 * (X-Auth-Nonce / X-Auth-Hash), полученные через getAuthHeaders() из auth.js.
 * Устраняет повторение блока "получить заголовки -> передать их в fetch",
 * встречавшегося в playOnEsp32, stopOnEsp32, saveConfig и loadConfigData.
 * @param {string} url
 * @param {RequestInit} options - стандартные опции fetch (method, body и т.д.)
 */
async function fetchWithAuth(url, options = {}) {
    const authHeaders = await getAuthHeaders();
    return fetch(url, {
        ...options,
        headers: {
            ...authHeaders,
            ...(options.headers || {})
        }
    });
}

/**
 * Выводит статусное сообщение с анимированным спиннером — используется
 * вместо статичного эмодзи "⏳" на время ожидания ответа сервера или
 * длительной операции в браузере (декодирование аудио и т.п.).
 * @param {HTMLElement|string} elementOrId - элемент или его id
 * @param {string} message - текст, который будет показан рядом со спиннером
 */
function setStatusLoading(elementOrId, message) {
    const el = typeof elementOrId === 'string' ? document.getElementById(elementOrId) : elementOrId;
    if (!el) return;
    el.innerHTML = `<span class="spinner spinner-dark spinner-inline"></span>${message}`;
}

/**
 * Переключает кнопку в состояние ожидания ответа: блокирует повторные клики,
 * подставляет спиннер и (опционально) временную подпись. Исходное содержимое
 * кнопки сохраняется в data-атрибуте и восстанавливается при isLoading=false.
 * @param {HTMLElement|string} elementOrId - кнопка или её id
 * @param {boolean} isLoading - включить/выключить состояние загрузки
 * @param {string|null} loadingText - текст рядом со спиннером; если не задан, используется исходная подпись кнопки
 */
function setButtonLoading(elementOrId, isLoading, loadingText = null) {
    const btn = typeof elementOrId === 'string' ? document.getElementById(elementOrId) : elementOrId;
    if (!btn) return;
    if (isLoading) {
        if (btn.dataset.originalHtml === undefined) {
            btn.dataset.originalHtml = btn.innerHTML;
        }
        btn.disabled = true;
        btn.classList.add('is-loading');
        btn.innerHTML = `<span class="spinner"></span>${loadingText || btn.dataset.originalHtml}`;
    } else {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        if (btn.dataset.originalHtml !== undefined) {
            btn.innerHTML = btn.dataset.originalHtml;
            delete btn.dataset.originalHtml;
        }
    }
}

/**
 * Заменяет содержимое контейнера на индикатор загрузки блока —
 * используется при переключении вкладок и загрузке экранов,
 * пока HTML-фрагмент ещё не получен с сервера.
 * @param {HTMLElement} container
 * @param {string} message
 */
function showContainerLoading(container, message = 'Загрузка...') {
    if (!container) return;
    container.innerHTML = `
        <div class="loading-container">
            <span class="spinner spinner-dark"></span>
            <span>${message}</span>
        </div>`;
}

// Добавляем функцию рендера полей Wi-Fi
function addWifiNetworkField(ssid = '') {
    const container = document.getElementById('wifi_networks_container');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'wifi-row';
    row.style.display = 'flex';
    row.style.gap = '8px';
    row.innerHTML = `
        <input type="text" class="wifi-ssid" placeholder="Название сети (SSID)" value="${ssid}" style="flex: 2;" autocomplete="off">
        <input type="password" class="wifi-pass" placeholder="Пароль (оставьте пустым для старого)" style="flex: 2;" autocomplete="new-password">
        <button type="button" onclick="this.parentElement.remove()" style="background-color: #ef4444; width: 44px; padding: 0;">✖</button>
    `;
    container.appendChild(row);
}

function updatePlayButtonUI(isPlaying) {
    console.log("[TRACE ENTER] updatePlayButtonUI", isPlaying); //[cite: 13]
    try {
        const btn = document.getElementById('togglePlayBtn');
        if (btn) {
            // Кнопка могла быть переведена в состояние загрузки (спиннер) перед
            // запросом play/stop — здесь всегда возвращаем её в рабочее состояние,
            // одновременно устанавливая финальный вид (Стоп/Проиграть).
            btn.disabled = false;
            btn.classList.remove('is-loading');
            delete btn.dataset.originalHtml;
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
        console.error("[TRACE EXIT] updatePlayButtonUI -> error", err); //[cite: 13]
    }
    console.log("[TRACE EXIT] updatePlayButtonUI"); //[cite: 13]
}

async function toggleEsp32Audio() {
    console.log("[TRACE ENTER] toggleEsp32Audio", { isEsp32Playing }); //[cite: 13]
    try {
        if (!isEsp32Playing) {
            await playOnEsp32();
        } else {
            await stopOnEsp32();
        }
    } catch (err) {
        console.error("[TRACE EXIT] toggleEsp32Audio -> error", err); //[cite: 13]
    }
    console.log("[TRACE EXIT] toggleEsp32Audio"); //[cite: 13]
}

async function loadMainView(defaultTab = 'upload') {
    console.log("[TRACE ENTER] loadMainView", defaultTab); //[cite: 13]
    const container = document.getElementById('app-container');
    showContainerLoading(container, 'Загрузка интерфейса...');
    try {
        const response = await fetch('/www/main.html');
        if (!response.ok) {
            throw new Error(`Не удалось загрузить /www/main.html (Код: ${response.status})`);
        }
        container.innerHTML = await response.text();
        console.log("[TRACE EXIT] loadMainView -> main layout loaded"); //[cite: 13]
        await switchTab(defaultTab);
    } catch (err) {
        console.error("[TRACE EXIT] loadMainView -> error", err); //[cite: 13]
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
    console.log("[TRACE ENTER] switchTab", tabName); //[cite: 13]
    const tabContent = document.getElementById('tab-content');
    const tabBtnAudio = document.getElementById('tabBtnAudio');
    const tabBtnConfig = document.getElementById('tabBtnConfig');

    if (!tabContent) {
        console.warn("[TRACE EXIT] switchTab -> tab-content container not found, loading main view"); //[cite: 13]
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
    showContainerLoading(tabContent, 'Загрузка...');
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
        console.log("[TRACE EXIT] switchTab -> success", tabName); //[cite: 13]
    } catch (err) {
        console.error("[TRACE EXIT] switchTab -> error", err); //[cite: 13]
        tabContent.innerHTML = `
            <div style="padding: 20px; text-align: center;">
                <p style="color: #ef4444; font-size: 14px;">${err.message}</p>
                <button onclick="switchTab('${tabName}')">Повторить</button>
            </div>`;
    }
}

async function loadView(viewName) {
    console.log("[TRACE ENTER] loadView", viewName); //[cite: 13]
    if (viewName !== 'login.html') {
        const tabName = viewName.replace('.html', '');
        await loadMainView(tabName);
        console.log("[TRACE EXIT] loadView -> redirected to loadMainView", tabName); //[cite: 13]
        return;
    }
    const container = document.getElementById('app-container');
    showContainerLoading(container, 'Загрузка...');
    try {
        const response = await fetch('/www/' + viewName);
        if (!response.ok) {
            throw new Error(`Не удалось загрузить /www/${viewName} (Код: ${response.status})`);
        }
        container.innerHTML = await response.text();
        console.log("[TRACE EXIT] loadView -> success", viewName); //[cite: 13]
    } catch (err) {
        console.error("[TRACE EXIT] loadView -> error", err); //[cite: 13]
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
    console.log("[TRACE ENTER] handleLogin"); //[cite: 13]
    e.preventDefault();
    const pwdInput = document.getElementById('pwdInput').value;
    const loginStatus = document.getElementById('loginStatus');
    const submitBtn = document.getElementById('loginSubmitBtn');

    setButtonLoading(submitBtn, true, 'Проверка...');
    setStatusLoading(loginStatus, 'Проверка пароля...');

    try {
        setSavedPassword(pwdInput);
        const verifyResp = await fetchWithAuth('/api/verify-auth', { method: 'POST' });

        if (verifyResp.ok) {
            console.log("[TRACE EXIT] handleLogin -> Auth successful"); //[cite: 13]
            loadMainView('upload');
            // Кнопку намеренно не разблокируем здесь: сейчас произойдёт
            // полная замена контейнера через loadMainView(), а вместе с ним
            // исчезнет и сама форма входа.
        } else {
            clearSavedPassword();
            setButtonLoading(submitBtn, false);
            const errData = await verifyResp.json();
            console.log("[TRACE EXIT] handleLogin -> Auth failed", errData); //[cite: 13]
            setStatusMessage(loginStatus, `❌ ${errData.error || 'Неверный пароль'}`, 'error');
        }
    } catch (err) {
        clearSavedPassword();
        setButtonLoading(submitBtn, false);
        console.error("[TRACE EXIT] handleLogin -> Network error", err); //[cite: 13]
        setStatusMessage(loginStatus, '❌ Ошибка соединения', 'error');
    }
}

async function loadSystemInfo() {
    console.log("[TRACE ENTER] loadSystemInfo"); //[cite: 13]
    const diskInfo = document.getElementById('diskInfo');
    if (!diskInfo) {
        console.log("[TRACE EXIT] loadSystemInfo (no diskInfo element)"); //[cite: 13]
        return;
    }
    setStatusLoading(diskInfo, 'Загрузка сведений о памяти...');
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

        console.log("[TRACE EXIT] loadSystemInfo -> Loaded info", data); //[cite: 13]
    } catch (e) {
        console.error("[TRACE EXIT] loadSystemInfo -> Exception", e); //[cite: 13]
        diskInfo.innerText = "💾 Память ESP32 готова к загрузке";
    }
}

async function loadConfigData() {
    console.log("[TRACE ENTER] loadConfigData"); //[cite: 13]
    const status = document.getElementById('configStatus');
    if (status) setStatusLoading(status, 'Загрузка настроек...');

    try {
        const res = await fetchWithAuth('/api/config');

        if (res.ok) {
            const cfg = await res.json();
            console.log("[TRACE LOAD CONFIG DATA]", cfg); //[cite: 13]
            
            // Заполнение динамического массива Wi-Fi
            const wifiContainer = document.getElementById('wifi_networks_container');
            if (wifiContainer) {
                wifiContainer.innerHTML = '';
                const nets = cfg.wifi_networks || [];
                // Обратная совместимость с одиночным SSID
                if (nets.length === 0 && cfg.wifi_ssid) {
                    nets.push({ssid: cfg.wifi_ssid});
                }
                nets.forEach(n => addWifiNetworkField(n.ssid));
            }
            
            document.getElementById('cfg_boot_mode').value = cfg.boot_mode || 'music_first';
            document.getElementById('cfg_repeat_count').value = cfg.repeat_count || 1;
            document.getElementById('cfg_max_duration').value = cfg.max_play_duration_sec || 0;
            document.getElementById('cfg_fade_out').value = cfg.fade_out_ms || 1000;
            document.getElementById('cfg_smart_timeout').value = cfg.smart_timeout_sec || 7;
            document.getElementById('cfg_auth_smart_timeout').value = cfg.auth_smart_timeout_sec || 600;
            document.getElementById('cfg_last_pos_sec').value = cfg.last_play_pos_sec !== undefined ? cfg.last_play_pos_sec : 0;
            document.getElementById('cfg_resume_playback').checked = !!cfg.resume_playback;
            document.getElementById('cfg_upload_password').value = getSavedPassword();
            
            if (status) setStatusMessage(status, "");
            console.log("[TRACE EXIT] loadConfigData -> Success"); //[cite: 13]
        } else {
            console.warn("[TRACE EXIT] loadConfigData -> Response not OK"); //[cite: 13]
            if (status) setStatusMessage(status, '❌ Ошибка загрузки настроек', 'error');
        }
    } catch (e) {
        console.error("[TRACE EXIT] loadConfigData -> Error", e); //[cite: 13]
        if (status) setStatusMessage(status, '❌ Сбой связи с ESP32', 'error');
    }
}

async function saveConfig(e) {
    console.log("[TRACE ENTER] saveConfig"); //[cite: 13]
    e.preventDefault();
    const status = document.getElementById('configStatus');
    const submitBtn = document.getElementById('saveConfigBtn');
    setButtonLoading(submitBtn, true, 'Сохранение...');
    setStatusLoading(status, 'Авторизация и запись...');

    try {
        const newUploadPwd = document.getElementById('cfg_upload_password').value;

        // Сборка массива сетей из формы
        const wifiNodes = document.querySelectorAll('.wifi-row');
        const wifiNetworks = [];
        wifiNodes.forEach(node => {
            const ssid = node.querySelector('.wifi-ssid').value.trim();
            const pass = node.querySelector('.wifi-pass').value;
            if (ssid) wifiNetworks.push({ ssid: ssid, password: pass });
        });

        const payload = {
            boot_mode: document.getElementById('cfg_boot_mode').value,
            repeat_count: parseInt(document.getElementById('cfg_repeat_count').value),
            max_play_duration_sec: parseInt(document.getElementById('cfg_max_duration').value),
            fade_out_ms: parseInt(document.getElementById('cfg_fade_out').value),
            smart_timeout_sec: parseInt(document.getElementById('cfg_smart_timeout').value),
            auth_smart_timeout_sec: parseInt(document.getElementById('cfg_auth_smart_timeout').value),
            last_play_pos_sec: parseFloat(document.getElementById('cfg_last_pos_sec').value) || 0,
            resume_playback: document.getElementById('cfg_resume_playback').checked,
            wifi_networks: wifiNetworks,
            upload_password: newUploadPwd
        };

        console.log("[TRACE SAVE CONFIG PAYLOAD]", payload); //[cite: 13]

        const res = await fetchWithAuth('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            setSavedPassword(newUploadPwd);
            setButtonLoading(submitBtn, false);
            setStatusMessage(status, '✅ Настройки сохранены в config.json!', 'success');
            console.log("[TRACE EXIT] saveConfig -> Saved successfully"); //[cite: 13]
        } else {
            const err = await res.json();
            setButtonLoading(submitBtn, false);
            setStatusMessage(status, `❌ ${err.error || 'Ошибка записи'}`, 'error');
            console.warn("[TRACE EXIT] saveConfig -> Failed", err); //[cite: 13]
        }
    } catch (err) {
        console.error("[TRACE EXIT] saveConfig -> Exception", err); //[cite: 13]
        setButtonLoading(submitBtn, false);
        setStatusMessage(status, '❌ Ошибка сети при сохранении', 'error');
    }
}

async function playOnEsp32() {
    console.log("[TRACE ENTER] playOnEsp32"); //[cite: 13]
    const status = document.getElementById('status');
    const btn = document.getElementById('togglePlayBtn');
    setButtonLoading(btn, true, 'Запуск...');
    setStatusLoading(status, 'Подготовка авторизации...');

    try {
        const resp = await fetchWithAuth('/api/play', { method: 'POST' });

        const result = await resp.json();
        if (resp.ok) {
            setStatusMessage(status, '▶ Воспроизведение заведено на ESP32', 'success');
            isEsp32Playing = true;
            updatePlayButtonUI(true);
            console.log("[TRACE EXIT] playOnEsp32 -> Playing started"); //[cite: 13]
        } else {
            setStatusMessage(status, `❌ ${result.error || 'Ошибка воспроизведения'}`, 'error');
            isEsp32Playing = false;
            updatePlayButtonUI(false);
            console.warn("[TRACE EXIT] playOnEsp32 -> Server rejected play request", result); //[cite: 13]
        }
    } catch (err) {
        console.error("[TRACE EXIT] playOnEsp32 -> Exception", err); //[cite: 13]
        setStatusMessage(status, '❌ Сбой соединения с ESP32', 'error');
        isEsp32Playing = false;
        updatePlayButtonUI(false);
    }
}

async function stopOnEsp32() {
    console.log("[TRACE ENTER] stopOnEsp32"); //[cite: 13]
    const status = document.getElementById('status');
    const btn = document.getElementById('togglePlayBtn');
    setButtonLoading(btn, true, 'Остановка...');
    try {
        const resp = await fetchWithAuth('/api/stop', { method: 'POST' });

        if (resp.ok) {
            setStatusMessage(status, '⏹ Воспроизведение остановлено', 'neutral');
            console.log("[TRACE EXIT] stopOnEsp32 -> Playback stopped"); //[cite: 13]
        }
    } catch (err) {
        console.error("[TRACE EXIT] stopOnEsp32 -> Exception", err); //[cite: 13]
        setStatusMessage(status, '❌ Сбой соединения с ESP32', 'error');
    } finally {
        isEsp32Playing = false;
        updatePlayButtonUI(false);
    }
}

async function logout() {
    console.log("[TRACE ENTER] logout"); //[cite: 13]
    try {
        await fetch('/api/logout', { method: 'POST' });
        console.log("[TRACE EXIT] logout -> Reset server timeout success"); //[cite: 13]
    } catch (err) {
        console.error("[TRACE EXIT] logout -> Error notifying server", err); //[cite: 13]
    }

    clearSavedPassword();
    clearAudioState();
    isEsp32Playing = false;
    console.log("[TRACE EXIT] logout"); //[cite: 13]
    loadView('login.html');
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        console.log("[TRACE ENTER] DOMContentLoaded event listener"); //[cite: 13]
        loadView('login.html');
        console.log("[TRACE EXIT] DOMContentLoaded event listener"); //[cite: 13]
    });
} else {
    console.log("[TRACE ENTER] Direct script load initial view"); //[cite: 13]
    loadView('login.html');
    console.log("[TRACE EXIT] Direct script load initial view"); //[cite: 13]
}


async function openWifiScanModal() {
    const modal = document.getElementById('wifiModal');
    const listContainer = document.getElementById('wifiModalList');
    if (!modal || !listContainer) return;
    
    modal.style.display = 'flex';
    listContainer.innerHTML = '<p style="text-align:center; color:var(--color-muted);">Сканирование эфира...</p>';
    
    try {
        const res = await fetchWithAuth('/api/wifi-scan');
        if (res.ok) {
            const data = await res.json();
            const nets = data.networks || [];
            if (nets.length === 0) {
                listContainer.innerHTML = '<p style="text-align:center; color:var(--color-muted);">Сети не найдены</p>';
                return;
            }
            listContainer.innerHTML = '';
            nets.forEach(net => {
                const item = document.createElement('div');
                item.style.padding = '8px 12px';
                item.style.border = '1px solid var(--color-border-light)';
                item.style.borderRadius = 'var(--radius-md)';
                item.style.cursor = 'pointer';
                item.style.display = 'flex';
                item.style.justifyContent = 'space-between';
                item.style.alignItems = 'center';
                item.style.marginBottom = '6px';
                item.innerHTML = `<span><strong>${net.ssid}</strong></span><span style="font-size:12px; color:var(--color-muted);">${net.rssi} dBm</span>`;
                item.onmouseover = () => item.style.background = 'var(--color-surface-subtle)';
                item.onmouseout = () => item.style.background = 'transparent';
                item.onclick = () => {
                    addWifiNetworkField(net.ssid);
                    closeWifiModal();
                };
                listContainer.appendChild(item);
            });
        } else {
            listContainer.innerHTML = '<p style="text-align:center; color:#ef4444;">Ошибка сканирования</p>';
        }
    } catch (err) {
        listContainer.innerHTML = '<p style="text-align:center; color:#ef4444;">Ошибка сети</p>';
    }
}

function closeWifiModal() {
    const modal = document.getElementById('wifiModal');
    if (modal) modal.style.display = 'none';
}