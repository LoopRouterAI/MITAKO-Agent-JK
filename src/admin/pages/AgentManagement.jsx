import React, { useCallback, useEffect, useState } from 'react';
import { Plus, Trash2, Save } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

const EMPTY = { agent_id: '', name: '', title: '', tier: 'standard', team: '', skills: [], enabled: true };

export default function AgentManagement() {
  const [agents, setAgents] = useState([]);
  const [draft, setDraft] = useState(EMPTY);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    const r = await authFetch('/api/v1/admin/agents');
    const data = await r.json();
    if (data.ok) setAgents(data.agents || []);
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!draft.agent_id || !draft.name) return;
    const r = await authFetch('/api/v1/admin/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...draft,
        skills: typeof draft.skills === 'string' ? draft.skills.split(/[,，]/).map(s => s.trim()).filter(Boolean) : draft.skills,
      }),
    });
    const data = await r.json();
    if (data.ok) {
      setMsg(t('admin.saved'));
      setDraft(EMPTY);
      load();
    }
  };

  const remove = async (id) => {
    await authFetch(`/api/v1/admin/agents/${encodeURIComponent(id)}`, { method: 'DELETE' });
    load();
  };

  return (
    <div className="p-6 space-y-4 max-w-3xl">
      <h1 className="text-xl font-bold">{t('admin.navAgents')}</h1>
      {msg && <p className="text-sm text-teal-700">{msg}</p>}
      <div className="rounded-2xl border bg-white p-4 space-y-3">
        <input placeholder={t('admin.agentId')} value={draft.agent_id} onChange={e => setDraft(d => ({ ...d, agent_id: e.target.value }))} className="w-full rounded-lg border px-3 py-2 text-sm" />
        <input placeholder={t('admin.agentName')} value={draft.name} onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} className="w-full rounded-lg border px-3 py-2 text-sm" />
        <select value={draft.tier} onChange={e => setDraft(d => ({ ...d, tier: e.target.value }))} className="w-full rounded-lg border px-3 py-2 text-sm">
          <option value="standard">{t('desk.tierStandard')}</option>
          <option value="supervisor">{t('desk.tierSupervisor')}</option>
        </select>
        <button type="button" onClick={save} className="inline-flex items-center gap-1 rounded-lg bg-[var(--mitako-purple)] text-white px-4 py-2 text-sm font-bold">
          <Save className="w-4 h-4" /> {t('admin.saveAgent')}
        </button>
      </div>
      <ul className="space-y-2">
        {agents.map(a => (
          <li key={a.agent_id} className="flex items-center justify-between rounded-xl border bg-white px-4 py-3">
            <div>
              <p className="font-bold text-sm">{a.name} <span className="font-mono text-slate-400">{a.agent_id}</span></p>
              <p className="text-xs text-slate-500">{a.team} · {a.tier}</p>
            </div>
            <button type="button" onClick={() => remove(a.agent_id)} className="text-rose-500 p-2"><Trash2 className="w-4 h-4" /></button>
          </li>
        ))}
      </ul>
    </div>
  );
}
