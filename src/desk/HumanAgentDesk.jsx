import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Headphones, RefreshCw, Send, User, ClipboardList, CheckCircle2, ArrowUpCircle, AlertTriangle, Users, SmilePlus, Search, Image as ImageIcon } from 'lucide-react';
import t from '../i18n/index.js';
import RichTextContent from '../components/shared/RichTextContent.jsx';
import { authFetch, getAuthToken } from '../lib/authClient.js';
import { attachHandoffTransport } from '../hooks/useHandoffSync.js';
import { sanitizePublicText } from '../utils/publicText.js';

function formatAttachmentSize(size = 0) {
  const n = Number(size || 0);
  if (!Number.isFinite(n) || n <= 0) return '';
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

function DeskAttachmentPreview({ attachment }) {
  const [src, setSrc] = useState('');
  useEffect(() => {
    let alive = true;
    let objectUrl = '';
    const load = async () => {
      if (!attachment?.url) return;
      try {
        const res = await authFetch(attachment.url);
        if (!res.ok) return;
        const blob = await res.blob();
        objectUrl = URL.createObjectURL(blob);
        if (alive) setSrc(objectUrl);
      } catch (e) {
        console.error('desk attachment preview failed:', e);
      }
    };
    load();
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment?.url]);

  return (
    <div className="mt-2 flex max-w-[280px] items-center gap-2 rounded-[8px] border border-slate-200 bg-white p-2 shadow-[0_8px_18px_rgba(16,19,31,0.06)]">
      {src ? (
        <img src={src} alt={attachment?.name || '用户上传图片'} className="h-14 w-14 rounded-[7px] object-cover" />
      ) : (
        <div className="flex h-14 w-14 items-center justify-center rounded-[7px] bg-slate-100 text-slate-500">
          <ImageIcon className="h-5 w-5" aria-hidden="true" />
        </div>
      )}
      <div className="min-w-0">
        <p className="truncate text-xs font-black text-slate-950">{sanitizePublicText(attachment?.name || '用户上传图片')}</p>
        <p className="mt-0.5 text-[10px] font-semibold text-slate-500">
          已接收 · {sanitizePublicText(attachment?.mime_type || '图片')} {formatAttachmentSize(attachment?.size)}
        </p>
      </div>
    </div>
  );
}

function DeskAttachmentList({ attachments = [] }) {
  const items = Array.isArray(attachments) ? attachments.filter(Boolean) : [];
  if (!items.length) return null;
  return <div>{items.map((item, index) => <DeskAttachmentPreview key={item.id || `${item.name || 'attachment'}-${index}`} attachment={item} />)}</div>;
}

/** PC 端 VIP客服工作台 — 独立入口 /desk */
export default function HumanAgentDesk({ authUser = null }) {
  const [sessions, setSessions] = useState([]);
  const [agents, setAgents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [activeId, setActiveId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [reply, setReply] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [acceptConfirmOpen, setAcceptConfirmOpen] = useState(false);
  const [replying, setReplying] = useState(false);
  const [escalating, setEscalating] = useState(false);
  const [escalateNote, setEscalateNote] = useState('');
  const [transferTargetId, setTransferTargetId] = useState('');
  const [transferNote, setTransferNote] = useState('');
  const [transferring, setTransferring] = useState(false);
  const [closing, setClosing] = useState(false);
  const [closeNote, setCloseNote] = useState('');
  const [notice, setNotice] = useState('');
  const [mobileView, setMobileView] = useState('queue');

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

  const refreshAll = useCallback(async () => {
    setRefreshing(true);
    setNotice('');
    try {
      await Promise.all([loadSessions(), loadAgents()]);
      if (activeId) await loadDetail(activeId);
      setNotice('队列已刷新');
    } catch (e) {
      console.error(e);
      setNotice('刷新失败，请稍后再试');
    } finally {
      setRefreshing(false);
    }
  }, [activeId, loadAgents, loadDetail, loadSessions]);

  useEffect(() => {
    loadAgents();
    loadSessions();
    const timer = setInterval(loadSessions, 8000);
    return () => clearInterval(timer);
  }, [loadAgents, loadSessions]);

  useEffect(() => {
    if (authUser?.agent_id) {
      setSelectedAgentId(authUser.agent_id);
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
      authValue: getAuthToken(),
    });
    return () => {
      clearInterval(timer);
      detach();
    };
  }, [activeId, loadDetail, loadSessions]);

  const lockedAgentId = authUser?.agent_id || '';
  const effectiveAgentId = lockedAgentId || selectedAgentId;
  const selectedAgent = useMemo(
    () => agents.find(a => a.agent_id === effectiveAgentId) || null,
    [agents, effectiveAgentId],
  );

  const acceptHandoff = async () => {
    if (!activeId || !effectiveAgentId || !acceptAllowed) return;
    setAccepting(true);
    try {
      const r = await authFetch(`/api/v1/desk/session/${encodeURIComponent(activeId)}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: effectiveAgentId }),
      });
      const data = await r.json();
      if (!data.ok) {
        window.alert(data.message || data.error || t('desk.acceptFailed'));
        return;
      }
      setAcceptConfirmOpen(false);
      setNotice('已接手该会话，可以回复用户或继续处理服务动作。');
      setMobileView('chat');
      loadDetail(activeId);
      loadSessions();
    } catch (e) {
      console.error(e);
      window.alert('接手失败，请检查网络后重试');
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
        body: JSON.stringify({ note: escalateNote.trim(), agent_id: detail?.assigned_agent?.agent_id || selectedAgentId }),
      });
      const data = await r.json();
      if (data.ok) {
        setEscalateNote('');
        setNotice('已升级到高级客服/专项处理队列。');
        loadDetail(activeId);
        loadSessions();
      } else {
        window.alert(data.message || data.error || '升级失败，请刷新后重试');
      }
    } catch (e) {
      console.error(e);
      window.alert('升级失败，请检查网络后重试');
    } finally {
      setEscalating(false);
    }
  };

  const transferColleague = async () => {
    if (!activeId || !transferTargetId) return;
    setTransferring(true);
    try {
      const fromId = detail?.assigned_agent?.agent_id || effectiveAgentId;
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
      setNotice(data.message || '已发起转交，等待同事确认接管。');
      setTransferNote('');
      loadDetail(activeId);
      loadSessions();
    } catch (e) {
      console.error(e);
      window.alert('转交失败，请检查网络后重试');
    } finally {
      setTransferring(false);
    }
  };

  const sendReply = async () => {
    if (!activeId || !reply.trim() || !detail?.can_chat || replying) return;
    const agentId = detail?.assigned_agent?.agent_id || effectiveAgentId;
    setReplying(true);
    try {
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
    } catch (e) {
      console.error(e);
      window.alert('发送失败，请检查网络后重试');
    } finally {
      setReplying(false);
    }
  };

  const closeSession = async () => {
    if (!activeId || closing) return;
    const note = closeNote.trim() || '本次服务已处理完成';
    if (!window.confirm(`确认结案？结案说明：${note}`)) return;
    setClosing(true);
    try {
      const params = new URLSearchParams({ session_id: activeId, note });
      const r = await authFetch(`/api/v1/handoff/close?${params.toString()}`, { method: 'POST' });
      const data = await r.json();
      if (!data.ok) {
        window.alert(data.message || data.error || '结案失败，请刷新后重试');
        return;
      }
      setNotice('会话已结案，服务记录已归档。');
      setCloseNote('');
      await loadSessions();
      await loadDetail(activeId);
    } catch (e) {
      console.error(e);
      window.alert('结案失败，请检查网络后重试');
    } finally {
      setClosing(false);
    }
  };

  const brief = detail?.brief;
  const sopState = brief?.sop_state || {};
  const sopChecklist = sopState.checklist || [];
  const businessEvents = detail?.business_events || [];
  const visibleBusinessEvents = businessEvents.filter(ev => String(ev.event_type || '').startsWith('service_') || ev.event_type === 'sop_branch' || ev.event_type === 'material_review');
  const latestBusinessAction = visibleBusinessEvents.find(ev => String(ev.event_type || '').startsWith('service_') && ev.event_type !== 'service_qc_sop_proposal');
  const qcEvent = visibleBusinessEvents.find(ev => ev.event_type === 'service_qc_sop_proposal');
  const canAccept = detail?.can_accept;
  const canChat = detail?.can_chat;
  const isEscalated = detail?.status === 'escalated';
  const needsSupervisor = detail?.required_tier === 'supervisor';
  const isTransferring = detail?.status === 'transferring';
  const isSupervisor = selectedAgent?.tier === 'supervisor';
  const assignedGateAgent = detail?.pending_agent || detail?.assigned_agent || null;
  const assignedGateId = assignedGateAgent?.agent_id || '';
  const assignedGateName = assignedGateAgent?.name || '';
  const agentMatchesAssignment = !assignedGateId || assignedGateId === effectiveAgentId;
  const tierAllowed = !needsSupervisor || isSupervisor;
  const acceptBlockedReason = (() => {
    if (!canAccept) return '';
    if (!effectiveAgentId) return '请先确认当前客服身份。';
    if (!tierAllowed) return '该会话需要高级客服或专项客服接手，请切换到对应身份。';
    if (!agentMatchesAssignment) return `该会话当前分配给${assignedGateName || assignedGateId}，当前身份不可接手；请切换身份或由主管转派。`;
    return '';
  })();
  const acceptAllowed = Boolean(canAccept && !acceptBlockedReason);
  const colleagueOptions = useMemo(
    () => agents.filter((a) => {
      if (a.agent_id === (detail?.assigned_agent?.agent_id || effectiveAgentId)) return false;
      if (detail?.required_tier === 'supervisor' && a.tier !== 'supervisor') return false;
      return true;
    }),
    [agents, detail?.assigned_agent, detail?.required_tier, effectiveAgentId],
  );
  const transferTarget = useMemo(
    () => agents.find(a => a.agent_id === transferTargetId) || null,
    [agents, transferTargetId],
  );
  const safeDeskText = (value) => sanitizePublicText(value);
  const quickReplies = useMemo(() => {
    const actions = Array.isArray(brief?.recommended_actions) ? brief.recommended_actions : [];
    const base = [
      '我已经看到您的反馈了，会先帮您核对订单、物流和售后规则，再给您一个明确处理方向。',
      '为了避免误判，请您再补充一张清晰的商品整体图和问题部位近景，我会一起提交复核。',
      '这类问题需要结合订单状态和仓库记录确认，我先为您记录并推进VIP客服复核。',
      '您现在的着急我能理解，我会按当前证据先处理能确认的部分，不能确认的部分会明确告诉您还差什么材料。',
    ];
    return [...actions, ...base].map(item => safeDeskText(item)).filter(Boolean).slice(0, 6);
  }, [brief?.recommended_actions]);
  const emojiReplies = ['收到，我来核对', '辛苦补充一下', '已记录', '我理解您的着急'];
  const appendReplyText = (text) => {
    setReply(prev => {
      const prefix = prev.trim() ? `${prev.trim()} ` : '';
      return `${prefix}${safeDeskText(text)}`.trim();
    });
  };
  const businessEventLabel = (type) => ({
    sop_branch: '服务类型识别',
    service_transfer_blocked: 'VIP客服接手留痕',
    service_after_sales_card: '售后处理单',
    service_warehouse_task: '仓库核查任务',
    service_product_info: '商品信息核对',
    service_ticket: '客服复核工单',
    service_qc_sop_proposal: '质检建议',
    service_private_domain_task: '后续跟进任务',
  }[type] || '业务处理记录');
  const businessStatusLabel = (status) => ({
    service_only: '已记录',
    planned: '已规划',
    drafted: '已生成',
    matched: '已匹配',
    ready_for_dispatch: '待派发',
    ready_for_human_review: '待复核',
  }[status] || sanitizePublicText(status) || '已记录');
  const businessRefLabel = (value) => {
    const raw = safeDeskText(value);
    if (!raw || raw === '-') return t('desk.currentService');
    const compact = String(raw).replace(/[^a-zA-Z0-9]/g, '');
    const code = (compact || String(raw)).slice(-6).toUpperCase();
    return t('desk.businessRef', 'zh-CN', { code });
  };

  const statusLabel = (status) => {
    if (status === 'connected') return t('desk.statusConnected');
    if (status === 'escalated') return t('desk.statusEscalated');
    if (status === 'transferring') return t('desk.transferPending');
    return t('desk.statusQueuing');
  };

  const formatDuration = (seconds = 0) => {
    const sec = Math.max(0, Number(seconds) || 0);
    const minutes = Math.floor(sec / 60);
    if (minutes < 1) return '刚刚入队';
    if (minutes < 60) return `已等 ${minutes} 分钟`;
    return `已等 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`;
  };

  const statusClass = (status) => {
    if (status === 'connected') return 'bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-[var(--mitako-ink)]';
    if (status === 'escalated') return 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]';
    if (status === 'transferring') return 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]';
    return 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]';
  };
  const speakerLabel = (m) => {
    if (m.role === 'user') return t('desk.roleUser');
    if (m.role === 'assistant') return t('desk.roleAi');
    if (m.role === 'human') {
      const agent = agents.find(a => a.agent_id === m.agent_id);
      return agent?.name || detail?.assigned_agent?.name || t('speakers.humanName');
    }
    if (m.role === 'observer') return t('agent.name');
    return '系统';
  };
  const messageBubbleClass = (role) => {
    if (role === 'user') return 'ml-auto bg-[var(--mitako-lime)] border-[var(--mitako-ink)] text-[var(--mitako-ink)]';
    if (role === 'human') return 'ml-auto bg-white border-[var(--mitako-ink)] text-[var(--mitako-ink)]';
    if (role === 'system') return 'mx-auto bg-slate-50 border-slate-200 text-slate-600';
    return 'bg-white border-slate-200 text-[var(--mitako-ink)]';
  };

  return (
    <div className="mitako-ppt-scope min-h-[100dvh] bg-white text-slate-800 flex flex-col overflow-hidden">
      <header className="flex-shrink-0 px-4 sm:px-6 py-4 bg-white/95 backdrop-blur border-b border-slate-200 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-[8px] border border-slate-200 bg-[var(--mitako-lime-soft)] shadow-[0_10px_24px_rgba(127,164,49,.18)] flex items-center justify-center text-[var(--mitako-ink)]">
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
              value={effectiveAgentId}
              onChange={e => setSelectedAgentId(e.target.value)}
              disabled={Boolean(lockedAgentId)}
              className="rounded-[8px] border border-slate-200 px-2 py-1.5 text-xs bg-white min-w-[180px]"
            >
              {(lockedAgentId ? agents.filter(a => a.agent_id === lockedAgentId) : agents).map(a => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.name} · {a.tier === 'supervisor' ? t('desk.tierSupervisor') : t('desk.tierStandard')}
                </option>
              ))}
            </select>
          </label>
          <a href="/" target="_blank" rel="noopener noreferrer" className="text-xs font-bold text-[var(--mitako-ink)] border border-slate-200 rounded-[8px] px-3 py-2 hover:bg-[var(--mitako-lime-soft)]">
            {t('desk.openCustomerApp')}
          </a>
          <button type="button" onClick={refreshAll} disabled={refreshing} className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-[8px] border border-slate-200 bg-white hover:bg-[var(--mitako-lime-soft)] disabled:opacity-60">
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} /> {refreshing ? '刷新中…' : t('desk.refresh')}
          </button>
        </div>
      </header>

      <div className="md:hidden grid grid-cols-3 gap-2 px-3 py-2 border-b border-slate-200 bg-white">
        {[
          ['queue', '队列'],
          ['chat', '会话'],
          ['brief', '档案'],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setMobileView(id)}
            className={`min-h-[44px] rounded-[8px] text-xs font-bold ${mobileView === id ? 'bg-[var(--mitako-lime)] text-slate-950' : 'bg-slate-50 text-slate-600'}`}
          >
            {label}
          </button>
        ))}
      </div>

      {notice && (
        <div className="px-4 py-2 border-b border-slate-200 bg-[var(--mitako-lime-soft)] text-xs font-bold text-slate-800">
          {notice}
        </div>
      )}

      <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-12 gap-0 overflow-y-auto md:overflow-hidden">
        <aside className={`${mobileView === 'queue' ? 'block' : 'hidden'} md:block md:col-span-3 min-h-0 md:border-r border-slate-200 bg-white overflow-y-auto console-scroll`}>
          <p className="px-4 py-3 text-xs font-bold text-slate-500">{t('desk.queueTitle')}</p>
          {sessions.length === 0 ? (
            <p className="px-4 py-8 text-sm text-slate-400 text-center">{t('desk.emptyQueue')}</p>
          ) : sessions.map(s => (
            <button
              key={s.session_id}
              type="button"
              data-testid={`desk-session-${s.session_id}`}
              onClick={() => { setActiveId(s.session_id); setMobileView('chat'); }}
              className={`w-full text-left px-4 py-3 border-b border-slate-100 hover:bg-[var(--mitako-lime-soft)] transition-colors ${
                activeId === s.session_id ? 'bg-[var(--mitako-lime-soft)] shadow-[inset_4px_0_0_var(--mitako-lime-deep)]' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-bold text-[var(--mitako-ink)]">{s.agent?.name || t('speakers.humanName')}</span>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-[8px] border ${statusClass(s.status)}`}>
                  {statusLabel(s.status)}
                </span>
              </div>
              <p className="text-sm font-semibold mt-1 truncate">{s.summary || t('desk.pickSession')}</p>
              <p className="text-[11px] text-slate-500 mt-0.5 flex flex-wrap gap-1">
                <span>情绪 L{s.emotion_level || '-'}</span>
                <span>{formatDuration(s.wait_seconds)}</span>
                {s.required_tier === 'supervisor' ? <span>{t('desk.needSupervisor')}</span> : null}
              </p>
            </button>
          ))}
        </aside>

        <main className={`${mobileView === 'chat' ? 'flex' : 'hidden'} md:flex md:col-span-5 min-h-[72dvh] md:min-h-0 flex-col bg-white`}>
          {!activeId ? (
            <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">{t('desk.pickSession')}</div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-slate-200 bg-white flex items-center gap-2 flex-wrap">
                <User className="w-4 h-4 text-slate-400" />
                <span className="text-sm font-bold">{t('transfer.briefTitle')}</span>
                {detail?.assigned_agent && (
                  <span className="text-xs font-bold text-[var(--mitako-ink)] ml-auto">
                    {detail.assigned_agent.name}
                  </span>
                )}
              </div>

              {canAccept && acceptBlockedReason && (
                <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                  {acceptBlockedReason}
                </div>
              )}

              {canAccept && (
                <div className="mx-4 mt-3 rounded-[8px] border border-slate-200 bg-[var(--mitako-lime-soft)] p-3 text-xs text-[var(--mitako-ink)]">
                  <p className="font-bold">{t('desk.acceptHint')}</p>
                  {assignedGateName && (
                    <p className="mt-1 text-[11px] text-slate-600">当前分配：{assignedGateName}；当前身份：{selectedAgent?.name || '未选择'}</p>
                  )}
                  <button
                    type="button"
                    data-testid="desk-accept-handoff"
                    disabled={accepting || !acceptAllowed}
                    onClick={() => setAcceptConfirmOpen(true)}
                    className="mt-2 inline-flex min-h-[44px] items-center gap-1.5 rounded-[8px] bg-[var(--mitako-lime)] px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-50"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    {accepting ? t('desk.accepting') : t('desk.acceptHandoff')}
                  </button>
                </div>
              )}

              <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3 console-scroll">
                {loading && <p className="text-xs text-slate-400">{t('desk.loading')}</p>}
                {((detail?.messages || []).length ? detail.messages : (brief?.conversation_snippet || [])).map((m, i) => (
                  <div key={`desk-${m.id || i}`} className={`max-w-[85%] rounded-[8px] px-3 py-2 text-sm border ${messageBubbleClass(m.role)}`}>
                    <span className="text-[10px] font-bold opacity-70 block mb-0.5">
                      {speakerLabel(m)}
                      {m.turn ? ` · ${t('desk.turnLabel', 'zh-CN', { turn: m.turn || i + 1 })}` : ''}
                    </span>
                    <RichTextContent text={sanitizePublicText(m.content)} />
                    <DeskAttachmentList attachments={m.attachments || []} />
                  </div>
                ))}
              </div>

              <div className="p-3 border-t border-slate-200 bg-white space-y-2">
                {canChat && (
                  <div className="flex flex-wrap gap-2 items-end p-2 rounded-[8px] bg-slate-50 border border-slate-200">
                    <div className="flex-1 min-w-[140px]">
                      <label className="text-[10px] font-bold text-slate-500 block mb-1">{t('desk.transferTarget')}</label>
                      <select
                        value={transferTargetId}
                        onChange={e => setTransferTargetId(e.target.value)}
                        className="w-full rounded-[8px] border border-slate-200 px-2 py-1.5 text-xs bg-white"
                      >
                        <option value="">{t('desk.transferTarget')}</option>
                        {colleagueOptions.map(a => (
                          <option key={a.agent_id} value={a.agent_id}>
                            {a.name} · {a.tier === 'supervisor' ? t('desk.tierSupervisor') : t('desk.tierStandard')}
                          </option>
                        ))}
                      </select>
                    </div>
                    <input
                      aria-label={t('desk.transferNotePlaceholder')}
                      value={transferNote}
                      onChange={e => setTransferNote(e.target.value)}
                      placeholder={t('desk.transferNotePlaceholder')}
                    className="flex-1 min-w-[120px] min-h-[36px] rounded-[8px] border border-slate-200 px-3 text-xs"
                    />
                    <button
                      type="button"
                      disabled={transferring || !transferTargetId}
                      onClick={transferColleague}
                      className="inline-flex min-h-[44px] items-center gap-1 text-xs font-bold px-3 py-2 rounded-[8px] bg-white text-[var(--mitako-ink)] hover:bg-[var(--mitako-lime-soft)] disabled:opacity-50"
                    >
                      <Users className="w-3.5 h-3.5" />
                      {transferring ? '处理中…' : t('desk.transferSubmit')}
                    </button>
                    {transferTarget && (
                      <div className="basis-full rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                        <div className="flex items-center gap-1 font-bold text-[var(--mitako-ink)]">
                          <Search className="w-3.5 h-3.5" />
                          {transferTarget.name} · {transferTarget.title || (transferTarget.tier === 'supervisor' ? '高级客服' : '普通客服')}
                        </div>
                        <p className="mt-1">
                          {transferTarget.team || '客服中心'} · {(transferTarget.skills || []).join('、') || '综合服务'}
                        </p>
                      </div>
                    )}
                  </div>
                )}
                {canChat && selectedAgent?.tier === 'standard' && (
                  <div className="flex flex-wrap gap-2 items-end">
                    <input
                      aria-label={t('desk.escalatePlaceholder')}
                      value={escalateNote}
                      onChange={e => setEscalateNote(e.target.value)}
                      placeholder={t('desk.escalatePlaceholder')}
                      className="flex-1 min-w-[160px] min-h-[36px] rounded-[8px] border border-slate-200 px-3 text-xs outline-none"
                    />
                    <button
                      type="button"
                      disabled={escalating}
                      onClick={escalateHandoff}
                      className="inline-flex min-h-[44px] items-center gap-1 text-xs font-bold px-3 py-2 rounded-[8px] bg-white text-[var(--mitako-ink)] hover:bg-[var(--mitako-lime-soft)]"
                    >
                      <ArrowUpCircle className="w-3.5 h-3.5" />
                      {escalating ? t('desk.escalating') : t('desk.escalate')}
                    </button>
                  </div>
                )}
                {isTransferring && detail?.pending_agent && (
                  <p className="text-xs text-[var(--mitako-ink)] bg-white rounded-[8px] px-3 py-2 border border-slate-200">
                    {t('desk.transferPending')}：{detail.pending_agent.name}
                  </p>
                )}
                {isEscalated && (
                  <p className="text-xs text-[var(--mitako-ink)] bg-white rounded-[8px] px-3 py-2 border border-slate-200">
                    {detail?.escalation_note || t('desk.escalatedDefault')}
                  </p>
                )}
                {canChat && (
                  <div className="flex flex-wrap gap-2 items-end">
                    <input
                      aria-label="结案说明"
                      value={closeNote}
                      onChange={e => setCloseNote(e.target.value)}
                      placeholder="结案说明，例如：已解释物流进度并告知用户后续节点"
                      className="flex-1 min-w-[180px] min-h-[36px] rounded-[8px] border border-slate-200 px-3 text-xs outline-none"
                    />
                    <button
                      type="button"
                      onClick={closeSession}
                      disabled={closing}
                      className="inline-flex min-h-[44px] items-center gap-1 rounded-[8px] bg-slate-900 px-3 py-2 text-xs font-bold text-white disabled:opacity-50"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      {closing ? '结案中…' : '结案归档'}
                    </button>
                  </div>
                )}
                <div className="flex gap-2">
                  {canChat && quickReplies.length > 0 && (
                    <div className="mb-2 flex basis-full flex-wrap gap-2">
                      {quickReplies.map((item, index) => (
                        <button
                          key={`${item}-${index}`}
                          type="button"
                          onClick={() => appendReplyText(item)}
                          className="rounded-[8px] border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-[var(--mitako-lime-soft)]"
                        >
                          {item.length > 24 ? `${item.slice(0, 24)}…` : item}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {canChat && (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="inline-flex items-center gap-1 font-bold text-slate-500"><SmilePlus className="w-3.5 h-3.5" />快捷表情</span>
                    {emojiReplies.map(item => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => appendReplyText(item)}
                        className="rounded-[8px] bg-[var(--mitako-lime-soft)] px-2.5 py-1.5 font-semibold text-[var(--mitako-ink)] hover:bg-[var(--mitako-lime)]"
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                )}
                <div className="flex gap-2">
                  <input
                    data-testid="desk-reply-input"
                    aria-label={canChat ? t('desk.replyPlaceholder') : t('desk.replyBlockedPlaceholder')}
                    value={reply}
                    onChange={e => setReply(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), sendReply())}
                    placeholder={canChat ? t('desk.replyPlaceholder') : t('desk.replyBlockedPlaceholder')}
                    disabled={!canChat || replying}
                    className="flex-1 min-h-[44px] rounded-[8px] border border-slate-200 px-3 text-sm outline-none disabled:bg-slate-50 disabled:text-slate-400"
                  />
                  <button
                    type="button"
                    data-testid="desk-reply-send"
                    aria-label="发送回复"
                    onClick={sendReply}
                    disabled={!canChat || replying}
                    className="min-w-[44px] h-11 rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] shadow-[0_10px_24px_rgba(127,164,49,.22)] flex items-center justify-center disabled:opacity-50"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </>
          )}
        </main>

        {acceptConfirmOpen && (
          <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/35 p-3 sm:items-center">
            <div className="w-full max-w-md rounded-[8px] border border-slate-200 bg-white p-4 shadow-[0_24px_80px_rgba(15,23,42,.18)]">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[8px] bg-[var(--mitako-lime-soft)] text-[var(--mitako-ink)]">
                  <CheckCircle2 className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-[var(--mitako-ink)]">确认接手当前会话</h3>
                  <p className="mt-1 text-sm leading-6 text-slate-600">
                    请确认已阅读队列摘要、服务记录和右侧移交简报。接手后需要负责回复用户、必要时转交同事或升级高级客服，并在处理完成后结案归档。
                  </p>
                  {acceptBlockedReason && (
                    <p className="mt-2 rounded-[8px] border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800">
                      {acceptBlockedReason}
                    </p>
                  )}
                </div>
              </div>
              <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={() => setAcceptConfirmOpen(false)}
                  disabled={accepting}
                  className="min-h-[44px] rounded-[8px] border border-slate-200 bg-white px-4 text-sm font-bold text-slate-600 hover:bg-slate-50 disabled:opacity-60"
                >
                  先不接手
                </button>
                <button
                  type="button"
                  data-testid="desk-accept-confirm"
                  onClick={acceptHandoff}
                  disabled={accepting || !acceptAllowed}
                  className="min-h-[44px] rounded-[8px] bg-[var(--mitako-lime)] px-4 text-sm font-bold text-[var(--mitako-ink)] shadow-[0_12px_28px_rgba(127,164,49,.22)] disabled:opacity-60"
                >
                  {accepting ? '接手中…' : '确认接手'}
                </button>
              </div>
            </div>
          </div>
        )}

        <aside className={`${mobileView === 'brief' ? 'block' : 'hidden'} md:block md:col-span-4 min-h-0 md:border-l border-slate-200 bg-white overflow-y-auto console-scroll p-4`}>
          <div className="flex items-center gap-2 mb-3">
            <ClipboardList className="w-4 h-4 text-[var(--mitako-ink)]" />
            <h2 className="text-sm font-bold">{t('transfer.briefTitle')}</h2>
          </div>
          {!brief ? (
            <p className="text-sm text-slate-400">{t('desk.noBrief')}</p>
          ) : (
            <div className="space-y-4 text-sm">
              {(sopState.sop_branch || qcEvent) && (
                <section className="rounded-[8px] border border-slate-200 bg-[var(--mitako-lime)] px-3 py-2 shadow-[0_10px_24px_rgba(127,164,49,.14)]">
                  <h3 className="text-xs font-bold text-[var(--mitako-ink)] mb-1">{t('desk.qcHint')}</h3>
                  <p className="text-xs leading-relaxed text-[var(--mitako-ink)] break-words">
                    {safeDeskText(sopState.sop_branch || brief.intent)}
                    {qcEvent?.result?.risk_level ? ` · ${safeDeskText(qcEvent.result.risk_level)}` : ''}
                    {sopState.readiness?.mode ? ` · ${t('desk.businessRecorded')}` : ''}
                  </p>
                </section>
              )}

              {latestBusinessAction && (
                <section className="rounded-[8px] border border-slate-200 bg-white px-3 py-2">
                  <h3 className="text-xs font-bold text-[var(--mitako-ink)] mb-1">{t('desk.nextStepPrimary')}</h3>
                  <p className="text-xs leading-relaxed text-[var(--mitako-ink)] break-words">
                    {safeDeskText(latestBusinessAction.result?.task_center?.next_step || latestBusinessAction.result?.reason || sopState.planned_action?.reason)}
                  </p>
                </section>
              )}

              {sopChecklist.length > 0 && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('desk.sopChecklist')}</h3>
                  <ul className="space-y-1.5">
                    {sopChecklist.map((item, i) => (
                      <li key={`${item.label}-${i}`} className="rounded-[8px] border border-slate-200 bg-white px-2 py-1.5 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-[var(--mitako-ink)] break-words">{safeDeskText(item.label)}</span>
                          <span className="shrink-0 rounded-[8px] bg-[var(--mitako-lime)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--mitako-ink)] border border-slate-200">{businessStatusLabel(item.status)}</span>
                        </div>
                        <p className="mt-1 leading-relaxed text-slate-600 break-words">{safeDeskText(item.note)}</p>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {visibleBusinessEvents.length > 0 && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('desk.businessActions')}</h3>
                  <div className="space-y-1.5">
                    {visibleBusinessEvents.slice(0, 5).map(ev => (
                      <div key={`${ev.id}-${ev.event_type}`} className="rounded-[8px] border border-slate-200 bg-white px-2 py-1.5 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-[var(--mitako-ink)] break-all">{businessEventLabel(ev.event_type)}</span>
                          <span className="shrink-0 rounded-[8px] bg-[var(--mitako-lime)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--mitako-ink)] border border-slate-200">{businessStatusLabel(ev.status)}</span>
                        </div>
                        <p className="mt-1 text-slate-600 break-words">
                          {businessRefLabel(ev.order_id || sopState.order_id)} · {ev.result?.requires_human ? t('desk.needSupervisor') : t('desk.businessRecorded')}
                        </p>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              <section>
                <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefSummary')}</h3>
                <div className="leading-relaxed"><RichTextContent text={safeDeskText(brief.summary)} /></div>
              </section>

              <section>
                <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefTrueIntent')}</h3>
                <p className="rounded-lg border border-slate-200 bg-white px-3 py-2 leading-relaxed text-slate-900 shadow-[0_10px_24px_rgba(127,164,49,.14)]">
                  {safeDeskText(brief.true_intent || brief.intent)}
                </p>
              </section>

              <section>
                <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefDialogue')}</h3>
                <div className="leading-relaxed"><RichTextContent text={safeDeskText(brief.ai_dialogue_summary)} /></div>
              </section>

              {brief.user_profile && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefProfile')}</h3>
                  <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3 text-xs">
                    <p><span className="text-slate-400">{t('transfer.profileNickname')}：</span>{safeDeskText(brief.user_profile.nickname)}</p>
                    <p><span className="text-slate-400">{t('transfer.profileLevel')}：</span>{safeDeskText(brief.user_profile.member_level)}</p>
                    <p><span className="text-slate-400">{t('transfer.profileRisk')}：</span>{safeDeskText(brief.user_profile.risk_level)}</p>
                    <p className="leading-relaxed"><span className="text-slate-400">{t('transfer.profilePsych')}：</span>{safeDeskText(brief.user_profile.psychological_analysis)}</p>
                  </div>
                </section>
              )}

              {(brief.emotion_triggers || []).length > 0 && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefTriggers')}</h3>
                  <ul className="space-y-2">
                    {brief.emotion_triggers.map((tr, i) => (
                      <li key={i} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs">
                        <span className="font-black text-slate-950">「{safeDeskText(tr.keyword)}」</span>
                        <span className="text-slate-500"> · {t('desk.turnLabel', 'zh-CN', { turn: tr.turn })}</span>
                        <p className="mt-1 text-slate-700 leading-relaxed">{safeDeskText(tr.excerpt)}</p>
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
                      <li key={i}>{safeDeskText(a)}</li>
                    ))}
                  </ol>
                </section>
              )}

              {(brief.orders || []).length > 0 && (
                <section>
                  <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefOrders')}</h3>
                  <ul className="space-y-1">{brief.orders.map((o, i) => (
                    <li key={i} className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 font-mono text-xs">{safeDeskText(o)}</li>
                  ))}</ul>
                </section>
              )}

              <section>
                <h3 className="text-xs font-bold text-slate-500 mb-1">{t('transfer.briefReason')}</h3>
                <div className="leading-relaxed"><RichTextContent text={safeDeskText(brief.transfer_reason_professional || brief.why_ai_cannot_handle || brief.reason)} /></div>
              </section>

              <section className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg border border-slate-200 bg-white p-2">
                  <span className="text-slate-400 block">{t('monitor.intentLabel')}</span>
                  {safeDeskText(brief.surface_intent || brief.intent)}
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-2">
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
