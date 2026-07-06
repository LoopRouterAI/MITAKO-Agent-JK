import React, { useCallback, useEffect, useState } from 'react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

const inputClass = 'rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:bg-[var(--mitako-lime-soft)]';
const cardClass = 'tool-panel rounded-[8px] bg-white p-4';

export default function QueueMonitor() {
  const [snap, setSnap] = useState(null);
  const [reassignTo, setReassignTo] = useState('');
  const [agents, setAgents] = useState([]);
  const [message, setMessage] = useState('');
  const [loadError, setLoadError] = useState('');
  const [busyId, setBusyId] = useState('');

  const load = useCallback(async () => {
    try {
      setLoadError('');
      const [sR, aR] = await Promise.all([
        authFetch('/api/v1/admin/queue/snapshot'),
        authFetch('/api/v1/admin/agents'),
      ]);
      const s = await sR.json();
      const a = await aR.json();
      if (s.ok) setSnap(s.snapshot);
      else setLoadError(s.message || s.error || '队列数据加载失败');
      if (a.ok) setAgents(a.agents || []);
      else setLoadError(a.message || a.error || '客服列表加载失败');
    } catch (e) {
      console.error(e);
      setLoadError('队列数据加载失败，请检查网络或重新登录后再试');
    }
  }, []);

  useEffect(() => { load(); const tmr = setInterval(load, 4000); return () => clearInterval(tmr); }, [load]);

  const reassign = async (sessionId) => {
    setMessage('');
    if (!reassignTo) {
      setMessage('请先选择要接管的客服人员。');
      return;
    }
    if (!window.confirm('确认将该会话转派给选中的客服吗？')) return;
    setBusyId(sessionId);
    try {
      const r = await authFetch(`/api/v1/admin/queue/${encodeURIComponent(sessionId)}/reassign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to_agent_id: reassignTo, note: '运营后台转派' }),
      });
      const data = await r.json();
      setMessage(data.message || (data.ok ? '转派已提交。' : '转派失败，请刷新后重试。'));
      if (data.ok) load();
    } catch (e) {
      console.error(e);
      setMessage('转派失败，请检查网络后重试。');
    } finally {
      setBusyId('');
    }
  };

  const sessions = (snap?.sessions || []).filter(s => s.status in { queuing: 1, escalated: 1, connected: 1, transferring: 1 });
  const statusLabel = (status) => ({
    queuing: '排队中',
    connected: '已接入',
    escalated: '待升级处理',
    transferring: '转交中',
    closed: '已关闭',
  }[status] || '处理中');
  const tierLabel = (tier) => ({
    standard: t('desk.tierStandard'),
    supervisor: t('desk.tierSupervisor'),
  }[tier] || t('desk.tierStandard'));
  const businessNo = (sessionId) => {
    const suffix = String(sessionId || '').replace(/[^a-zA-Z0-9]/g, '').slice(-6).toUpperCase();
    return suffix ? `会话 ${suffix}` : '待处理会话';
  };
  const fmtDuration = (seconds = 0) => {
    const min = Math.floor((Number(seconds) || 0) / 60);
    if (min < 1) return '1 分钟内';
    if (min < 60) return `${min} 分钟`;
    return `${Math.floor(min / 60)} 小时 ${min % 60} 分钟`;
  };

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">{t('admin.navQueue')}</h1>
          <p className="mt-1 text-sm text-slate-500">按真实排队顺序查看等待、风险和接管状态；强制转派会锁定会话，等待目标客服确认。</p>
        </div>
        <label className="flex gap-2 items-center text-sm">
          <span className="font-bold">{t('admin.reassignTarget')}</span>
          <select value={reassignTo} onChange={e => setReassignTo(e.target.value)} className={inputClass}>
            <option value="">请选择客服</option>
            {agents.map(a => <option key={a.agent_id} value={a.agent_id}>{a.name} · {tierLabel(a.tier)}</option>)}
          </select>
        </label>
      </div>
      {loadError && (
        <div className="rounded-[8px] border border-red-200 bg-red-50 px-3 py-2 text-sm font-bold text-red-700">
          {loadError}
          <button type="button" onClick={load} className="ml-3 rounded-[8px] border border-red-200 bg-white px-2 py-1 text-xs">重试</button>
        </div>
      )}
      {message && <p className="rounded-[8px] bg-[var(--mitako-lime-soft)] px-3 py-2 text-sm font-bold text-slate-800">{message}</p>}
      <div className="grid gap-3 sm:grid-cols-4">
        {[
          ['排队中', snap?.queuing || 0],
          ['转交中', snap?.transferring || 0],
          ['最长等待', fmtDuration(snap?.longest_wait_seconds)],
          ['平均等待', fmtDuration(snap?.avg_wait_seconds)],
        ].map(([label, value]) => (
          <div key={label} className="metric-card rounded-[8px] bg-white p-3">
            <p className="text-xl font-black">{value}</p>
            <p className="text-xs text-slate-500">{label}</p>
          </div>
        ))}
      </div>
      <div className="space-y-3">
        {sessions.length === 0 && <p className="rounded-[8px] bg-white p-6 text-center text-sm text-slate-500">当前没有排队或进行中的会话。可以先点击右上角“加载演示数据”查看完整流程。</p>}
        {sessions.map(s => (
          <div key={s.session_id} className={`${cardClass} flex flex-wrap items-center justify-between gap-2`}>
            <div>
              <p className="text-sm font-bold">{businessNo(s.session_id)}</p>
              <p className="text-xs text-slate-500">{statusLabel(s.status)} · {tierLabel(s.required_tier)} · 第 {s.position || '-'} 位 · 已等 {fmtDuration(s.wait_seconds)}</p>
              <p className="mt-1 text-xs text-slate-600">{s.brief?.summary || s.summary || '暂无摘要，请打开服务记录查看。'}</p>
            </div>
            <button type="button" disabled={busyId === s.session_id} onClick={() => reassign(s.session_id)} className="min-h-[40px] text-xs font-bold px-3 py-2 rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] disabled:opacity-60">
              {busyId === s.session_id ? '转派中…' : t('admin.forceReassign')}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
