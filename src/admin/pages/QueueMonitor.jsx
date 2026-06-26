import React, { useCallback, useEffect, useState } from 'react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

export default function QueueMonitor() {
  const [snap, setSnap] = useState(null);
  const [reassignTo, setReassignTo] = useState('');
  const [agents, setAgents] = useState([]);

  const load = useCallback(async () => {
    const [sR, aR] = await Promise.all([
      authFetch('/api/v1/admin/queue/snapshot'),
      authFetch('/api/v1/admin/agents'),
    ]);
    const s = await sR.json();
    const a = await aR.json();
    if (s.ok) setSnap(s.snapshot);
    if (a.ok) setAgents(a.agents || []);
  }, []);

  useEffect(() => { load(); const tmr = setInterval(load, 4000); return () => clearInterval(tmr); }, [load]);

  const reassign = async (sessionId) => {
    if (!reassignTo) return;
    await authFetch(`/api/v1/admin/queue/${encodeURIComponent(sessionId)}/reassign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to_agent_id: reassignTo, note: 'admin reassign' }),
    });
    load();
  };

  const sessions = (snap?.sessions || []).filter(s => s.status in { queuing: 1, escalated: 1, connected: 1, transferring: 1 });

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">{t('admin.navQueue')}</h1>
      <div className="flex gap-2 items-center text-sm">
        <span>{t('admin.reassignTarget')}</span>
        <select value={reassignTo} onChange={e => setReassignTo(e.target.value)} className="rounded-lg border px-2 py-1">
          <option value="">—</option>
          {agents.map(a => <option key={a.agent_id} value={a.agent_id}>{a.name}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        {sessions.map(s => (
          <div key={s.session_id} className="rounded-xl border bg-white p-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="font-mono text-sm font-bold">{s.session_id}</p>
              <p className="text-xs text-slate-500">{s.status} · tier={s.required_tier}</p>
            </div>
            <button type="button" onClick={() => reassign(s.session_id)} className="text-xs font-bold px-3 py-1.5 rounded-lg bg-slate-800 text-white">{t('admin.forceReassign')}</button>
          </div>
        ))}
      </div>
    </div>
  );
}
