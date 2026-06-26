/** 009 鉴权客户端 — admin/desk 共用 */
const TOKEN_KEY = 'mitako_auth_token_v1';
const USER_KEY = 'mitako_auth_user_v1';

export function getAuthToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export function getAuthUser() {
  try {
    const raw = sessionStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setAuthSession(token, user) {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* 隐私模式忽略 */
  }
}

export function clearAuthSession() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

export function authHeaders(extra = {}) {
  const token = getAuthToken();
  const headers = { ...extra };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function fetchAuthStatus() {
  const r = await fetch('/api/v1/auth/status');
  const data = await r.json();
  return Boolean(data.auth_required);
}

export async function login(username, password, tenantId = 'mitako') {
  const r = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, tenant_id: tenantId }),
  });
  const data = await r.json();
  if (!data.ok) throw new Error(data.error || 'login_failed');
  setAuthSession(data.token, data.user);
  return data.user;
}

export async function authFetch(url, options = {}) {
  const headers = authHeaders(options.headers || {});
  const r = await fetch(url, { ...options, headers });
  if (r.status === 401) {
    clearAuthSession();
    window.dispatchEvent(new CustomEvent('mitako:auth:logout'));
  }
  return r;
}
