import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, Heart, MessageCircle, Radio, RefreshCw, Search, Shield, Smile, Timer, Users,
} from 'lucide-react';
import { authFetch } from '../lib/authClient.js';
import t from '../i18n/index.js';

const FILTERS = [
  { id: '', labelKey: 'companionObs.filterAll' },
  { id: 'safety', labelKey: 'companionObs.filterSafety' },
  { id: 'negative', labelKey: 'companionObs.filterNegative' },
  { id: 'positive', labelKey: 'companionObs.filterPositive' },
  { id: 'long', labelKey: 'companionObs.filterLong' },
];

const SIDEBAR_TABS = [
  { id: 'users', labelKey: 'companionObs.tabUsers' },
  { id: 'feed', labelKey: 'companionObs.tabFeed' },
];

function formatUserLabel(u) {
  if (!u) return '—';
  const phone = u.phone ? ` · ${u.phone}` : '';
  return `${u.agent_name || u.user_id}${phone}`;
}

/** Companion 可观测后台 — 全局用户总览 + 搜索钻取（非按随机 user_id 运营） */
export default function CompanionObservabilityApp({ authUser }) {
  const [summary, setSummary] = useState(null);
  const [advSummary, setAdvSummary] = useState(null);
  const [dashboardMode, setDashboardMode] = useState('companion');
  const [users, setUsers] = useState([]);
  const [traces, setTraces] = useState([]);
  const [searchInput, setSearchInput] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const [sidebarTab, setSidebarTab] = useState('users');
  const [filter, setFilter] = useState('');
  const [selectedUserId, setSelectedUserId] = useState('');
  const [userDetail, setUserDetail] = useState(null);
  const [activeTraceId, setActiveTraceId] = useState('');
  const [traceDetail, setTraceDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [liveSessions, setLiveSessions] = useState([]);
  const [streamConnected, setStreamConnected] = useState(false);
  const selectedUserIdRef = useRef('');
  const activeTraceIdRef = useRef('');

  useEffect(() => {
    selectedUserIdRef.current = selectedUserId;
  }, [selectedUserId]);

  useEffect(() => {
    activeTraceIdRef.current = activeTraceId;
  }, [activeTraceId]);

  const loadLive = useCallback(async () => {
    const r = await authFetch('/api/v2/companion/observability/live?max_age=300');
    const data = await r.json();
    if (data.ok) {
      setLiveSessions(data.sessions || []);
    }
  }, []);

  const loadSummary = useCallback(async () => {
    const [r1, r2] = await Promise.all([
      authFetch('/api/v2/companion/observability/summary'),
      authFetch('/api/v2/companion/observability/adventure/summary'),
    ]);
    const data1 = await r1.json();
    const data2 = await r2.json();
    if (data1.ok) setSummary(data1.summary);
    if (data2.ok) setAdvSummary(data2.summary);
  }, []);

  const loadUsers = useCallback(async () => {
    const q = searchQ ? `?q=${encodeURIComponent(searchQ)}&limit=80` : '?limit=80';
    const r = await authFetch(`/api/v2/companion/observability/users${q}`);
    const data = await r.json();
    if (data.ok) setUsers(data.users || []);
  }, [searchQ]);

  const loadTraces = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '60' });
      if (filter) params.set('filter', filter);
      if (searchQ) params.set('q', searchQ);
      if (selectedUserId) params.set('user_id', selectedUserId);
      if (dashboardMode === 'adventure') params.set('agent_mode', 'adventure');
      else params.set('agent_mode', 'companion');
      const r = await authFetch(`/api/v2/companion/observability/traces?${params}`);
      const data = await r.json();
      if (data.ok) setTraces(data.traces || []);
    } finally {
      setLoading(false);
    }
  }, [filter, searchQ, selectedUserId, dashboardMode]);

  const loadUserDetail = useCallback(async (userId) => {
    if (!userId) {
      setUserDetail(null);
      return;
    }
    setSelectedUserId(userId);
    setActiveTraceId('');
    setTraceDetail(null);
    const r = await authFetch(`/api/v2/companion/observability/users/${encodeURIComponent(userId)}`);
    const data = await r.json();
    if (data.ok) setUserDetail(data);
  }, []);

  const loadTraceDetail = useCallback(async (turnId) => {
    if (!turnId) return;
    setActiveTraceId(turnId);
    const r = await authFetch(`/api/v2/companion/observability/traces/${encodeURIComponent(turnId)}`);
    const data = await r.json();
    if (data.ok) setTraceDetail(data);
  }, []);

  const refreshAll = useCallback(() => {
    loadSummary();
    loadUsers();
    loadTraces();
    loadLive();
    if (selectedUserId) loadUserDetail(selectedUserId);
    if (activeTraceId) loadTraceDetail(activeTraceId);
  }, [loadSummary, loadUsers, loadTraces, loadLive, loadUserDetail, loadTraceDetail, selectedUserId, activeTraceId]);

  useEffect(() => {
    loadSummary();
    loadUsers();
    loadLive();
  }, [loadSummary, loadUsers, loadLive]);

  useEffect(() => {
    loadTraces();
  }, [loadTraces]);

  // 观测台 SSE — 有重要事件时才刷新，不做定时轮询
  useEffect(() => {
    const controller = new AbortController();
    let buffer = '';

    const processBlock = (block) => {
      block = block.trim();
      if (!block) return;
      let eventType = 'message';
      let dataStr = '';
      for (const line of block.split('\n')) {
        const trimmed = line.trim();
        if (trimmed.startsWith('event:')) eventType = trimmed.substring(6).trim();
        else if (trimmed.startsWith('data:')) dataStr = trimmed.substring(5).trim();
      }
      if (!dataStr || eventType === 'heartbeat' || eventType === 'connected') {
        if (eventType === 'connected') setStreamConnected(true);
        return;
      }
      let payload = {};
      try {
        payload = JSON.parse(dataStr);
      } catch {
        return;
      }

      if (eventType === 'live_update') {
        loadLive();
        return;
      }
      if (eventType === 'turn_complete') {
        loadLive();
        loadTraces();
        loadSummary();
        loadUsers();
        if (payload.user_id && payload.user_id === selectedUserIdRef.current) {
          loadUserDetail(payload.user_id);
        }
        return;
      }
      if (eventType === 'safety_alert') {
        loadLive();
        loadTraces();
        loadSummary();
        loadUsers();
        if (payload.user_id && payload.user_id === selectedUserIdRef.current) {
          loadUserDetail(payload.user_id);
        }
        if (payload.turn_id && payload.turn_id === activeTraceIdRef.current) {
          loadTraceDetail(payload.turn_id);
        }
        return;
      }
      if (eventType === 'memory_update') {
        loadUsers();
        if (payload.user_id && payload.user_id === selectedUserIdRef.current) {
          loadUserDetail(payload.user_id);
        }
      }
    };

    (async () => {
      try {
        const res = await authFetch('/api/v2/companion/observability/stream', { signal: controller.signal });
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split(/\r?\n\r?\n/);
          buffer = blocks.pop() || '';
          for (const block of blocks) processBlock(block);
        }
        if (buffer.trim()) processBlock(buffer);
      } catch (e) {
        if (e?.name !== 'AbortError') console.error('obs stream error', e);
      } finally {
        setStreamConnected(false);
      }
    })();

    return () => controller.abort();
  }, [loadLive, loadTraces, loadSummary, loadUsers, loadUserDetail, loadTraceDetail]);

  const submitSearch = (e) => {
    e.preventDefault();
    setSearchQ(searchInput.trim());
    setSelectedUserId('');
    setUserDetail(null);
    setActiveTraceId('');
    setTraceDetail(null);
  };

  const clearUserSelection = () => {
    setSelectedUserId('');
    setUserDetail(null);
    setActiveTraceId('');
    setTraceDetail(null);
  };

  const cards = dashboardMode === 'adventure'
    ? [
      { icon: MessageCircle, label: t('companionObs.advKpiTurns'), value: advSummary?.total_turns ?? '—', tone: 'text-violet-800' },
      { icon: Activity, label: t('companionObs.advKpiUsage'), value: advSummary?.usage_rate_pct != null ? `${advSummary.usage_rate_pct}%` : '—', tone: 'text-fuchsia-700' },
      { icon: Shield, label: t('companionObs.advKpiStability'), value: advSummary?.stability_score != null ? `${advSummary.stability_score}` : '—', tone: 'text-emerald-600' },
      { icon: Smile, label: t('companionObs.advKpiSatisfaction'), value: advSummary?.satisfaction_proxy ?? '—', tone: 'text-amber-600' },
      { icon: Timer, label: t('companionObs.advKpiDuration'), value: advSummary?.total_duration_min ?? '—', tone: 'text-cyan-700' },
      { icon: Heart, label: t('companionObs.advKpiCost'), value: advSummary?.cost_est_usd ?? '—', tone: 'text-rose-600' },
    ]
    : [
      { icon: MessageCircle, label: t('companionObs.kpiTurns'), value: summary?.total_turns ?? '—', tone: 'text-slate-800' },
      { icon: Shield, label: t('companionObs.kpiSafety'), value: summary?.safety_flags ?? '—', tone: 'text-rose-600' },
      { icon: AlertTriangle, label: t('companionObs.kpiNegative'), value: summary?.negative_emotion ?? '—', tone: 'text-amber-600' },
      { icon: Smile, label: t('companionObs.kpiPositive'), value: summary?.positive_emotion ?? '—', tone: 'text-emerald-600' },
      { icon: Timer, label: t('companionObs.kpiLong'), value: summary?.long_conversations ?? '—', tone: 'text-fuchsia-600' },
      { icon: Heart, label: t('companionObs.kpiUsers'), value: summary?.active_users ?? '—', tone: 'text-[var(--mitako-purple)]' },
    ];

  const trace = traceDetail?.trace;
  const traceMsgs = traceDetail?.messages || [];
  const userPersona = userDetail?.persona;
  const userTraces = userDetail?.traces || [];
  const userMsgs = userDetail?.messages || [];

  return (
    <div className="min-h-[100dvh] flex flex-col bg-gradient-to-br from-rose-50 via-white to-purple-50 text-slate-800">
      <header className="border-b border-rose-100 bg-white/80 backdrop-blur px-4 md:px-6 py-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold text-rose-600 uppercase">{t('companionObs.badge')}</p>
          <h1 className="text-xl font-bold">{t('companionObs.title')}</h1>
          <p className="text-xs text-slate-500">{t('companionObs.subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="px-2 py-1 rounded-lg bg-rose-50 border border-rose-100">{authUser?.username || 'ops'}</span>
          <button type="button" onClick={refreshAll} className="p-2 rounded-lg hover:bg-rose-50" aria-label={t('companionObs.refresh')}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <a href="/companion" target="_blank" rel="noopener noreferrer" className="text-rose-600 font-semibold">{t('companionObs.openCompanion')}</a>
        </div>
      </header>

      <div className="px-4 md:px-6 py-3">
        <form onSubmit={submitSearch} className="flex gap-2 max-w-2xl">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder={t('companionObs.searchPlaceholder')}
              className="w-full rounded-xl border border-rose-100 bg-white pl-9 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-rose-200"
            />
          </div>
          <button type="submit" className="rounded-xl bg-rose-600 text-white font-bold px-4 py-2.5 text-sm">{t('companionObs.searchBtn')}</button>
          {(searchQ || selectedUserId) && (
            <button type="button" onClick={() => { setSearchInput(''); setSearchQ(''); clearUserSelection(); }} className="rounded-xl border border-rose-100 bg-white px-3 py-2.5 text-sm text-slate-500">
              {t('companionObs.clearSearch')}
            </button>
          )}
        </form>
        {searchQ && <p className="text-[11px] text-slate-400 mt-1">{t('companionObs.searchHint')} · {searchQ}</p>}
      </div>

      <section className="px-4 md:px-6 pb-3">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h2 className="text-xs font-bold text-rose-600 uppercase flex items-center gap-1.5">
            <Radio className="w-3.5 h-3.5 animate-pulse" />
            {t('companionObs.liveTitle')}
          </h2>
          <span className="text-[10px] text-slate-400">
            {streamConnected ? t('companionObs.liveEventDriven') : t('companionObs.liveConnecting')}
          </span>
        </div>
        {liveSessions.length === 0 ? (
          <p className="text-xs text-slate-400 rounded-xl border border-dashed border-rose-100 bg-white/60 px-4 py-3">
            {t('companionObs.liveEmpty')}
          </p>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-1 snap-x">
            {liveSessions.map(sess => (
              <button
                key={sess.user_id}
                type="button"
                onClick={() => loadUserDetail(sess.user_id)}
                className={`min-w-[220px] snap-start text-left rounded-2xl border p-3 transition-colors ${
                  sess.status === 'streaming'
                    ? 'border-rose-400 bg-rose-50 shadow-sm shadow-rose-100'
                    : 'border-rose-100 bg-white hover:bg-rose-50/40'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-bold text-slate-800 truncate">{sess.agent_name || sess.user_id}</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full shrink-0 ${
                    sess.status === 'streaming' ? 'bg-rose-600 text-white animate-pulse' : 'bg-slate-100 text-slate-500'
                  }`}>
                    {sess.status === 'streaming' ? t('companionObs.liveStreaming') : t('companionObs.liveIdle')}
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 mt-0.5 truncate">{sess.phone || sess.user_id}</p>
                <div className="flex flex-wrap gap-2 mt-2 text-[10px]">
                  <span className="px-1.5 py-0.5 rounded bg-fuchsia-100 text-fuchsia-800 font-bold">
                    L{sess.emotion_level} {sess.emotion_label}
                  </span>
                  <span className="text-slate-400">{t('companionObs.liveMsgCount', 'zh-CN', { n: sess.message_count || 0 })}</span>
                  <span className="text-slate-400">{t('companionObs.liveTurnCount', 'zh-CN', { n: sess.turn_count || 0 })}</span>
                </div>
                <p className="text-xs text-slate-600 mt-2 line-clamp-2">{sess.last_user_snippet || '—'}</p>
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="px-4 md:px-6 pb-2 flex flex-wrap gap-2">
        {[
          { id: 'companion', label: t('companionObs.dashCompanion') },
          { id: 'adventure', label: t('companionObs.dashAdventure') },
        ].map(tab => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setDashboardMode(tab.id)}
            className={`rounded-full px-4 py-1.5 text-xs font-bold border transition-colors ${
              dashboardMode === tab.id
                ? tab.id === 'adventure'
                  ? 'bg-violet-600 text-white border-violet-600'
                  : 'bg-rose-600 text-white border-rose-600'
                : 'bg-white text-slate-600 border-rose-100 hover:bg-rose-50'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="px-4 md:px-6 py-2 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {cards.map(({ icon: Icon, label, value, tone }) => (
          <div key={label} className="glass-panel p-3">
            <Icon className={`w-4 h-4 mb-1 ${tone}`} />
            <p className="text-[10px] text-slate-400 font-semibold uppercase">{label}</p>
            <p className={`text-2xl font-bold ${tone}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className="flex-1 min-h-0 flex flex-col md:flex-row gap-0 md:gap-4 px-4 md:px-6 pb-4">
        <aside className="md:w-[22rem] lg:w-96 flex flex-col min-h-0 glass-panel overflow-hidden">
          <div className="p-2 border-b border-rose-100 flex gap-1">
            {SIDEBAR_TABS.map(tab => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setSidebarTab(tab.id)}
                className={`flex-1 text-[11px] font-bold py-2 rounded-lg ${
                  sidebarTab === tab.id ? 'bg-rose-600 text-white' : 'bg-white text-slate-500 border border-rose-100'
                }`}
              >
                {t(tab.labelKey)}
              </button>
            ))}
          </div>

          {sidebarTab === 'feed' && (
            <div className="p-2 border-b border-rose-100 flex flex-wrap gap-1">
              {FILTERS.map(f => (
                <button
                  key={f.id || 'all'}
                  type="button"
                  onClick={() => setFilter(f.id)}
                  className={`text-[10px] font-bold px-2 py-1 rounded-full border ${
                    filter === f.id ? 'bg-rose-600 text-white border-rose-600' : 'bg-white text-slate-500 border-rose-100'
                  }`}
                >
                  {t(f.labelKey)}
                </button>
              ))}
            </div>
          )}

          <div className="flex-1 overflow-auto p-2 space-y-2">
            {sidebarTab === 'users' && (
              <>
                {users.length === 0 && <p className="text-xs text-slate-400 p-4 text-center">{t('companionObs.emptyUsers')}</p>}
                {users.map(u => (
                  <button
                    key={u.user_id}
                    type="button"
                    onClick={() => loadUserDetail(u.user_id)}
                    className={`w-full text-left rounded-xl p-3 border transition-colors ${
                      selectedUserId === u.user_id ? 'border-rose-400 bg-rose-50' : 'border-rose-100 bg-white hover:bg-rose-50/50'
                    }`}
                  >
                    <div className="flex justify-between items-start gap-2">
                      <span className="text-sm font-bold text-slate-800 truncate">{u.agent_name || t('companionObs.unnamedAgent')}</span>
                      {u.safety_count > 0 && (
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-100 text-rose-700">{u.safety_count}</span>
                      )}
                    </div>
                    <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                      {u.phone || t('companionObs.noPhone')} · {u.user_id}
                    </p>
                    <div className="flex gap-2 mt-2 text-[10px] text-slate-400">
                      <span>{t('companionObs.turnCount', 'zh-CN', { n: u.turn_count || 0 })}</span>
                      {u.last_emotion_label && <span>L{u.last_emotion_level} {u.last_emotion_label}</span>}
                    </div>
                  </button>
                ))}
              </>
            )}

            {sidebarTab === 'feed' && (
              <>
                {traces.length === 0 && <p className="text-xs text-slate-400 p-4 text-center">{t('companionObs.empty')}</p>}
                {traces.map(tr => (
                  <button
                    key={tr.turn_id}
                    type="button"
                    onClick={() => loadTraceDetail(tr.turn_id)}
                    className={`w-full text-left rounded-xl p-3 border transition-colors ${
                      activeTraceId === tr.turn_id ? 'border-rose-400 bg-rose-50' : 'border-rose-100 bg-white hover:bg-rose-50/50'
                    }`}
                  >
                    <div className="flex justify-between items-start gap-2">
                      <span className="text-xs font-semibold text-slate-700 truncate">{formatUserLabel(tr)}</span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${
                        tr.safety_status !== 'pass' ? 'bg-rose-100 text-rose-700' : 'bg-slate-100 text-slate-500'
                      }`}>
                        {tr.safety_status}
                      </span>
                    </div>
                    <p className="text-sm font-medium mt-1 line-clamp-2">{tr.user_message}</p>
                    <div className="flex gap-2 mt-2 text-[10px] text-slate-400">
                      <span>L{tr.emotion_level} {tr.emotion_label}</span>
                      <span>{Math.round(tr.duration_ms || 0)}ms</span>
                    </div>
                  </button>
                ))}
              </>
            )}
          </div>
        </aside>

        <main className="flex-1 min-h-0 glass-panel flex flex-col overflow-hidden mt-3 md:mt-0">
          {trace ? (
            <>
              <div className="p-4 border-b border-rose-100 flex flex-wrap gap-2 items-center">
                <button type="button" onClick={() => { setActiveTraceId(''); setTraceDetail(null); }} className="text-xs text-rose-600 font-semibold">{t('companionObs.backToGlobal')}</button>
                <span className="text-xs font-mono bg-white border rounded-lg px-2 py-1">{trace.turn_id}</span>
                <span className="text-xs px-2 py-1 rounded-full bg-fuchsia-100 text-fuchsia-800">{trace.emotion_label} · L{trace.emotion_level}</span>
                {trace.safety_status !== 'pass' && (
                  <span className="text-xs px-2 py-1 rounded-full bg-rose-100 text-rose-800">{t('companionObs.safety')} · {trace.safety_reason}</span>
                )}
              </div>
              <div className="flex-1 min-h-0 grid md:grid-cols-2 gap-0 overflow-hidden">
                <div className="border-b md:border-b-0 md:border-r border-rose-100 p-4 overflow-auto space-y-2">
                  <h3 className="text-xs font-bold text-slate-500 uppercase">{t('companionObs.conversation')}</h3>
                  {traceMsgs.slice(-20).map(m => (
                    <div key={m.id} className={`text-sm rounded-xl px-3 py-2 max-w-[95%] ${
                      m.role === 'user' ? 'ml-auto bg-rose-100 text-rose-900' : 'mr-auto bg-white border border-rose-50'
                    }`}>
                      {m.content}
                    </div>
                  ))}
                </div>
                <div className="p-4 overflow-auto space-y-3">
                  <h3 className="text-xs font-bold text-slate-500 uppercase flex items-center gap-1">
                    <Activity className="w-3.5 h-3.5" /> LangGraph {t('companionObs.trace')}
                  </h3>
                  {(trace.graph_trace || []).map((ev, i) => (
                    <div key={i} className="text-xs font-mono border-l-2 border-[var(--mitako-purple)] pl-2">
                      <span className="font-bold text-[var(--mitako-purple)]">[{ev.status}] {ev.node}</span>
                      <span className="text-slate-600 ml-1">{ev.desc}</span>
                    </div>
                  ))}
                  <h3 className="text-xs font-bold text-slate-500 uppercase pt-2">{t('companionObs.apiLog')}</h3>
                  <pre className="text-[11px] bg-slate-950 text-slate-100 p-3 rounded-xl overflow-auto max-h-48">
                    {JSON.stringify(trace.api_log || {}, null, 2)}
                  </pre>
                </div>
              </div>
            </>
          ) : userDetail ? (
            <>
              <div className="p-4 border-b border-rose-100 flex flex-wrap gap-2 items-center justify-between">
                <div>
                  <p className="text-lg font-bold text-slate-800">{userPersona?.agent_name}</p>
                  <p className="text-xs text-slate-500">
                    {userPersona?.phone || t('companionObs.noPhone')} · {userPersona?.user_id} · {userPersona?.user_title}
                  </p>
                </div>
                <button type="button" onClick={clearUserSelection} className="text-xs text-rose-600 font-semibold">{t('companionObs.backToGlobal')}</button>
              </div>
              <div className="flex-1 min-h-0 grid md:grid-cols-2 gap-0 overflow-hidden">
                <div className="border-b md:border-b-0 md:border-r border-rose-100 p-4 overflow-auto space-y-2">
                  <h3 className="text-xs font-bold text-slate-500 uppercase">{t('companionObs.userConversation')}</h3>
                  {userMsgs.slice(-24).map(m => (
                    <div key={m.id} className={`text-sm rounded-xl px-3 py-2 max-w-[95%] ${
                      m.role === 'user' ? 'ml-auto bg-rose-100 text-rose-900' : 'mr-auto bg-white border border-rose-50'
                    }`}>
                      {m.content}
                    </div>
                  ))}
                </div>
                <div className="p-4 overflow-auto space-y-2">
                  <h3 className="text-xs font-bold text-slate-500 uppercase">{t('companionObs.userTraces')}</h3>
                  {userTraces.map(tr => (
                    <button
                      key={tr.turn_id}
                      type="button"
                      onClick={() => loadTraceDetail(tr.turn_id)}
                      className="w-full text-left rounded-xl p-3 border border-rose-100 bg-white hover:bg-rose-50/50"
                    >
                      <p className="text-sm line-clamp-2">{tr.user_message}</p>
                      <p className="text-[10px] text-slate-400 mt-1">L{tr.emotion_level} {tr.emotion_label} · {tr.safety_status}</p>
                    </button>
                  ))}
                  {(userDetail?.memories || []).length > 0 && (
                    <>
                      <h3 className="text-xs font-bold text-slate-500 uppercase pt-3">{t('companionObs.userMemories')}</h3>
                      {(userDetail.memories || []).slice(0, 8).map(m => (
                        <div key={m.id || m.fingerprint} className="rounded-xl p-3 border border-violet-100 bg-violet-50/40 text-xs">
                          <span className="font-bold text-violet-700">{m.category}/{m.memory_key}</span>
                          <p className="text-slate-700 mt-1">{m.memory_value}</p>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 overflow-auto p-6 space-y-6">
              <div className="text-center max-w-lg mx-auto">
                <Users className="w-10 h-10 mx-auto text-rose-300 mb-3" />
                <h2 className="text-lg font-bold text-slate-800">{t('companionObs.globalTitle')}</h2>
                <p className="text-sm text-slate-500 mt-2">{t('companionObs.globalHint')}</p>
              </div>
              <div className="grid md:grid-cols-2 gap-4">
                <div className="rounded-2xl border border-rose-100 bg-white p-4">
                  <h3 className="text-xs font-bold text-slate-500 uppercase mb-3">{t('companionObs.recentSafety')}</h3>
                  {(traces.filter(tr => tr.safety_status !== 'pass').slice(0, 5)).length === 0 ? (
                    <p className="text-xs text-slate-400">{t('companionObs.noAlerts')}</p>
                  ) : (
                    traces.filter(tr => tr.safety_status !== 'pass').slice(0, 5).map(tr => (
                      <button key={tr.turn_id} type="button" onClick={() => loadTraceDetail(tr.turn_id)} className="block w-full text-left py-2 border-b border-rose-50 last:border-0">
                        <span className="text-xs font-semibold text-rose-700">{formatUserLabel(tr)}</span>
                        <p className="text-xs text-slate-600 line-clamp-1">{tr.user_message}</p>
                      </button>
                    ))
                  )}
                </div>
                <div className="rounded-2xl border border-rose-100 bg-white p-4">
                  <h3 className="text-xs font-bold text-slate-500 uppercase mb-3">{t('companionObs.topUsers')}</h3>
                  {users.slice(0, 6).map(u => (
                    <button key={u.user_id} type="button" onClick={() => loadUserDetail(u.user_id)} className="flex w-full items-center justify-between py-2 border-b border-rose-50 last:border-0 text-left">
                      <span className="text-sm font-medium text-slate-800">{u.agent_name}</span>
                      <span className="text-[10px] text-slate-400">{u.turn_count || 0} 轮</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
