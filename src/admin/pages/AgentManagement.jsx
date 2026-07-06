import React, { useCallback, useEffect, useState } from 'react';
import { Trash2, Save } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';
import { sanitizePublicText } from '../../utils/publicText.js';

const EMPTY = { agent_id: '', name: '', title: '', tier: 'standard', team: '', skills: [], enabled: true };
const inputClass = 'w-full rounded-[8px] border border-slate-200 px-3 py-2 text-sm outline-none focus:bg-[var(--mitako-lime-soft)] focus:ring-2 focus:ring-[var(--mitako-lime)]';
const cardClass = 'rounded-[8px] border border-slate-200 bg-white shadow-[0_16px_34px_rgba(16,19,31,.08)]';

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
    const target = agents.find(a => a.agent_id === id);
    if (!window.confirm(`确认停用/删除客服账号「${target?.name || id}」？该操作会影响后续接单。`)) return;
    await authFetch(`/api/v1/admin/agents/${encodeURIComponent(id)}`, { method: 'DELETE' });
    load();
  };

  const tierLabel = (tier) => ({
    standard: t('desk.tierStandard'),
    supervisor: t('desk.tierSupervisor'),
  }[tier] || t('desk.tierStandard'));

  const teamLabel = (team) => (team ? sanitizePublicText(team) : '客服中心');

  return (
    <div className="p-6 space-y-4 max-w-3xl">
      <h1 className="text-xl font-bold">{t('admin.navAgents')}</h1>
      {msg && <p className="text-sm font-bold text-[var(--mitako-ink)]">{msg}</p>}
      <div className={`${cardClass} p-4 space-y-3`}>
        <input placeholder={t('admin.agentId')} value={draft.agent_id} onChange={e => setDraft(d => ({ ...d, agent_id: e.target.value }))} className={inputClass} />
        <input placeholder={t('admin.agentName')} value={draft.name} onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} className={inputClass} />
        <select value={draft.tier} onChange={e => setDraft(d => ({ ...d, tier: e.target.value }))} className={inputClass}>
          <option value="standard">{t('desk.tierStandard')}</option>
          <option value="supervisor">{t('desk.tierSupervisor')}</option>
        </select>
        <button type="button" onClick={save} className="inline-flex items-center gap-1 rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] px-4 py-2 text-sm font-bold shadow-[0_12px_26px_rgba(127,164,49,.22)]">
          <Save className="w-4 h-4" /> {t('admin.saveAgent')}
        </button>
      </div>
      <ul className="space-y-2">
        {agents.map(a => (
          <li key={a.agent_id} className={`${cardClass} flex items-center justify-between px-4 py-3`}>
            <div>
              <p className="font-bold text-sm">{a.name}</p>
              <p className="text-xs text-slate-500">{teamLabel(a.team)} · {tierLabel(a.tier)}</p>
            </div>
            <button type="button" aria-label={`删除客服账号 ${a.name}`} onClick={() => remove(a.agent_id)} className="rounded-[8px] border border-slate-200 bg-white p-2 text-slate-600 hover:bg-rose-50 hover:text-rose-600">
              <Trash2 className="w-4 h-4" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
