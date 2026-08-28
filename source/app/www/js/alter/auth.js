// Хранилище пароля для текущей сессии
let currentPassword = '';

function getCurrentPassword() {
    return currentPassword;
}

function setCurrentPassword(pwd) {
    currentPassword = pwd;
    if (pwd) {
        sessionStorage.setItem('admin_pwd', pwd);
    } else {
        sessionStorage.removeItem('admin_pwd');
    }
}

function initAuthSession() {
    currentPassword = sessionStorage.getItem('admin_pwd') || '';
    return currentPassword;
}

function togglePassword() {
    const pwd = document.getElementById('pwdInput');
    if (pwd) pwd.type = pwd.type === 'password' ? 'text' : 'password';
}

async function sha256(message) {
    const msgBuffer = new TextEncoder().encode(message);
    const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

async function getAuthHeaders() {
    if (!currentPassword) return {};
    try {
        const nonceRes = await fetch('/api/get-nonce');
        if (!nonceRes.ok) return {};
        const { nonce } = await nonceRes.json();
        const hash = await sha256(currentPassword + nonce);
        return {
            'X-Auth-Nonce': nonce,
            'X-Auth-Hash': hash
        };
    } catch (e) {
        return {};
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const pwd = document.getElementById('pwdInput').value;
    const status = document.getElementById('loginStatus');
    
    try {
        const nonceRes = await fetch('/api/get-nonce');
        const { nonce } = await nonceRes.json();
        const hash = await sha256(pwd + nonce);

        const authRes = await fetch('/api/verify-auth', {
            method: 'POST',
            headers: { 'X-Auth-Nonce': nonce, 'X-Auth-Hash': hash }
        });

        if (authRes.ok) {
            setCurrentPassword(pwd);
            loadView('main');
        } else {
            const err = await authRes.json();
            status.innerText = err.error || "Неверный пароль!";
            status.style.color = "#ef4444";
        }
    } catch (err) {
        status.innerText = "Ошибка соединения с устройством";
        status.style.color = "#ef4444";
    }
}

async function logout() {
    const headers = await getAuthHeaders();
    await fetch('/api/logout', { method: 'POST', headers });
    setCurrentPassword('');
    loadView('login');
}