import React, { useCallback, useEffect, useState } from 'react';
import DeskLogin from './DeskLogin.jsx';
import HumanAgentDesk from './HumanAgentDesk.jsx';
import { clearAuthSession, fetchAuthStatus, getAuthUser } from '../lib/authClient.js';

export default function DeskApp() {
  const [authRequired, setAuthRequired] = useState(false);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState(() => getAuthUser());

  const refresh = useCallback(async () => {
    const required = await fetchAuthStatus();
    setAuthRequired(required);
    if (!required) setUser({ username: '客服账号', display_name: '客服账号', role: 'desk_agent', agent_id: 'CS-0816' });
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
  return <HumanAgentDesk authUser={user} />;
}
