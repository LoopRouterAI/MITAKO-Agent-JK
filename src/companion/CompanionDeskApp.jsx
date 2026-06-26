import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import t from '../i18n/index.js';
import { authFetch } from '../lib/authClient.js';

/** Companion 独立运营/人工台 — 与 /desk 数据隔离 */
export default function CompanionDeskApp({ authUser = null }) {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState('');
  const [detail, setDetail] = useState(null);
  const [reply, setReply] = useState('');
  const [loading, setLoading] = useState(false);

  const loadSessions = useCallback(async () => {
    try {
      const r = await authFetch('/api/v2/companion/desk/sessions');
      const data = await r.json();
      if (data.ok) setSessions(data.sessions || []);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const loadDetail = useCallback(async (sid) => {
    if (!sid) return;
    try {
      const r = await authFetch(`/api/v2/companion/desk/sessions/${sid}`);
      const data = await r.json();
      if (data.ok) setDetail(data);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    loadSessions();
    const tmr = setInterval(loadSessions, 4000);
    return () => clearInterval(tmr);
  }, [loadSessions]);

  useEffect(() => {
    if (activeId) loadDetail(activeId);
  }, [activeId, loadDetail]);

  const accept = async () => {
    if (!activeId) return;
    setLoading(true);
    try {
      await authFetch(`/api/v2/companion/desk/sessions/${activeId}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ operator: authUser?.username || 'companion_ops' }),
      });
      await loadSessions();
      await loadDetail(activeId);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const sendReply = async () => {
    const text = reply.trim();
    if (!text || !activeId) return;
    setLoading(true);
    try {
      await authFetch(`/api/v2/companion/desk/sessions/${activeId}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text, operator: authUser?.username || 'companion_ops' }),
      });
      setReply('');
      await loadDetail(activeId);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const sess = detail?.session;
  const msgs = detail?.messages || [];

  return (
    <div className="min-h-[100dvh] flex flex-col md:flex-row bg-gradient-to-br from-rose-50 via-white to-purple-50 text-slate-800">
      <aside className="md:w-72 border-b md:border-b-0 md:border-r border-rose-100 bg-white/80 backdrop-blur p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-xs font-bold text-rose-600 uppercase">{t('companionDesk.badge')}</p>
            <h1 className="font-bold">{t('companionDesk.title')}</h1>
          </div>
          <button type="button" onClick={loadSessions} className="p-2 rounded-lg hover:bg-rose-50" aria-label={t('companionDesk.refresh')}>
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
        <ul className="space-y-2 max-h-[60vh] overflow-auto">
          {sessions.length === 0 && <li className="text-xs text-slate-400">{t('companionDesk.empty')}</li>}
          {sessions.map(s => (
            <button
              key={s.session_id}
              type="button"
              onClick={() => setActiveId(s.session_id)}
              className={`w-full text-left rounded-xl px-3 py-2 text-sm border transition-colors ${activeId === s.session_id ? 'border-rose-400 bg-rose-50' : 'border-slate-100 hover:bg-slate-50'}`}
            >
              <p className="font-semibold truncate">{s.user_id}</p>
              <p className="text-[11px] text-slate-500">{s.status} · {s.reason || '—'}</p>
            </button>
          ))}
        </ul>
        <a href="/companion" className="block mt-4 text-xs text-purple-700 font-semibold">{t('companionDesk.backCompanion')}</a>
      </aside>
      <main className="flex-1 flex flex-col min-h-0 p-4 md:p-6">
        {!activeId ? (
          <p className="text-sm text-slate-400 m-auto">{t('companionDesk.pickSession')}</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2 mb-4">
              <span className="text-xs font-mono bg-white border rounded-lg px-2 py-1">{activeId}</span>
              {sess?.status === 'queuing' && (
                <button type="button" disabled={loading} onClick={accept} className="rounded-xl bg-rose-600 text-white px-4 py-2 text-sm font-bold">{t('companionDesk.accept')}</button>
              )}
            </div>
            <div className="flex-1 overflow-auto rounded-2xl border bg-white/90 p-4 space-y-3 mb-4">
              {msgs.map(m => (
                <div key={m.id} className={`text-sm ${m.role === 'operator' ? 'text-right' : ''}`}>
                  <span className="inline-block rounded-2xl px-3 py-2 max-w-[85%] bg-slate-100">{m.content}</span>
                </div>
              ))}
            </div>
            {sess?.status === 'connected' && (
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded-xl border px-4 py-3 text-sm"
                  value={reply}
                  onChange={e => setReply(e.target.value)}
                  placeholder={t('companionDesk.replyPlaceholder')}
                  onKeyDown={e => e.key === 'Enter' && sendReply()}
                />
                <button type="button" disabled={loading} onClick={sendReply} className="rounded-xl bg-[#7B61FF] text-white px-5 font-bold text-sm">{t('companionDesk.send')}</button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
