// static/js/auth.js — login, register, post-register offer

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
  const auth = document.getElementById('auth-screen');
  const offer = document.getElementById('post-register-offer');
  const created = document.getElementById('account-created');
  if (auth) auth.style.display = 'none';
  if (offer) offer.style.display = 'none';
  if (created) created.style.display = 'none';
}

function showChatShell() {
  hideAllAuthScreens();
  const chat = document.getElementById('chat-wrapper');
  if (chat) chat.classList.add('visible');
}

function showPostRegisterOffer(name) {
  hideAllAuthScreens();
  const offer = document.getElementById('post-register-offer');
  const offerName = document.getElementById('offer-name');
  if (offerName) offerName.textContent = name || 'there';
  if (offer) offer.style.display = 'flex';
}

function showAccountCreated(name) {
  hideAllAuthScreens();
  const created = document.getElementById('account-created');
  const suffix = document.getElementById('created-name-suffix');
  if (suffix) suffix.textContent = name ? `, ${name}` : '';
  if (created) created.style.display = 'flex';
}

function continueWithFree() {
  // Prefer going straight into chat after free path
  goToChatAfterAuth();
}

function goToChatAfterRegister() {
  goToChatAfterAuth();
}

function goToChatAfterAuth() {
  showChatShell();

  // Prefer existing chat helpers if present (still in chat.html for now)
  if (typeof loadUserHistory === 'function') loadUserHistory();
  if (typeof updateSubscriptionDisplay === 'function') updateSubscriptionDisplay();
  if (typeof updateUsageCounter === 'function') updateUsageCounter();
  if (typeof refreshUserData === 'function') refreshUserData();
  if (typeof updateAvailability === 'function') updateAvailability();
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
    // OAuth2-style form login (common with your FastAPI setup)
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

    const token = data.access_token || data.token;
    if (!token) {
      showAuthError('Login failed — no token returned');
      return;
    }

    localStorage.setItem('token', token);

    // Optional user payload from login response
    if (data.user) {
      localStorage.setItem('user', JSON.stringify(data.user));
    } else if (data.full_name || data.email) {
      localStorage.setItem('user', JSON.stringify({
        id: data.id,
        email: data.email,
        full_name: data.full_name,
        subscription_tier: data.subscription_tier || 'free'
      }));
    }

    // Refresh user display fields if chat helpers exist
    if (typeof refreshUserData === 'function') {
      await refreshUserData();
    }

    goToChatAfterAuth();
  } catch (err) {
    console.error('login error:', err);
    showAuthError('Something went wrong. Try again.');
  }
}

async function register() {
  clearAuthError();

  const fullName = (document.getElementById('reg-name')?.value || '').trim();
  const email = (document.getElementById('reg-email')?.value || '').trim();
  const password = document.getElementById('reg-password')?.value || '';

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

    // Auto-login after register (same form login)
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

    const token = loginData.access_token || loginData.token;
    localStorage.setItem('token', token);
    localStorage.setItem('user', JSON.stringify({
      email,
      full_name: fullName,
      subscription_tier: 'free'
    }));

    // Show premium offer after register
    showPostRegisterOffer(fullName);
  } catch (err) {
    console.error('register error:', err);
    showAuthError('Something went wrong. Try again.');
  }
}

// Enter key on auth inputs
document.addEventListener('DOMContentLoaded', () => {
  const loginPass = document.getElementById('login-password');
  const regPass = document.getElementById('reg-password');

  if (loginPass) {
    loginPass.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        login();
      }
    });
  }
  if (regPass) {
    regPass.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        register();
      }
    });
  }
});
