// static/js/auth.js

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  if (!el) return;
  el.textContent = msg || 'Something went wrong';
  el.style.display = 'block';
}

function clearAuthError() {
  const el = document.getElementById('auth-error');
  if (!el) return;
  el.textContent = '';
  el.style.display = 'none';
}

function showLogin() {
  clearAuthError();
  const loginForm = document.getElementById('login-form');
  const registerForm = document.getElementById('register-form');
  if (loginForm) loginForm.style.display = 'block';
  if (registerForm) registerForm.style.display = 'none';
}

function showRegister() {
  clearAuthError();
  const loginForm = document.getElementById('login-form');
  const registerForm = document.getElementById('register-form');
  if (loginForm) loginForm.style.display = 'none';
  if (registerForm) registerForm.style.display = 'block';
}

function hideAllAuthScreens() {
  ['auth-screen', 'post-register-offer', 'account-created'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

function syncAuthToPage(accessToken, user) {
  localStorage.setItem('token', accessToken);
  if (user) localStorage.setItem('user', JSON.stringify(user));

  // Keep chat.html globals in sync
  window.token = accessToken;
  window.currentUser = user || null;

  try {
    // These exist in the inline chat script
    if (typeof token !== 'undefined') token = accessToken;
    if (typeof currentUser !== 'undefined') currentUser = user || null;
    if (user && user.id && typeof convoId !== 'undefined') {
      convoId = `user_${user.id}`;
      localStorage.setItem('convo_id', convoId);
    }
  } catch (e) {
    // ignore scope issues; window.* is the backup
  }
}

function showChatShell() {
  hideAllAuthScreens();
  const chat = document.getElementById('chat-wrapper');
  if (chat) {
    chat.classList.add('visible');
    chat.style.display = 'flex';
  }
}

function showPostRegisterOffer(name) {
  hideAllAuthScreens();
  const offer = document.getElementById('post-register-offer');
  const offerName = document.getElementById('offer-name');
  if (offerName) offerName.textContent = name || 'there';
  if (offer) offer.style.display = 'flex';
}

function continueWithFree() {
  goToChatAfterAuth();
}

function goToChatAfterRegister() {
  goToChatAfterAuth();
}

function goToChatAfterAuth() {
  showChatShell();

  const user = window.currentUser || JSON.parse(localStorage.getItem('user') || '{}');
  const userInfo = document.getElementById('user-info');
  if (userInfo) {
    userInfo.textContent = `Hi, ${user.full_name || user.email || 'User'}`;
  }

  if (typeof updateSubscriptionDisplay === 'function') updateSubscriptionDisplay();
  if (typeof updateUsageCounter === 'function') updateUsageCounter();
  if (typeof loadUserHistory === 'function') loadUserHistory();
  if (typeof refreshUserData === 'function') refreshUserData();
  if (typeof updateAvailability === 'function') updateAvailability();
}

function readRegisterFields() {
  const form = document.getElementById('register-form');
  const nameInput =
    document.getElementById('reg-name') ||
    form?.querySelector('input[type="text"]');
  const emailInput =
    document.getElementById('reg-email') ||
    form?.querySelector('input[type="email"]');
  const passInput =
    document.getElementById('reg-password') ||
    form?.querySelector('input[type="password"]');

  return {
    fullName: (nameInput?.value || '').trim(),
    email: (emailInput?.value || '').trim(),
    password: passInput?.value || ''
  };
}

async function login() {
  clearAuthError();

  const email = (document.getElementById('login-email')?.value || '').trim();
  const password = document.getElementById('login-password')?.value || '';

  if (!email || !password) {
    showAuthError('Enter email and password.');
    return;
  }

  try {
    const body = new URLSearchParams();
    body.append('username', email);
    body.append('password', password);

    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showAuthError(data.detail || 'Login failed');
      return;
    }

    const accessToken = data.access_token || data.token;
    if (!accessToken) {
      showAuthError('Login failed — no token returned');
      return;
    }

    const user = data.user || {
      id: data.id,
      email: data.email || email,
      full_name: data.full_name,
      subscription_tier: data.subscription_tier || 'free'
    };

    syncAuthToPage(accessToken, user);
    window.location.href = '/';
  } catch (err) {
    console.error('login error:', err);
    showAuthError('Something went wrong. Try again.');
  }
}

async function register() {
  clearAuthError();

  const { fullName, email, password } = readRegisterFields();

  console.log('register fields:', { fullName, email, passwordLength: password.length });

  if (!fullName || !email || !password) {
    showAuthError('Fill in name, email, and password.');
    return;
  }

  try {
    const res = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        password,
        full_name: fullName
      })
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      const msg = typeof detail === 'string'
        ? detail
        : (Array.isArray(detail) ? detail.map(d => d.msg).join(', ') : 'Registration failed');
      showAuthError(msg);
      return;
    }

    // Auto-login
    const body = new URLSearchParams();
    body.append('username', email);
    body.append('password', password);

    const loginRes = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body
    });
    const loginData = await loginRes.json().catch(() => ({}));

    if (!loginRes.ok || !(loginData.access_token || loginData.token)) {
      showAuthError('Account created, but login failed. Try logging in.');
      showLogin();
      return;
    }

    const accessToken = loginData.access_token || loginData.token;
    const user = loginData.user || {
      email,
      full_name: fullName,
      subscription_tier: 'free'
    };

    syncAuthToPage(accessToken, user);
    window.location.href = '/';
  } catch (err) {
    console.error('register error:', err);
    showAuthError('Something went wrong. Try again.');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('login-password')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      login();
    }
  });
  document.getElementById('reg-password')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      register();
    }
  });
});
