/** Companion C 端鉴权 — 与 admin authClient 分离 */
const TOKEN_KEY = 'mitako_companion_token_v1';

export function getCompanionToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export function setCompanionToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* ignore */
  }
}

export function clearCompanionToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export function companionHeaders(extra = {}) {
  const token = getCompanionToken();
  const headers = { ...extra };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function companionFetch(url, options = {}) {
  const headers = companionHeaders(options.headers || {});
  const r = await fetch(url, { ...options, headers });
  if (r.status === 401) clearCompanionToken();
  return r;
}

/** 从 onboarding 响应中提取并保存 companion_token */
export function absorbCompanionToken(json) {
  if (json?.companion_token) setCompanionToken(json.companion_token);
}
