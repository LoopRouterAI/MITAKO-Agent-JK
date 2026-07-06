import React, { useCallback, useEffect, useState } from 'react';
import AdminLogin from './AdminLogin.jsx';
import AdminShell from './AdminShell.jsx';
import HandoffAdmin from './HandoffAdmin.jsx';
import { clearAuthSession, fetchAuthStatus, getAuthUser, setAuthSession } from '../lib/authClient.js';

const ADMIN_ROLES = new Set(['super_admin', 'supervisor', 'bpo_manager']);

/** /admin 根组件 — 鉴权门控 + 多模块 Shell */
export default function AdminApp() {
  const [authRequired, setAuthRequired] = useState(false);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState(() => getAuthUser());

  const refresh = useCallback(async () => {
    const required = await fetchAuthStatus();
    setAuthRequired(required);
    if (!required) setUser({ username: '运营账号', display_name: '运营账号', role: 'super_admin' });
    else if (!getAuthUser()) setUser(null);
    else setUser(getAuthUser());
    setReady(true);
  }, []);

  useEffect(() => {
    refresh();
    const onLogout = () => {
      clearAuthSession();
      setUser(null);
    };
    const onForbidden = () => setUser(null);
    window.addEventListener('mitako:auth:logout', onLogout);
    window.addEventListener('mitako:auth:forbidden', onForbidden);

    const params = new URLSearchParams(window.location.search);
    if (params.get('sso') === '1' && params.get('code') && params.get('state')) {
      let tenantId = 'mitako';
      try {
        tenantId = sessionStorage.getItem('mitako_sso_tenant_v1') || 'mitako';
      } catch {
        tenantId = 'mitako';
      }
      (async () => {
        try {
          const cr = await fetch('/api/v1/auth/sso/callback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              tenant_id: tenantId,
              code: params.get('code'),
              state: params.get('state'),
            }),
          });
          const data = await cr.json();
          if (data.ok && ADMIN_ROLES.has(data.user?.role)) {
            setAuthSession(data.token, data.user);
            setUser(data.user);
            window.history.replaceState({}, '', '/admin');
          } else {
            clearAuthSession();
            setUser(null);
          }
        } catch (e) {
          console.error(e);
        }
      })();
    }

    return () => {
      window.removeEventListener('mitako:auth:logout', onLogout);
      window.removeEventListener('mitako:auth:forbidden', onForbidden);
    };
  }, [refresh]);

  if (!ready) return null;
  if (user && !ADMIN_ROLES.has(user.role)) {
    clearAuthSession();
    return <AdminLogin onSuccess={u => setUser(ADMIN_ROLES.has(u.role) ? u : null)} />;
  }
  if (authRequired && !user) {
    return <AdminLogin onSuccess={u => setUser(u)} />;
  }
  return <div className="mitako-ppt-scope min-h-[100dvh]"><AdminShell user={user} legacyRouting={<HandoffAdmin embedded />} /></div>;
}
