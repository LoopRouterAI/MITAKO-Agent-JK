import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Headphones, RefreshCw, Send, User, ClipboardList, CheckCircle2, ArrowUpCircle, AlertTriangle, Users } from 'lucide-react';
import t from '../i18n/index.js';
import RichTextContent from '../components/shared/RichTextContent.jsx';
import { authFetch } from '../lib/authClient.js';
import { attachHandoffTransport } from '../hooks/useHandoffSync.js';

/** PC 端人工客服工作台 — 独立入口 /desk */
export default function HumanAgentDesk({ authUser = null }) {
  const [sessions, setSessions] = useState([]);
  const [agents, setAgents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [activeId, setActiveId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [reply, setReply] = useState('');
  const [loading, setLoading] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [escalating, setEscalating] = useState(false);
  const [escalateNote, setEscalateNote] = useState('');
  const [transferTargetId, setTransferTargetId] = useState('');
  const [transferNote, setTransferNote] = useState('');
  const [transferring, setTransferring] = useState(false);

  const loadAgents = useCallback(async () => {
    try {
      const r = await authFetch('/api/v1/desk/agents');
      const data = await r.json();
      if (data.ok && data.agents?.length) {
        setAgents(data.agents);
        setSelectedAgentId(prev => prev || data.agents[0].agent_id);
      }
    } catch (e) {
      console.error(e);
    }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const r = await authFetch('/api/v1/desk/sessions');
      const data = await r.json();
      if (data.ok) setSessions(data.sessions || []);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const loadDetail = useCallback(async (sessionId) => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const r = await authFetch(`/api/v1/desk/session/${encodeURIComponent(sessionId)}`);
      const data = await r.json();
      if (data.ok) setDetail(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
    loadSessions();
    const timer = setInterval(loadSessions, 8000);
    return () => clearInterval(timer);
  }, [loadAgents, loadSessions]);

  useEffect(() => {
    if (authUser?.agent_id) {
      setSelectedAgentId(prev => prev || authUser.agent_id);
    }
  }, [authUser]);

  useEffect(() => {
    loadDetail(activeId);
    if (!activeId) return undefined;
    const pollDetail = () => loadDetail(activeId);
    const timer = setInterval(pollDetail, 8000);
    const detach = attachHandoffTransport({
      sessionId: activeId,
      enabled: Boolean(activeId),
      onStatus: () => { pollDetail(); loadSessions(); },
      onMessages: () => pollDetail(),
      pollFn: pollDetail,
      pollIntervalMs: 4000,
    });
    return () => {
      clearInterval(timer);
      detach();
    };
  }, [activeId, loadDetail, loadSessions]);

  const selectedAgent = useMemo(
    () => agents.find(a => a.agent_id === selectedAgentId) || null,
    [agents, selectedAgentId],
  );

  const acceptHandoff = async () => {
    if (!activeId || !selectedAgentId) return;
    setAccepting(true);
    try {
      const r = await authFetch(`/api/v1/desk/session/${encodeURIComponent(activeId)}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: selectedAgentId }),
      });
      const data = await r.json();
      if (!data.ok) {
        window.alert(data.message || data.error || t('desk.acceptFailed'));
        return;
      }
      loadDetail(activeId);
      loadSessions();
    } catch (e) {
      console.error(e);
    } finally {
      setAccepting(false);
    }
  };

  const escalateHandoff = async () => {
    if (!activeId) return;
    setEscalating(true);
    try {
      const r = await authFetch(`/api/v1/desk/session/${encodeURIComponent(activeId)}/escalate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: escalateNote.trim() }),
      });
      const data = await r.json();
      if (data.ok) {
        setEscalateNote('');
        loadDetail(activeId);
        loadSessions();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setEscalating(false);
    }
  };

  const transferColleague = async () => {
    if (!activeId || !transferTargetId) return;
    setTransferring(true);
    try {
      const fromId = detail?.assigned_agent?.agent_id || selectedAgentId;
      const r = await authFetch(`/api/v1/desk/session/${encodeURIComponent(activeId)}/transfer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_agent_id: fromId, to_agent_id: transferTargetId, note: transferNote.trim() }),
      });
      const data = await r.json();
      if (!data.ok) {
        window.alert(data.message || data.error || t('desk.transferSubmit'));
        return;
      }
      setTransferNote('');
      loadDetail(activeId);
      loadSessions();
    } catch (e) {
      console.error(e);
    } finally {
      setTransferring(false);
    }
  };

  const sendReply = async () => {
    if (!activeId || !reply.trim() || !detail?.can_chat) return;
    const agentId = detail?.assigned_agent?.agent_id || selectedAgentId;
    const r = await authFetch(`/api/v1/desk/session/${encodeURIComponent(activeId)}/reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: reply.trim(), agent_id: agentId }),
    });
    const data = await r.json();
    if (!data.ok) {
      window.alert(data.message || t('desk.replyBlocked'));
      return;
    }
    setReply('');
    loadDetail(activeId);
  };

  const brief = detail?.brief;
  const canAccept = detail?.can_accept;
  const canChat = detail?.can_chat;
  const isEscalated = detail?.status === 'escalated';
  const needsSupervisor = detail?.required_tier === 'supervisor';
  const isTransferring = detail?.status === 'transferring';
  const isSupervisor = selectedAgent?.tier === 'supervisor';
  const colleagueOptions = useMemo(
    () => agents.filter(a => a.agent_id !== (detail?.assigned_agent?.agent_id || selectedAgentId)),
    [agents, detail?.assigned_agent, selectedAgentId],
  );

  const statusLabel = (status) => {
    if (status === 'connected') return t('desk.statusConnected');
    if (status === 'escalated') return t('desk.statusEscalated');
    if (status === 'transferring') return t('desk.transferPending');
    return t('desk.statusQueuing');
  };

  const statusClass = (status) => {
    if (status === 'connected') return 'bg-emerald-100 text-emerald-700';
    if (status === 'escalated') return 'bg-rose-100 text-rose-700';
    if (status === 'transferring') return 'bg-sky-100 text-sky-700';
    return 'bg-amber-100 text-amber-700';
  };

  return (
    <div className="min-h-[100dvh] bg-slate-100 text-slate-800 flex flex-col">
      <header className="flex-shrink-0 px-6 py-4 bg-white border-b border-slate-200 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center text-white">
            <Headphones className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold">{t('desk.title')}</h1>
            <p className="text-xs text-slate-500">{t('desk.subtitle')}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-2 text-xs">
            <span className="text-slate-500 font-semibold">{t('desk.agentIdentity')}</span>
            <select
              value={selectedAgentId}
              onChange={e => setSelectedAgentId(e.target.value)}
              className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs font-mono bg-white min-w-[180px]"
            >
              {agents.map(a => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.agent_id} · {a.name} · {a.tier === 'supervisor' ? t('desk.tierSupervisor') : t('desk.tierStandard')}
                </option>
              ))}
            </select>
          </label>
          <a href="/" target="_blank" rel="noopener noreferrer" className="text-xs font-semibold text-teal-700 hover:underline">
            {t('desk.openCustomerDemo')}
          </a>
          <button type="button" onClick={() => { loadSessions(); loadAgents(); }} className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50">
            <RefreshCw className="w-3.5 h-3.5" /> {t('desk.refresh')}
          </button>
        </div>
      </header>

      <div className="flex-1 min-h-0 grid grid-cols-12 gap-0">
        <aside className="col-span-3 min-h-0 border-r border-slate-200 bg-white overflow-y-auto console-scroll">
          <p className="px-4 py-3 text-xs font-bold text-slate-400 uppercase tracking-wide">{t('desk.queueTitle')}</p>
          {sessions.length === 0 ? (
            <p className="px-4 py-8 text-sm text-slate-400 text-center">{t('desk.emptyQueue')}</p>
          ) : sessions.map(s => (
            <button
              key={s.session_id}
              type="button"
              data-testid={`desk-session-${s.session_id}`}
              onClick={() => setActiveId(s.session_id)}
              className={`w-full text-left px-4 py-3 border-b border-slate-100 hover:bg-teal-50/50 transition-colors ${
                activeId === s.session_id ? 'bg-teal-50 border-l-4 border-l-teal-500' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-mono text-teal-700">{s.agent?.agent_id || '—'}</span>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${statusClass(s.status)}`}>
                  {statusLabel(s.status)}
                </span>
              </div>
              <p className="text-sm font-semibold mt-1 truncate">{s.summary || s.session_id}</p>
              <p className="text-[11px] text-slate-500 mt-0.5">
                {s.user_id} · L{s.emotion_level}
                {s.required_tier === 'supervisor' ? ` · ${t('desk.needSupervisor')}` : ''}
              </p>
            </button>
          ))}
        </aside>

        <main className="col-span-5 min-h-0 flex flex-col bg-slate-50">
          {!activeId ? (
            <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">{t('desk.pickSession')}</div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-slate-200 bg-white flex items-center gap-2 flex-wrap">
                <User className="w-4 h-4 text-slate-400" />
                <span className="text-sm font-bold">{activeId}</span>
                {detail?.assigned_agent && (
                  <span className="text-xs font-mono text-teal-700 ml-auto">
                    {detail.assigned_agent.agent_id} · {detail.assigned_agent.name}
                  </span>
                )}
                {canAccept && (
                  <button
                    type="button"
                    data-testid="desk-accept-handoff"
                    disabled={accepting || (needsSupervisor && !isSupervisor)}
                    onClick={acceptHandoff}
                    className="ml-auto inline-flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-lg bg-teal-600 text-white hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    {accepting ? t('desk.accepting') : t('desk.acceptHandoff')}
                  </button>
                )}
              </div>

              {canAccept && needsSupervisor && !isSupervisor && (
                <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                  {t('desk.supervisorOnlyHint')}
                </div>
              )}

              {canAccept && !needsSupervisor && (
                <div className="px-4 py-2 bg-sky-50 border-b border-sky-200 text-xs text-sky-800">
                  {t('desk.acceptHint')}
                </div>
              )}

              <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3 console-scroll">
                {loading && <p className="text-xs text-slate-400">{t('desk.loading')}</p>}
                {(brief?.conversation_snippet || []).map((m, i) => (
                  <div key={`snip-${i}`} className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                    m.role === 'user' ? 'ml-auto bg-[var(--mitako-purple)] text-white' : 'bg-white border border-slate-200'
                  }`}>
                    <span className="text-[10px] opacity-70 block mb-0.5">
                      {m.role === 'user' ? t('desk.roleUser') : t('desk.roleAi')} · {t('desk.turnLabel', 'zh-CN', { turn: m.turn || i + 1 })}
                    </span>
                    <RichTextContent text={m.content} />
                  </div>
                ))}
                {(detail?.messages || []).map((m, i) => (
                  <div key={`desk-${i}`} className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm border text-slate-800 ${
                    m.role === 'observer' ? 'bg-[#7B61FF]/8 border-[#7B61FF]/20' : 'bg-teal-50 border-teal-200'
                  }`}>
                    <span className="text-[10px] font-bold block mb-0.5 text-teal-700">
                      {m.role === 'observer' ? t('agent.name') : (m.agent_id || detail?.assigned_agent?.agent_id)}
                      {m.role === 'observer' ? ` · ${t('transfer.observerTitle').replace('已成功', '旁听')}` : ''}
                    </span>
                    <RichTextContent text={m.content} />
                  </div>
                ))}
              </div>

              <div className="p-3 border-t border-slate-200 bg-white space-y-2">
                {canChat && (
                  <div className="flex flex-wrap gap-2 items-end p-2 rounded-xl bg-slate-50 border border-slate-200">
                    <div className="flex-1 min-w-[140px]">
                      <label className="text-[10px] font-bold text-slate-500 block mb-1">{t('desk.transferTarget')}</label>
                      <select
                        value={transferTargetId}
                        onChange={e => setTransferTargetId(e.target.value)}
                        className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs bg-white"
                      >
                        <option value="">{t('desk.transferTarget')}</option>
                        {colleagueOptions.map(a => (
                          <option key={a.agent_id} value={a.agent_id}>{a.agent_id} · {a.name}</option>
                        ))}
                      </select>
                    </div>
                    <input
                      value={transferNote}
                      onChange={e => setTransferNote(e.target.value)}
                      placeholder={t('desk.transferNotePlaceholder')}
                      className="flex-1 min-w-[120px] min-h-[36px] rounded-lg border border-slate-200 px-3 text-xs"
                    />
                    <button
                      type="button"
                      disabled={transferring || !transferTargetId}
                      onClick={transferColleague}
                      className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-lg border border-sky-200 text-sky-700 hover:bg-sky-50 disabled:opacity-50"
                    >
                      <Users className="w-3.5 h-3.5" />
                      {transferring ? '…' : t('desk.transferSubmit')}
                    </button>
                  </div>
                )}
                {canChat && selectedAgent?.tier === 'standard' && (
                  <div className="flex gap-2 items-end">
                    <input
                      value={escalateNote}
                      onChange={e => setEscalateNote(e.target.value)}
                      placeholder={t('desk.escalatePlaceholder')}
                      className="flex-1 min-h-[36px] rounded-lg border border-slate-200 px-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-rose-300/40"
                    />
                    <button
                      type="button"
                      disabled={escalating}
                      onClick={escalateHandoff}
                      className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-lg border border-rose-200 text-rose-700 hover:bg-rose-50"
                    >
                      <ArrowUpCircle className="w-3.5 h-3.5" />
                      {escalating ? t('desk.escalating') : t('desk.escalate')}
                    </button>
                  </div>
                )}
                {isTransferring && detail?.pending_agent && (
                  <p className="text-xs text-sky-700 bg-sky-50 rounded-lg px-3 py-2 border border-sky-100">
                    {t('desk.transferPending')}：{detail.pending_agent.agent_id} · {detail.pending_agent.name}
                  </p>
                )}
                {isEscalated && (
                  <p className="text-xs text-rose-700 bg-rose-50 rounded-lg px-3 py-2 border border-rose-100">
                    {detail?.escalation_note || t('desk.escalatedDefault')}
                  </p>
                )}
                <div className="flex gap-2">
                  <input
                    data-testid="desk-reply-input"
                    value={reply}
                    onChange={e => setReply(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), sendReply())}
                    placeholder={canChat ? t('desk.replyPlaceholder') : t('desk.replyBlockedPlaceholder')}
                    disabled={!canChat}
                    className="flex-1 min-h-[44px] rounded-xl border border-slate-200 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 disabled:bg-slate-50 disabled:text-slate-400"
                  />
                  <button
                    type="button"
                    data-testid="desk-reply-send"
                    onClick={sendReply}
                    disabled={!canChat}
                    className="min-w-[44px] h-11 rounded-xl bg-teal-600 text-white flex items-center justify-center hover:bg-teal-700 disabled:opacity-50"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </>
          )}
        </main>

        <aside className="col-span-4 min-h-0 border-l border-slate-200 bg-white overflow-y-auto console-scroll p-4">
          <div className="flex items-center gap-2 mb-3">
            <ClipboardList className="w-4 h-4 text-teal-600" />
            <h2 className="text-sm font-bold">{t('transfer.briefTitle')}</h2>
          </div>
          {!brief ? (
            <p className="text-sm text-slate-400">{t('desk.noBrief')}</p>
          ) : (
            <div className="space-y-4 text-sm">
              <section>
                <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefSummary')}</h3>
                <div className="leading-relaxed"><RichTextContent text={brief.summary} /></div>
              </section>

              <section>
                <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefTrueIntent')}</h3>
                <p className="leading-relaxed text-teal-900 bg-teal-50 rounded-lg px-3 py-2 border border-teal-100">
                  {brief.true_intent || brief.intent}
                </p>
              </section>

              <section>
                <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefDialogue')}</h3>
                <div className="leading-relaxed"><RichTextContent text={brief.ai_dialogue_summary} /></div>
              </section>

              {brief.user_profile && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefProfile')}</h3>
                  <div className="rounded-lg bg-slate-50 border p-3 space-y-2 text-xs">
                    <p><span className="text-slate-400">{t('transfer.profileNickname')}：</span>{brief.user_profile.nickname}</p>
                    <p><span className="text-slate-400">{t('transfer.profileLevel')}：</span>{brief.user_profile.member_level}</p>
                    <p><span className="text-slate-400">{t('transfer.profileRisk')}：</span>{brief.user_profile.risk_level}</p>
                    <p className="leading-relaxed"><span className="text-slate-400">{t('transfer.profilePsych')}：</span>{brief.user_profile.psychological_analysis}</p>
                  </div>
                </section>
              )}

              {(brief.emotion_triggers || []).length > 0 && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefTriggers')}</h3>
                  <ul className="space-y-2">
                    {brief.emotion_triggers.map((tr, i) => (
                      <li key={i} className="text-xs rounded-lg bg-rose-50 border border-rose-100 px-2 py-1.5">
                        <span className="font-bold text-rose-700">「{tr.keyword}」</span>
                        <span className="text-slate-500"> · {t('desk.turnLabel', 'zh-CN', { turn: tr.turn })}</span>
                        <p className="mt-1 text-slate-700 leading-relaxed">{tr.excerpt}</p>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {(brief.recommended_actions || []).length > 0 && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefActions')}</h3>
                  <ol className="list-decimal list-inside space-y-1 text-xs leading-relaxed">
                    {brief.recommended_actions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ol>
                </section>
              )}

              {(brief.orders || []).length > 0 && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefOrders')}</h3>
                  <ul className="space-y-1">{brief.orders.map((o, i) => (
                    <li key={i} className="text-xs font-mono bg-slate-50 rounded-lg px-2 py-1.5 border">{o}</li>
                  ))}</ul>
                </section>
              )}

              <section>
                <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefReason')}</h3>
                <div className="leading-relaxed"><RichTextContent text={brief.transfer_reason_professional || brief.why_ai_cannot_handle || brief.reason} /></div>
              </section>

              <section className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg bg-slate-50 p-2 border">
                  <span className="text-slate-400 block">{t('monitor.intentLabel')}</span>
                  {brief.surface_intent || brief.intent}
                </div>
                <div className="rounded-lg bg-slate-50 p-2 border">
                  <span className="text-slate-400 block">{t('transfer.briefEmotion')}</span>
                  L{brief.emotion_level}
                </div>
              </section>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
