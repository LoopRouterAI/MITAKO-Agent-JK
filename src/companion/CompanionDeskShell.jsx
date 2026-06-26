import React, { useCallback, useEffect, useState } from 'react';
import DeskLogin from '../desk/DeskLogin.jsx';
import CompanionObservabilityApp from './CompanionObservabilityApp.jsx';
import { clearAuthSession, fetchAuthStatus, getAuthUser } from '../lib/authClient.js';

/** Companion 运营台 — 与主 desk 共用 JWT 鉴权 */
export default function CompanionDeskShell() {
  const [authRequired, setAuthRequired] = useState(false);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState(() => getAuthUser());

  const refresh = useCallback(async () => {
    const required = await fetchAuthStatus();
    setAuthRequired(required);
    if (!required) setUser({ username: 'dev', role: 'companion_ops', agent_id: '' });
    else if (!getAuthUser()) setUser(null);
    else setUser(getAuthUser());
    setReady(true);
  }, []);

  useEffect(() => {
    refresh();
    const onLogout = () => { clearAuthSession(); setUser(null); };
    window.addEventListener('mitako:auth:logout', onLogout);
    return () => window.removeEventListener('mitako:auth:logout', onLogout);
  }, [refresh]);

  if (!ready) return null;
  if (authRequired && !user) return <DeskLogin onSuccess={u => setUser(u)} />;
  return <CompanionObservabilityApp authUser={user} />;
}
