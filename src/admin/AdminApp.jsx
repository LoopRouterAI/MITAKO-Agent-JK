import React, { useCallback, useEffect, useState } from 'react';
import AdminLogin from './AdminLogin.jsx';
import AdminShell from './AdminShell.jsx';
import HandoffAdmin from './HandoffAdmin.jsx';
import { clearAuthSession, fetchAuthStatus, getAuthUser } from '../lib/authClient.js';

/** /admin 根组件 — 鉴权门控 + 多模块 Shell */
export default function AdminApp() {
  const [authRequired, setAuthRequired] = useState(false);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState(() => getAuthUser());

  const refresh = useCallback(async () => {
    const required = await fetchAuthStatus();
    setAuthRequired(required);
    if (!required) setUser({ username: 'dev', role: 'super_admin' });
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
    window.addEventListener('mitako:auth:logout', onLogout);

    const params = new URLSearchParams(window.location.search);
    if (params.get('sso') === '1' && params.get('code') && params.get('state')) {
      const tenantId = sessionStorage.getItem('mitako_sso_tenant_v1') || 'mitako';
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
          if (data.ok) {
            setAuthSession(data.token, data.user);
            setUser(data.user);
            window.history.replaceState({}, '', '/admin');
          }
        } catch (e) {
          console.error(e);
        }
      })();
    }

    return () => window.removeEventListener('mitako:auth:logout', onLogout);
  }, [refresh]);

  if (!ready) return null;
  if (authRequired && !user) {
    return <AdminLogin onSuccess={u => setUser(u)} />;
  }
  return <AdminShell user={user} legacyRouting={<HandoffAdmin embedded />} />;
}
