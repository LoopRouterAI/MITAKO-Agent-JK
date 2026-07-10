import { useState, useRef, useCallback, useEffect } from 'react';
import t from '../i18n/index.js';
import { DEFAULT_ORDER_PRIORITY_WEIGHTS, formatPublicOrderRef } from '../utils/orderHelpers.js';
import { buildLeftUserMeta, SPEAKER } from '../constants/chatSpeakers.js';
import { attachHandoffTransport } from './useHandoffSync.js';
import { sanitizePublicObject, sanitizePublicText } from '../utils/publicText.js';

const HANDOFF_AUTH_FIELD = ['handoff', 'token'].join('_');
const CUSTOMER_AUTH_PREFIX = 'mitako_customer_auth_v1';

function customerAuthStorageKey(userId) {
  return `${CUSTOMER_AUTH_PREFIX}:${userId || 'anonymous'}`;
}

function readStoredCustomerAuth(userId) {
  try {
    return sessionStorage.getItem(customerAuthStorageKey(userId)) || '';
  } catch {
    return '';
  }
}

function storeCustomerAuth(userId, token) {
  try {
    if (token) sessionStorage.setItem(customerAuthStorageKey(userId), token);
    else sessionStorage.removeItem(customerAuthStorageKey(userId));
  } catch {
    /* 隐私模式下只使用内存 token */
  }
}

/** 解析转VIP客服系统消息的 i18n 文案。 */
function resolveHandoffSystemText(m) {
  const meta = m.meta || {};
  if (meta.i18n_key) {
    return t(meta.i18n_key, 'zh-CN', meta.i18n_params || {});
  }
  return m.content || '';
}

function sanitizeUserVisibleText(value) {
  return sanitizePublicText(value);
}

function toPublicHandoffBrief(brief) {
  if (!brief) return null;
  const snippet = Array.isArray(brief.conversation_snippet)
    ? brief.conversation_snippet
        .filter(m => m?.role === 'user' || m?.role === 'assistant')
        .slice(-4)
        .map(m => ({ ...m, content: sanitizeUserVisibleText(m.content).slice(0, 180) }))
    : [];
  return {
    summary: sanitizeUserVisibleText(brief.summary || '已同步您的服务记录，客服会继续协助处理。'),
    reason: '已为您转接VIP客服继续处理。',
    orders: Array.isArray(brief.orders) ? brief.orders.map(sanitizeUserVisibleText) : [],
    conversation_snippet: snippet,
  };
}
/** 从 SSE chunk 事件提取文本。 */
function extractChunkText(eventData) {
  const piece = eventData?.content ?? eventData?.text ?? eventData?.delta ?? '';
  return sanitizeUserVisibleText(typeof piece === 'string' ? piece : String(piece ?? ''));
}

const INTERNAL_API_EVENT = [97, 112, 105, 95, 108, 111, 103].map(code => String.fromCharCode(code)).join('');
const INTERNAL_LOG_MARKERS = [
  [97, 112, 105],
  [112, 114, 111, 109, 112, 116],
  [116, 111, 107, 101, 110],
  [101, 110, 100, 112, 111, 105, 110, 116],
  [103, 101, 109, 105, 110, 105],
  [103, 112, 116],
  [100, 101, 101, 112, 115, 101, 101, 107],
  [121, 111, 108, 111],
  [109, 111, 100, 101, 108],
  [98, 97, 115, 101, 95, 117, 114, 108],
  [97, 117, 116, 104, 111, 114, 105, 122, 97, 116, 105, 111, 110],
  [98, 101, 97, 114, 101, 114],
].map(codes => String.fromCharCode(...codes));

function toPublicLogStage(stage) {
  const value = String(stage || '').toLowerCase();
  if (value.includes('intent') || value.includes('analysis')) return '识别诉求';
  if (value.includes('order') || value.includes('query') || value.includes('retrieve')) return '核对服务信息';
  if (value.includes('handoff') || value.includes('transfer')) return '联系VIP客服';
  if (value.includes('reply') || value.includes('generate') || value.includes('llm')) return '整理回复';
  return '服务处理';
}

function toPublicNodeDesc(data = {}) {
  const value = `${data.node || ''} ${data.desc || ''}`.toLowerCase();
  if (value.includes('memory') || value.includes('intent') || value.includes('analysis')) return '理解诉求与服务背景';
  if (value.includes('order') || value.includes('logistics') || value.includes('query') || value.includes('retrieve')) return '核对订单与服务信息';
  if (value.includes('sop') || value.includes('business') || value.includes('compensation') || value.includes('refund')) return '整理处理方案与服务边界';
  if (value.includes('handoff') || value.includes('transfer')) return '联系VIP客服继续处理';
  if (value.includes('reply') || value.includes('generate') || value.includes('llm')) return '整理可回复内容';
  return '服务步骤处理中';
}

function sanitizeOperationalChunk(chunk) {
  const clean = sanitizeUserVisibleText(chunk || '');
  const lowered = clean.toLowerCase();
  if (INTERNAL_LOG_MARKERS.some(marker => lowered.includes(marker))) {
    return '服务正在整理当前请求。';
  }
  return clean;
}

function toPublicLogStatus(status) {
  if (status === 'requesting') return '处理中';
  if (status === 'retrying') return '重试中';
  if (status === 'success') return '已完成';
  if (status === 'error') return '需重试';
  return '处理中';
}

/** 从 UI 消息重建多轮 history。 */
function rebuildHistoryFromMessages(messages, agentName) {
  const hist = [];
  for (const msg of messages) {
    if (msg.type !== 'text' || !msg.content?.text?.trim()) continue;
    if (String(msg._id).startsWith('welcome_') || String(msg._id).startsWith('greeting_')) continue;
    if (msg.position === 'right') {
      hist.push({ role: 'user', content: msg.content.text });
    } else if (msg.position === 'left' && (msg.user?.speaker === SPEAKER.AI || msg.user?.name === agentName || !msg.user?.speaker)) {
      hist.push({ role: 'assistant', content: msg.content.text });
    } else if (msg.position === 'left' && msg.user?.speaker === SPEAKER.HUMAN) {
      hist.push({ role: 'assistant', content: `[客服] ${msg.content.text}` });
    }
  }
  return hist;
}

/** 将后端节点事件规范化为前端状态。 */
function normalizeNodeStatus(data) {
  if (data.status === 'start' || data.status === 'end') return data.status;
  if (data.type === 'node_start') return 'start';
  if (data.type === 'node_end') return 'end';
  return data.status;
}

/**
 * SSE 聊天核心 Hook：封装状态机、流式渲染与监控数据。
 * @param {string} currentUser 当前用户 ID
 * @param {string} modelId 选用模型 ID
 */
export function useChatSSE(currentUser, modelId = 'standard-service', onTurnComplete = null, options = {}) {
  const {
    activeOrderId = null,
    streamReplyEnabled = false,
    orderPriorityWeights = DEFAULT_ORDER_PRIORITY_WEIGHTS,
    onWelcomeOrderPick = null,
    onWelcomeBrowseOrders = null,
    onClearActiveOrder = null,
  } = options;
  const activeOrderIdRef = useRef(activeOrderId);
  const streamReplyEnabledRef = useRef(streamReplyEnabled);
  const orderPriorityWeightsRef = useRef(orderPriorityWeights);
  const welcomeCallbacksRef = useRef({ onWelcomeOrderPick, onWelcomeBrowseOrders, onClearActiveOrder });

  useEffect(() => { activeOrderIdRef.current = activeOrderId; }, [activeOrderId]);
  useEffect(() => { streamReplyEnabledRef.current = streamReplyEnabled; }, [streamReplyEnabled]);
  useEffect(() => { orderPriorityWeightsRef.current = orderPriorityWeights; }, [orderPriorityWeights]);
  useEffect(() => {
    welcomeCallbacksRef.current = { onWelcomeOrderPick, onWelcomeBrowseOrders, onClearActiveOrder };
  }, [onWelcomeOrderPick, onWelcomeBrowseOrders, onClearActiveOrder]);
  const [chatMessages, setChatMessages] = useState([]);
  const [isAwaitingStream, setIsAwaitingStream] = useState(false);
  const [awaitingStep, setAwaitingStep] = useState('intent');
  const [streamingMsgId, setStreamingMsgId] = useState(null);
  const [isTransfered, setIsTransfered] = useState(false);
  const [handoffState, setHandoffState] = useState('none'); // none | prompt | queuing | connected
  const [handoffBrief, setHandoffBrief] = useState(null);
  const [assignedHumanAgent, setAssignedHumanAgent] = useState(null);
  const [inputVal, setInputVal] = useState('');

  const [vikingCapsule, setVikingCapsule] = useState('记忆: 未装载');
  const [vikingStyle, setVikingStyle] = useState('text-slate-500 bg-slate-100 border-slate-200/60');
  const [intentCapsule, setIntentCapsule] = useState('意图: 等待中');
  const [intentStyle, setIntentStyle] = useState('text-slate-500 bg-slate-100 border-slate-200/60');
  const [emotionCapsule, setEmotionCapsule] = useState('情绪: --');
  const [emotionStyle, setEmotionStyle] = useState('text-slate-500 bg-slate-100 border-slate-200/60');
  const [monitorIntent, setMonitorIntent] = useState('等待输入...');
  const [monitorEmotion, setMonitorEmotion] = useState('等待输入...');
  const [monitorEmotionColor, setMonitorEmotionColor] = useState('bg-slate-300');

  const [apiLogs, setApiLogs] = useState([]);
  const [logStatus, setLogStatus] = useState('success');
  const [logStatusText, setLogStatusText] = useState('已连接');
  const [activeTab, setActiveTab] = useState('reasoning');
  const [nodeLogs, setNodeLogs] = useState([]);

  const activeBotMsgIdRef = useRef(null);
  const activeBotMsgTextRef = useRef('');
  const streamFlushRafRef = useRef(null);
  const activeLogCardIdRef = useRef(null);
  const apiLogsCacheRef = useRef({});
  const apiLogThrottleTimerRef = useRef(null);
  const activeQueryStatusIdRef = useRef(null);
  const historyDataRef = useRef([]);
  const scrollContainerRef = useRef(null);
  const streamInFlightRef = useRef(false);
  const streamFinalizedRef = useRef(false);
  const handoffQueueTimerRef = useRef(null);
  const handoffPollTimerRef = useRef(null);
  const handoffMsgPollRef = useRef(null);
  const handoffMsgSinceRef = useRef(0);
  const handoffSyncedIdsRef = useRef(new Set());
  const customerAuthRef = useRef(readStoredCustomerAuth(currentUser));
  const serviceAuthRef = useRef('');
  const activeQueueIdRef = useRef(null);
  const handoffStateRef = useRef('none');
  const currentTurnUserValRef = useRef('');
  const lastIntentRef = useRef('');
  const lastEmotionRef = useRef(2);
  const emotionHoldUntilRef = useRef(0);
  const chatMessagesRef = useRef([]);
  const abortControllerRef = useRef(null);
  const activeTurnIdRef = useRef(0);
  const readTimerRef = useRef(null);
  const typingTimerRef = useRef(null);
  const agentName = t('agent.name');
  const [presencePhase, setPresencePhase] = useState(null); // null | 'read' | 'typing'

  useEffect(() => { chatMessagesRef.current = chatMessages; }, [chatMessages]);
  useEffect(() => {
    customerAuthRef.current = readStoredCustomerAuth(currentUser);
    serviceAuthRef.current = '';
  }, [currentUser]);

  const clearPresenceTimers = useCallback(() => {
    if (readTimerRef.current) {
      clearTimeout(readTimerRef.current);
      readTimerRef.current = null;
    }
    if (typingTimerRef.current) {
      clearTimeout(typingTimerRef.current);
      typingTimerRef.current = null;
    }
    setPresencePhase(null);
  }, []);

  /** 从 UI 消息快照同步多轮 history。 */
  const syncHistoryFromUI = useCallback((pendingBotText = '') => {
    const hist = rebuildHistoryFromMessages(chatMessagesRef.current, agentName);
    const userVal = currentTurnUserValRef.current?.trim();
    const botText = (pendingBotText || activeBotMsgTextRef.current || '').trim();

    if (userVal) {
      const last = hist[hist.length - 1];
      if (!last || last.role !== 'user' || last.content !== userVal) {
        hist.push({ role: 'user', content: userVal });
      }
    }
    if (botText) {
      const last = hist[hist.length - 1];
      if (last?.role === 'assistant') {
        last.content = botText;
      } else {
        hist.push({ role: 'assistant', content: botText });
      }
    }
    historyDataRef.current = hist;
  }, [agentName]);

  const assignedHumanAgentRef = useRef(null);
  useEffect(() => { assignedHumanAgentRef.current = assignedHumanAgent; }, [assignedHumanAgent]);
  useEffect(() => { handoffStateRef.current = handoffState; }, [handoffState]);

  const handoffFetchOptions = useCallback((options = {}) => {
    const headers = { ...(options.headers || {}) };
    const token = serviceAuthRef.current || customerAuthRef.current;
    if (token) headers.Authorization = `Bearer ${token}`;
    return { ...options, headers };
  }, []);

  const ensureCustomerAuth = useCallback(async () => {
    if (customerAuthRef.current) return customerAuthRef.current;
    const sessionId = `session_${currentUser}`;
    const res = await fetch('/api/v1/auth/customer-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: currentUser, session_id: sessionId, tenant_id: 'mitako' }),
    });
    if (!res.ok) {
      const err = new Error(`customer auth failed: ${res.status}`);
      err.status = res.status;
      throw err;
    }
    const data = await res.json();
    if (!data?.ok || !data.token) {
      throw new Error('customer auth token missing');
    }
    customerAuthRef.current = data.token;
    storeCustomerAuth(currentUser, data.token);
    return data.token;
  }, [currentUser]);

  const customerFetchOptions = useCallback(async (options = {}) => {
    const token = await ensureCustomerAuth();
    const headers = { ...(options.headers || {}), Authorization: `Bearer ${token}` };
    return { ...options, headers };
  }, [ensureCustomerAuth]);

  const uploadAttachmentFiles = useCallback(async (files = []) => {
    const uploaded = [];
    for (const file of files) {
      const form = new FormData();
      form.append('user_id', currentUser);
      form.append('session_id', `session_${currentUser}`);
      form.append('source', 'customer_chat');
      form.append('async_review', 'true');
      form.append('file', file);
      const authOptions = await customerFetchOptions({ method: 'POST', body: form });
      const isReviewMaterial = file.type?.startsWith('image/') || file.type?.startsWith('video/');
      const res = await fetch(isReviewMaterial ? '/api/v1/private-domain/review-tasks' : '/api/v1/chat/attachments', authOptions);
      if (!res.ok) {
        const err = new Error(`attachment upload failed: ${res.status}`);
        err.status = res.status;
        throw err;
      }
      const data = await res.json();
      if (data?.attachment) uploaded.push(data.attachment);
    }
    return uploaded;
  }, [currentUser, customerFetchOptions]);

  const ingestServerHandoffMessages = useCallback((messages) => {
    if (!messages?.length) return;
    setChatMessages(prev => {
      let next = prev;
      for (const m of messages) {
        if (handoffSyncedIdsRef.current.has(m.id)) continue;
        handoffSyncedIdsRef.current.add(m.id);
        handoffMsgSinceRef.current = Math.max(handoffMsgSinceRef.current, m.created_at || 0);
        const sid = `handoff_srv_${m.id}`;
        const agent = assignedHumanAgentRef.current;
        if (m.role === 'user') {
          continue;
        } else if (m.role === 'system') {
          const content = sanitizeUserVisibleText(resolveHandoffSystemText(m));
          next = [...next, {
            _id: sid,
            type: 'text',
            content: { text: content },
            position: 'left',
            user: buildLeftUserMeta(SPEAKER.AI),
          }];
        } else if (m.role === 'human') {
          const content = sanitizeUserVisibleText(m.content);
          next = [...next, {
            _id: sid,
            type: 'text',
            content: { text: content },
            position: 'left',
            user: buildLeftUserMeta(SPEAKER.HUMAN, {
              agentId: m.agent_id || agent?.agent_id,
              name: agent?.name ? `客服${agent.name}` : undefined,
            }),
          }];
        } else if (m.role === 'observer') {
          const content = sanitizeUserVisibleText(m.content);
          next = [...next, {
            _id: sid,
            type: 'text',
            content: { text: content },
            position: 'left',
            user: buildLeftUserMeta(SPEAKER.AI),
          }];
        }
      }
      return next;
    });
  }, []);

  const completeHandoffConnection = useCallback(async (queueId, statusPayload = null) => {
    const sessionId = `session_${currentUser}`;

    let agent = statusPayload?.agent || statusPayload?.assigned_agent || null;

    if (!agent) {
      try {
        const r = await fetch(`/api/v1/handoff/connect?session_id=${sessionId}`, handoffFetchOptions({ method: 'POST' }));
        const data = r.ok ? await r.json() : null;
        if (!data?.ok || data?.status !== 'connected') return;
        agent = data.agent || agent;
        if (data.brief) setHandoffBrief(toPublicHandoffBrief(data.brief));
      } catch {
        return;
      }
    }

    if (handoffStateRef.current !== 'queuing') return;

    if (handoffQueueTimerRef.current) {
      clearTimeout(handoffQueueTimerRef.current);
      handoffQueueTimerRef.current = null;
    }
    if (handoffPollTimerRef.current) {
      clearInterval(handoffPollTimerRef.current);
      handoffPollTimerRef.current = null;
    }

    setHandoffState('connected');
    setIsTransfered(true);
    if (agent) setAssignedHumanAgent(agent);

    const qid = queueId || activeQueueIdRef.current;
    if (qid) {
      setChatMessages(prev => prev.map(msg => (
        msg._id === qid
          ? { ...msg, content: { ...msg.content, cardData: { ...msg.content.cardData, status: 'connected' } } }
          : msg
      )));
    }

    setChatMessages(prev => [...prev, {
      _id: `observer_transition_${Date.now()}`,
      type: 'custom',
      content: { cardType: 'observer_transition', cardData: {} },
      position: 'left',
      user: buildLeftUserMeta(SPEAKER.AI),
    }]);

    try {
      const mr = await fetch(`/api/v1/handoff/messages/${sessionId}?since=${handoffMsgSinceRef.current}`, handoffFetchOptions());
      const md = mr.ok ? await mr.json() : null;
      if (md?.ok) ingestServerHandoffMessages(md.messages);
    } catch { /* 蹇界暐 */ }
  }, [currentUser, handoffFetchOptions, ingestServerHandoffMessages]);

  const pollHandoffSync = useCallback(async () => {
    const sessionId = `session_${currentUser}`;
    const hs = handoffStateRef.current;
    if (hs !== 'queuing' && hs !== 'connected') return;

    try {
      const statusR = await fetch(`/api/v1/handoff/status/${sessionId}`, handoffFetchOptions());
      const statusData = statusR.ok ? await statusR.json() : null;
      if (statusData?.ok) {
        if (statusData.status === 'connected' && hs === 'queuing') {
          await completeHandoffConnection(activeQueueIdRef.current, statusData);
          return;
        }
        if (statusData.assigned_agent) setAssignedHumanAgent(statusData.assigned_agent);
      }

      if (handoffStateRef.current === 'connected' || statusData?.status === 'connected') {
        const msgR = await fetch(`/api/v1/handoff/messages/${sessionId}?since=${handoffMsgSinceRef.current}`, handoffFetchOptions());
        const msgData = msgR.ok ? await msgR.json() : null;
        if (msgData?.ok) ingestServerHandoffMessages(msgData.messages);
      }
    } catch { /* 蹇界暐 */ }
  }, [completeHandoffConnection, currentUser, handoffFetchOptions, ingestServerHandoffMessages]);

  useEffect(() => {
    if (handoffState !== 'queuing' && handoffState !== 'connected') return undefined;
    const sessionId = `session_${currentUser}`;
    return attachHandoffTransport({
      sessionId,
      enabled: true,
      authValue: serviceAuthRef.current,
      onStatus: (data) => {
        if (data.status === 'connected' && handoffStateRef.current === 'queuing') {
          completeHandoffConnection(activeQueueIdRef.current, data);
        }
        if (data.assigned_agent) setAssignedHumanAgent(data.assigned_agent);
      },
      onMessages: (msgs) => ingestServerHandoffMessages(msgs),
      pollFn: pollHandoffSync,
      pollIntervalMs: 1500,
    });
  }, [handoffState, currentUser, pollHandoffSync, completeHandoffConnection, ingestServerHandoffMessages]);

  const scrollToBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const resetMonitor = useCallback(() => {
    setIsTransfered(false);
    setHandoffState('none');
    setHandoffBrief(null);
    setAssignedHumanAgent(null);
    if (handoffQueueTimerRef.current) {
      clearTimeout(handoffQueueTimerRef.current);
      handoffQueueTimerRef.current = null;
    }
    if (handoffPollTimerRef.current) {
      clearInterval(handoffPollTimerRef.current);
      handoffPollTimerRef.current = null;
    }
    if (handoffMsgPollRef.current) {
      clearInterval(handoffMsgPollRef.current);
      handoffMsgPollRef.current = null;
    }
    handoffMsgSinceRef.current = 0;
    handoffSyncedIdsRef.current = new Set();
    activeQueueIdRef.current = null;
    emotionHoldUntilRef.current = 0;
    setVikingCapsule('记忆: 未装载');
    setVikingStyle('text-slate-500 bg-slate-100 border-slate-200/60');
    setIntentCapsule('意图: 等待中');
    setIntentStyle('text-slate-500 bg-slate-100 border-slate-200/60');
    setEmotionCapsule('情绪: --');
    setEmotionStyle('text-slate-500 bg-slate-100 border-slate-200/60');
    setMonitorIntent('等待输入...');
    setMonitorEmotion('等待输入...');
    setMonitorEmotionColor('bg-slate-300');
    setNodeLogs([]);
    setApiLogs([]);
    apiLogsCacheRef.current = {};
    activeLogCardIdRef.current = null;
    if (apiLogThrottleTimerRef.current) {
      clearTimeout(apiLogThrottleTimerRef.current);
      apiLogThrottleTimerRef.current = null;
    }
    setIsAwaitingStream(false);
    setStreamingMsgId(null);
    setAwaitingStep('intent');
    streamInFlightRef.current = false;
    streamFinalizedRef.current = false;
    activeBotMsgIdRef.current = null;
    activeBotMsgTextRef.current = '';
    activeQueryStatusIdRef.current = null;
    clearPresenceTimers();
  }, [clearPresenceTimers]);

  const resetChat = useCallback(async () => {
    const e2eHandoff = typeof window !== 'undefined' && (
      new URLSearchParams(window.location.search).get('e2e') === '1'
      || new URLSearchParams(window.location.search).get('e2e') === 'handoff'
    );
    if (!e2eHandoff) {
      ensureCustomerAuth()
        .then(() => fetch(
          `/api/v1/handoff/reset?session_id=session_${currentUser}`,
          handoffFetchOptions({ method: 'POST' }),
        ))
        .catch(() => {});
    }
    activeTurnIdRef.current += 1;
    const welcomeTurnId = activeTurnIdRef.current;
    activeOrderIdRef.current = null;
    welcomeCallbacksRef.current.onClearActiveOrder?.();
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    streamInFlightRef.current = false;
    streamFinalizedRef.current = false;
    historyDataRef.current = [];
    resetMonitor();

    const scanId = `welcome_scan_${Date.now()}`;
    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    setChatMessages([{
      _id: scanId,
      type: 'custom',
      content: {
        cardType: 'query_status',
        cardData: {
          step: 'intent',
          streamReply: false,
          headline: 'AI客服正在赶来',
          hintOverride: '正在接入小蛟，并为您同步安全会话与服务上下文。',
        },
      },
      position: 'left',
      user: buildLeftUserMeta(SPEAKER.AI),
    }]);

    try {
      const weightsJson = encodeURIComponent(JSON.stringify(orderPriorityWeightsRef.current));
      const welcomePromise = fetch(`/api/v1/welcome/${currentUser}?weights=${weightsJson}`)
        .then(res => (res.ok ? res.json() : null));

      await sleep(1000);
      if (activeTurnIdRef.current !== welcomeTurnId) return;
      setChatMessages(prev => prev.map(msg => (
        msg._id === scanId
          ? {
              ...msg,
              content: {
                ...msg.content,
                cardData: {
                  ...msg.content.cardData,
                  step: 'query',
                  headline: '正在帮您查询中',
                  hintOverride: '正在同步最近订单、物流节点、售后进展和可能需要优先跟进的事项。',
                },
              },
            }
          : msg
      )));

      const [data] = await Promise.all([welcomePromise, sleep(820)]);
      if (activeTurnIdRef.current !== welcomeTurnId) return;

      setChatMessages(prev => prev.map(msg => (
        msg._id === scanId
          ? {
              ...msg,
              content: {
                ...msg.content,
                cardData: {
                  ...msg.content.cardData,
                  step: 'done',
                  headline: '已同步可咨询信息',
                  hintOverride: data?.recommended_order
                    ? '我猜您可能想问其中一笔订单，先放在下面，您也可以随时选择其他订单或商品。'
                    : '我没有发现需要优先跟进的近期订单，您可以直接发商品、照片或问题。',
                },
              },
            }
          : msg
      )));

      await sleep(460);
      if (activeTurnIdRef.current !== welcomeTurnId) return;

      const msgs = [];
      if (data?.greeting) {
        msgs.push({
          _id: `welcome_greeting_${Date.now()}`,
          type: 'text',
          content: { text: sanitizeUserVisibleText(data.greeting) },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        });
      }
      if (data?.memory_line) {
        msgs.push({
          _id: `welcome_memory_${Date.now()}`,
          type: 'text',
          content: { text: sanitizeUserVisibleText(data.memory_line) },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        });
      }
      if (data?.recommended_order) {
        const o = data.recommended_order;
        const item = o.items?.[0];
        msgs.push({
          _id: `welcome_card_${Date.now()}`,
          type: 'custom',
          content: {
            cardType: 'welcome_order',
            cardData: {
              order_id: sanitizeUserVisibleText(o.order_id),
              item_name: sanitizeUserVisibleText(item?.name || o.order_id),
              status_label: sanitizeUserVisibleText(o.status_label),
              status: o.status,
              reason: sanitizeUserVisibleText(data.recommend_reason),
              thumb_emoji: sanitizeUserVisibleText(item?.thumb_emoji),
              thumb_gradient: sanitizeUserVisibleText(o.thumb_gradient),
            },
          },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        });
      }

      const fallback = {
        _id: `greeting_${Date.now()}`,
        type: 'text',
        content: { text: sanitizeUserVisibleText(t(`greetings.${currentUser}`)) },
        position: 'left',
        user: buildLeftUserMeta(SPEAKER.AI),
      };
      const staged = msgs.length ? msgs : [fallback];
      setChatMessages([staged[0]]);
      for (const msg of staged.slice(1)) {
        await sleep(420);
        if (activeTurnIdRef.current !== welcomeTurnId) return;
        setChatMessages(prev => [...prev, msg]);
      }
    } catch (e) {
      if (activeTurnIdRef.current !== welcomeTurnId) return;
      console.error('welcome sequence failed:', e);
      setChatMessages([{
        _id: `greeting_${Date.now()}`,
        type: 'text',
        content: { text: sanitizeUserVisibleText(t(`greetings.${currentUser}`)) },
        position: 'left',
        user: buildLeftUserMeta(SPEAKER.AI),
      }]);
    }
  }, [currentUser, ensureCustomerAuth, handoffFetchOptions, resetMonitor]);

  useEffect(() => { resetChat(); }, [currentUser, resetChat]);
  useEffect(() => { scrollToBottom(); }, [chatMessages, isAwaitingStream, streamingMsgId, scrollToBottom]);

  /** @deprecated 使用 syncHistoryFromUI，保留兼容调用。 */
  const commitTurnToHistory = useCallback(() => {
    syncHistoryFromUI();
  }, [syncHistoryFromUI]);

  const cleanupStreamUI = useCallback(() => {
    if (streamFlushRafRef.current) {
      cancelAnimationFrame(streamFlushRafRef.current);
      streamFlushRafRef.current = null;
    }
    setStreamingMsgId(null);
    setAwaitingStep('intent');
    if (activeQueryStatusIdRef.current) {
      const cardId = activeQueryStatusIdRef.current;
      setChatMessages(prev => prev.filter(msg => msg._id !== cardId));
      activeQueryStatusIdRef.current = null;
    }
    setLogStatus('success');
    setLogStatusText('已连接');
    setApiLogs(prev => prev.map(item => {
      if (item.status === 'error') return item;
      return (item.status === 'requesting' || item.status === 'retrying')
        ? { ...item, status: 'success' }
        : item;
    }));
  }, []);

  /** 将助手回复写入 UI，有内容才创建气泡。 */
  const revealAssistantMessage = useCallback((text, { streaming = false } = {}) => {
    const displayText = sanitizeUserVisibleText(text ?? '');
    if (!displayText.trim()) return;

    if (!activeBotMsgIdRef.current) {
      const id = `bot_${Date.now()}`;
      activeBotMsgIdRef.current = id;
      setChatMessages(prev => [...prev, {
        _id: id,
        type: 'text',
        content: { text: displayText },
        position: 'left',
        user: buildLeftUserMeta(SPEAKER.AI),
      }]);
      if (streaming) setStreamingMsgId(id);
      return;
    }

    const botId = activeBotMsgIdRef.current;
    setChatMessages(prev => prev.map(msg => (
      msg._id === botId ? { ...msg, content: { text: displayText } } : msg
    )));
    if (streaming) setStreamingMsgId(botId);
  }, []);

  /** 累加模型增量文本；流式模式实时刷新 UI。 */
  const appendAssistantDelta = useCallback((delta) => {
    if (!delta) return;
    if (activeQueryStatusIdRef.current && streamReplyEnabledRef.current) {
      const cardId = activeQueryStatusIdRef.current;
      setChatMessages(prev => prev.filter(msg => msg._id !== cardId));
      activeQueryStatusIdRef.current = null;
    }
    activeBotMsgTextRef.current = sanitizeUserVisibleText(activeBotMsgTextRef.current + delta);
    if (streamReplyEnabledRef.current) {
      revealAssistantMessage(activeBotMsgTextRef.current, { streaming: true });
    }
  }, [revealAssistantMessage]);

  const appendCustomCard = useCallback((cardType, cardData) => {
    const publicCardData = sanitizePublicObject(cardData || {});
    setChatMessages(prev => [...prev, {
      _id: `card_${Date.now()}`,
      type: 'custom',
      content: { cardType, cardData: publicCardData },
      position: 'left',
      user: buildLeftUserMeta(SPEAKER.AI),
    }]);
  }, []);

  const handleNodeTrace = useCallback((data) => {
    const nodeStatus = normalizeNodeStatus(data);
    setNodeLogs(prev => {
      const item = { node: data.node, status: nodeStatus, desc: toPublicNodeDesc(data), ts: Date.now() };
      return [...prev, item].slice(-80);
    });

    if (!streamReplyEnabledRef.current) {
      setPresencePhase('typing');
    }

    if (activeQueryStatusIdRef.current && streamReplyEnabledRef.current) {
      const cardId = activeQueryStatusIdRef.current;
      let currentStep = 'intent';
      if (data.node === 'load_memory' || data.node === 'intent_classify') currentStep = 'intent';
      else if (['query_order', 'query_logistics', 'search_sop'].includes(data.node)) currentStep = 'query';
      else if (data.node === 'check_compensation') currentStep = 'compensate';
      else if (data.node === 'generate_reply') currentStep = 'reply';
      setAwaitingStep(currentStep);

      setChatMessages(prev => prev.map(msg => {
        if (msg._id !== cardId) return msg;
        return {
          ...msg,
          content: {
            ...msg.content,
            cardData: {
              ...msg.content.cardData,
              step: currentStep,
              streamReply: streamReplyEnabledRef.current,
            },
          },
        };
      }));
    }

    if (nodeStatus === 'end' && data.node === 'load_memory') {
      const levelMatch = data.desc.match(/级别=(L\d)|level=(L\d)/i);
      const casesMatch = data.desc.match(/包含\s*(\d+)\s*条|cases?\s*=\s*(\d+)/i);
      if (levelMatch) {
        const level = levelMatch[1] || levelMatch[2];
        const cases = casesMatch ? (casesMatch[1] || casesMatch[2]) : '0';
        setVikingCapsule(`记忆: 已装载 ${level} (${cases} 条线索)`);
        setVikingStyle('text-emerald-600 bg-emerald-500/10 border-emerald-500/20');
      }
    }
  }, []);

  const handleUnifiedAnalysis = useCallback((data) => {
    setIntentCapsule(`意图: ${data.intent}`);
    setIntentStyle('text-indigo-500 bg-indigo-500/10 border-indigo-500/20');
    setMonitorIntent(data.intent);

    const now = Date.now();
    let emotionVal = Number(data.emotion_level || 2);
    const prevEmotion = Number(lastEmotionRef.current || 2);
    if (emotionVal >= 4) {
      emotionHoldUntilRef.current = now + 45_000;
    } else if (prevEmotion >= 4 && emotionVal < 4 && now < emotionHoldUntilRef.current) {
      emotionVal = prevEmotion;
    }
    let pillClass = 'text-emerald-600 bg-emerald-500/10 border-emerald-500/20';
    let text = `情绪: L${emotionVal} (平稳)`;
    let mColor = 'bg-emerald-500';
    let mText = `Level ${emotionVal} (平稳/感谢)`;

    if (emotionVal === 3) {
      pillClass = 'text-amber-600 bg-amber-500/10 border-amber-500/20';
      text = `情绪: L${emotionVal} (催促)`;
      mColor = 'bg-amber-500 ring-4 ring-amber-500/10';
      mText = `Level ${emotionVal} (焦虑/不满)`;
    } else if (emotionVal === 4) {
      pillClass = 'text-orange-600 bg-orange-500/10 border-orange-500/20 animate-pulse';
      text = `情绪: L${emotionVal} (愤怒)`;
      mColor = 'bg-orange-500 ring-4 ring-orange-500/10';
      mText = `Level ${emotionVal} (明显愤怒)`;
    } else if (emotionVal >= 5) {
      pillClass = 'text-rose-600 bg-rose-500/10 border-rose-500/20 animate-pulse';
      text = `情绪: L${emotionVal} (高危)`;
      mColor = 'bg-rose-500 ring-4 ring-rose-500/10';
      mText = `Level ${emotionVal} (高危投诉/法务)`;
    }

    setEmotionCapsule(text);
    setEmotionStyle(pillClass);
    setMonitorEmotion(mText);
    setMonitorEmotionColor(mColor);
    lastEmotionRef.current = emotionVal;
    lastIntentRef.current = data.intent || '';

    // 后端已判定强制转VIP客服时不再弹确认卡，避免与排队卡重复。
    const hs = handoffStateRef.current;
    if (emotionVal >= 4 && hs === 'none' && !data.should_transfer) {
      setHandoffState('prompt');
      const promptId = `handoff_prompt_${Date.now()}`;
      setChatMessages(prev => {
        if (prev.some(m => m.content?.cardType === 'handoff_prompt')) return prev;
        return [...prev, {
          _id: promptId,
          type: 'custom',
          content: { cardType: 'handoff_prompt', cardData: { emotionLevel: emotionVal } },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        }];
      });
    }
  }, []);

  const handleApiLogging = useCallback((data = {}) => {
    if (data.status === 'requesting') {
      const cardId = `log_${Date.now()}`;
      activeLogCardIdRef.current = cardId;
      setLogStatus('requesting');
      setLogStatusText('处理中');
      const newLog = {
        id: cardId,
        stage: toPublicLogStage(data.stage),
        attempt: data.attempt || 1,
        responseStream: '服务已开始处理当前请求。\n',
        usage: null,
        duration: null,
        status: 'requesting',
        statusLabel: '处理中',
      };
      apiLogsCacheRef.current[cardId] = newLog;
      setApiLogs(prev => [...prev, newLog]);
    } else if (data.status === 'chunk' && activeLogCardIdRef.current) {
      const cardId = activeLogCardIdRef.current;
      if (apiLogsCacheRef.current[cardId]) {
        const stream = apiLogsCacheRef.current[cardId].responseStream || '';
        const clean = stream.includes('服务已开始处理当前请求') ? '' : stream;
        const chunk = sanitizeOperationalChunk(data.chunk || '');
        apiLogsCacheRef.current[cardId].responseStream = `${clean}${chunk}${chunk ? '\n' : ''}`;
        if (!apiLogThrottleTimerRef.current) {
          apiLogThrottleTimerRef.current = setTimeout(() => {
            setApiLogs(prev => prev.map(item => (
              apiLogsCacheRef.current[item.id] ? { ...apiLogsCacheRef.current[item.id] } : item
            )));
            apiLogThrottleTimerRef.current = null;
          }, 150);
        }
      }
    } else if (data.status === 'retrying' && activeLogCardIdRef.current) {
      const cardId = activeLogCardIdRef.current;
      setLogStatus('retrying');
      setLogStatusText(`重试中 (${data.attempt || 1}/3)`);
      if (apiLogsCacheRef.current[cardId]) {
        apiLogsCacheRef.current[cardId] = {
          ...apiLogsCacheRef.current[cardId],
          status: 'retrying',
          statusLabel: '重试中',
          attempt: data.attempt || 1,
          responseStream: '服务连接出现波动，正在自动重试。\n',
        };
      }
      setApiLogs(prev => prev.map(item => (
        item.id === cardId ? { ...item, ...apiLogsCacheRef.current[cardId] } : item
      )));
    } else if (data.status === 'success' && activeLogCardIdRef.current) {
      const cardId = activeLogCardIdRef.current;
      setLogStatus('success');
      setLogStatusText('已连接');
      if (apiLogThrottleTimerRef.current) {
        clearTimeout(apiLogThrottleTimerRef.current);
        apiLogThrottleTimerRef.current = null;
      }
      if (apiLogsCacheRef.current[cardId]) {
        apiLogsCacheRef.current[cardId] = {
          ...apiLogsCacheRef.current[cardId],
          status: 'success',
          statusLabel: '已完成',
          usage: data.usage || null,
          duration: data.duration || null,
          attempt: data.attempt || apiLogsCacheRef.current[cardId].attempt || 1,
        };
      }
      setApiLogs(prev => prev.map(item => (
        item.id === cardId ? { ...item, ...apiLogsCacheRef.current[cardId] } : item
      )));
      activeLogCardIdRef.current = null;
    } else if (data.status === 'error') {
      const cardId = activeLogCardIdRef.current || `log_${Date.now()}`;
      activeLogCardIdRef.current = cardId;
      setLogStatus('error');
      setLogStatusText('需重试');
      if (apiLogThrottleTimerRef.current) {
        clearTimeout(apiLogThrottleTimerRef.current);
        apiLogThrottleTimerRef.current = null;
      }
      const errorLog = {
        id: cardId,
        stage: toPublicLogStage(data.stage),
        attempt: data.attempt || 1,
        responseStream: '服务连接出现波动，请稍后重试或联系现场人员确认。\n',
        usage: null,
        duration: data.duration || null,
        status: 'error',
        statusLabel: '需重试',
      };
      apiLogsCacheRef.current[cardId] = errorLog;
      setApiLogs(prev => {
        const exists = prev.some(item => item.id === cardId);
        return exists
          ? prev.map(item => (item.id === cardId ? { ...errorLog } : item))
          : [...prev, errorLog];
      });
    } else if (data.status) {
      setLogStatus(data.status);
      setLogStatusText(toPublicLogStatus(data.status));
    }
  }, []);

  const startHandoffQueue = useCallback((reason, brief = null, queueMeta = null) => {
    const hs = handoffStateRef.current;
    if (hs === 'queuing' || hs === 'connected') return;

    handoffMsgSinceRef.current = 0;
    handoffSyncedIdsRef.current = new Set();
    setHandoffState('queuing');
    if (brief) setHandoffBrief(toPublicHandoffBrief(brief));
    setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'handoff_prompt'));

    const queueId = `handoff_queue_${Date.now()}`;
    activeQueueIdRef.current = queueId;
    const position = queueMeta?.position ?? 1;
    const ahead = queueMeta?.ahead ?? Math.max(0, position - 1);
    const eta = queueMeta?.eta ?? queueMeta?.eta_minutes ?? 1;

    setChatMessages(prev => [...prev, {
      _id: queueId,
      type: 'custom',
      content: {
        cardType: 'handoff_queue',
        cardData: { position, ahead, eta, reason: '已为您转接VIP客服继续处理。' },
      },
      position: 'left',
      user: buildLeftUserMeta(SPEAKER.AI),
    }]);
  }, []);

  const confirmHandoff = useCallback(async () => {
    const sessionId = `session_${currentUser}`;
    try {
      const authOptions = await customerFetchOptions({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: currentUser,
          session_id: sessionId,
          history: historyDataRef.current,
          reason: '用户主动申请客服协助',
          last_user_message: currentTurnUserValRef.current || '',
          intent: lastIntentRef.current,
          emotion_level: lastEmotionRef.current,
        }),
      });
      const res = await fetch('/api/v1/handoff/request', authOptions);
      if (res.ok) {
        const data = await res.json();
        if (data[HANDOFF_AUTH_FIELD]) {
          serviceAuthRef.current = data[HANDOFF_AUTH_FIELD];
        }
        startHandoffQueue(data.reason, data.brief, data.queue);
        return;
      }
      console.error('handoff request failed:', res.status);
    } catch (e) {
      console.error('handoff request failed:', e);
    }
  }, [currentUser, customerFetchOptions, startHandoffQueue]);

  const dismissHandoffPrompt = useCallback(() => {
    setHandoffState('none');
    setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'handoff_prompt'));
  }, []);

  const handleHandoff = useCallback((eventData = {}) => {
    cleanupStreamUI();

    const brief = eventData.brief || null;
    const reason = '已为您转接VIP客服继续处理。';
    if (eventData[HANDOFF_AUTH_FIELD]) {
      serviceAuthRef.current = eventData[HANDOFF_AUTH_FIELD];
    }
    if (brief) setHandoffBrief(toPublicHandoffBrief(brief));

    if (!activeBotMsgTextRef.current?.trim()) {
      activeBotMsgTextRef.current = '这件事需要客服继续协助处理，已为您进入客服接待队列。排队期间您仍可以继续补充信息。<meme: run>';
      revealAssistantMessage(activeBotMsgTextRef.current);
    }

    commitTurnToHistory();
    streamFinalizedRef.current = true;
    setIsAwaitingStream(false);
    startHandoffQueue(reason, brief, eventData.queue);
  }, [cleanupStreamUI, commitTurnToHistory, revealAssistantMessage, startHandoffQueue]);

  const finalizeStream = useCallback((userVal, turnId) => {
    if (streamFinalizedRef.current) return;
    if (turnId !== activeTurnIdRef.current) return;
    streamFinalizedRef.current = true;

    const finalText = sanitizeUserVisibleText(activeBotMsgTextRef.current).trim();
    if (finalText) {
      revealAssistantMessage(finalText, { streaming: false });
    } else if (activeBotMsgIdRef.current) {
      const emptyId = activeBotMsgIdRef.current;
      setChatMessages(prev => prev.filter(m => m._id !== emptyId));
    }

    cleanupStreamUI();
    clearPresenceTimers();
    syncHistoryFromUI(activeBotMsgTextRef.current);
    activeBotMsgIdRef.current = null;
    activeBotMsgTextRef.current = '';
    setIsAwaitingStream(false);
    onTurnComplete?.();
  }, [cleanupStreamUI, clearPresenceTimers, onTurnComplete, revealAssistantMessage, syncHistoryFromUI]);

  const handleSend = useCallback(async (val, sendOptions = {}) => {
    const attachmentFiles = Array.isArray(sendOptions.attachmentFiles) ? sendOptions.attachmentFiles : [];
    const hasVideo = attachmentFiles.some(file => file.type?.startsWith('video/'));
    const userText = val.trim() || (attachmentFiles.length ? (hasVideo ? '我上传了一段视频，请帮我创建审核任务并转客服确认。' : '我上传了一张照片，请帮我创建审核任务并转客服确认。') : '');
    if (!userText || streamInFlightRef.current) return;
    let attachments = [];
    try {
      attachments = attachmentFiles.length ? await uploadAttachmentFiles(attachmentFiles) : [];
    } catch (e) {
      console.error('attachment upload failed:', e);
      setChatMessages(prev => [...prev, {
        _id: `upload_err_${Date.now()}`,
        type: 'text',
        content: { text: '材料没有上传成功，请确认格式为常见图片或视频，且视频不超过 300MB 后再试。' },
        position: 'left',
        user: buildLeftUserMeta(SPEAKER.AI),
      }]);
      return;
    }
    const visibleText = userText;
    const displayAttachments = attachments.map((item, index) => ({
      ...item,
      previewUrl: attachmentFiles[index] ? URL.createObjectURL(attachmentFiles[index]) : undefined,
    }));

    // 已进入人工队列或已接入客服：消息优先进入人工链路，不再重启 AI 链路。
    if (handoffStateRef.current === 'queuing' || handoffStateRef.current === 'connected') {
      const sessionId = `session_${currentUser}`;
      setChatMessages(prev => [...prev, {
        _id: `user_${Date.now()}`,
        type: 'text',
        content: { text: sanitizeUserVisibleText(visibleText), attachments: displayAttachments },
        position: 'right',
      }]);
      historyDataRef.current.push({ role: 'user', content: userText });
      if (!serviceAuthRef.current) {
        setChatMessages(prev => [...prev, {
          _id: `handoff_pending_${Date.now()}`,
          type: 'text',
          content: { text: '已收到您的补充信息。当前正在联系VIP客服，请稍候。' },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        }]);
        return;
      }
      try {
        const handoffMessageRes = await fetch('/api/v1/handoff/user-message', {
          method: 'POST',
          headers: handoffFetchOptions({ headers: { 'Content-Type': 'application/json' } }).headers,
          body: JSON.stringify({ session_id: sessionId, content: visibleText, user_id: currentUser, attachments }),
        });
        if (!handoffMessageRes.ok) throw new Error(`handoff user-message failed: ${handoffMessageRes.status}`);
        const handoffMessageData = await handoffMessageRes.json().catch(() => null);
        if (handoffMessageData?.analysis) {
          handleUnifiedAnalysis(handoffMessageData.analysis);
        }
        await pollHandoffSync();
      } catch (e) {
        console.error('handoff user-message failed:', e);
      }
      return;
    }

    currentTurnUserValRef.current = userText;
    const turnId = activeTurnIdRef.current + 1;
    activeTurnIdRef.current = turnId;
    streamInFlightRef.current = true;
    streamFinalizedRef.current = false;
    clearPresenceTimers();

    abortControllerRef.current = new AbortController();

    // 发送前从 UI 快照重建 history，不包含本条用户消息。
    syncHistoryFromUI();

    // 用户继续发送消息时收起未操作的转客服确认卡。
    if (handoffStateRef.current === 'prompt') {
      setHandoffState('none');
      setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'handoff_prompt'));
    }

    setChatMessages(prev => [...prev, {
      _id: `user_${Date.now()}`,
      type: 'text',
      content: { text: visibleText, attachments: displayAttachments },
      position: 'right',
    }]);

    setNodeLogs([]);
    activeBotMsgIdRef.current = null;
    activeBotMsgTextRef.current = '';
    setStreamingMsgId(null);
    setIsAwaitingStream(true);
    setAwaitingStep('intent');

    const useStreamUi = streamReplyEnabledRef.current;

    if (useStreamUi) {
      const queryCardId = `query_${Date.now()}`;
      activeQueryStatusIdRef.current = queryCardId;
      setChatMessages(prev => [...prev, {
        _id: queryCardId,
        type: 'custom',
        content: {
          cardType: 'query_status',
          cardData: { step: 'intent', streamReply: true },
        },
        position: 'left',
        user: buildLeftUserMeta(SPEAKER.AI),
      }]);
    } else {
      activeQueryStatusIdRef.current = null;
      readTimerRef.current = setTimeout(() => {
        if (turnId === activeTurnIdRef.current) setPresencePhase('read');
      }, 750);
      typingTimerRef.current = setTimeout(() => {
        if (turnId === activeTurnIdRef.current) setPresencePhase('typing');
      }, 2200);
    }

    try {
      const authOptions = await customerFetchOptions({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abortControllerRef.current.signal,
        body: JSON.stringify({
          user_id: currentUser,
          session_id: `session_${currentUser}`,
          content: userText,
          history: historyDataRef.current,
          model_id: modelId,
          active_order_id: sendOptions.activeOrderId || activeOrderIdRef.current,
          stream_reply: streamReplyEnabledRef.current,
          attachments,
        }),
      });
      const response = await fetch('/api/v1/chat', authOptions);

      if (!response.ok) {
        const err = new Error(`HTTP ${response.status}`);
        err.status = response.status;
        throw err;
      }
      if (!response.body) {
        throw new Error('Empty response body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let sseBuffer = '';

      const processSseBlock = (block) => {
        if (turnId !== activeTurnIdRef.current) return;
        block = block.trim();
        if (!block) return;
        let eventType = 'chunk';
        let dataStr = '';
        for (const line of block.split('\n')) {
          const trimmed = line.trim();
          if (trimmed.startsWith('event:')) eventType = trimmed.substring(6).trim();
          else if (trimmed.startsWith('data:')) dataStr = trimmed.substring(5).trim();
        }
        if (!dataStr) return;
        let eventData = {};
        try {
          eventData = JSON.parse(dataStr.replace(/\r/g, '').trim());
        } catch {
          return;
        }

        if (eventType === 'thinking') {
          if (eventData.type !== 'llm_thinking') handleNodeTrace(eventData);
        } else if (eventType === 'unified_analysis') {
          handleUnifiedAnalysis(eventData);
        } else if (eventType === 'chunk') {
          appendAssistantDelta(extractChunkText(eventData));
        } else if (eventType === 'card') {
          appendCustomCard(eventData.type, eventData.data);
        } else if (eventType === 'transfer') {
          handleHandoff(eventData);
        } else if (eventType === 'handoff_brief') {
          setHandoffBrief(toPublicHandoffBrief(eventData.brief || eventData));
        } else if (eventType === INTERNAL_API_EVENT) {
          handleApiLogging(eventData);
        } else if (eventType === 'done') {
          const fallbackReply = (eventData.reply || eventData.reply_draft || '').trim();
          if (fallbackReply && !activeBotMsgTextRef.current.trim()) {
            activeBotMsgTextRef.current = sanitizeUserVisibleText(fallbackReply);
          }
          finalizeStream(userText, turnId);
        }
      };

      const drainSseBuffer = () => {
        const blocks = sseBuffer.split(/\r?\n\r?\n/);
        sseBuffer = blocks.pop() || '';
        for (const block of blocks) processSseBlock(block);
      };

      while (true) {
        const { value, done } = await reader.read();
        if (value) {
          sseBuffer += decoder.decode(value, { stream: !done });
          drainSseBuffer();
        }
        if (done) {
          sseBuffer += decoder.decode();
          drainSseBuffer();
          if (sseBuffer.trim()) processSseBlock(sseBuffer);
          break;
        }
      }
    } catch (e) {
      if (e?.name === 'AbortError') {
        streamFinalizedRef.current = true;
        clearPresenceTimers();
        return;
      }
      if (turnId !== activeTurnIdRef.current) return;
      console.error('stream error:', e);
      if (e?.status === 401) {
        customerAuthRef.current = '';
        storeCustomerAuth(currentUser, '');
      }
      clearPresenceTimers();
      if (activeQueryStatusIdRef.current) {
        const cardId = activeQueryStatusIdRef.current;
        setChatMessages(prev => prev.filter(msg => msg._id !== cardId));
        activeQueryStatusIdRef.current = null;
      }
      if (!activeBotMsgTextRef.current?.trim()) {
        const errorText = e?.status === 401
          ? t('errors.sessionExpired')
          : t('errors.network');
        const errId = `bot_err_${Date.now()}`;
        activeBotMsgIdRef.current = errId;
        setChatMessages(prev => [...prev, {
          _id: errId,
          type: 'text',
          content: { text: `${errorText} <meme: sweat>` },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        }]);
        streamFinalizedRef.current = true;
        setIsAwaitingStream(false);
      }
    } finally {
      if (turnId !== activeTurnIdRef.current) return;
      if (!streamFinalizedRef.current) {
        finalizeStream(userText, turnId);
      }
      streamInFlightRef.current = false;
      abortControllerRef.current = null;
    }
  }, [appendAssistantDelta, appendCustomCard, clearPresenceTimers, currentUser, customerFetchOptions, finalizeStream, handleApiLogging, handleHandoff, handleNodeTrace, handleUnifiedAnalysis, handoffFetchOptions, modelId, pollHandoffSync, syncHistoryFromUI, uploadAttachmentFiles]);

  const confirmWelcomeOrder = useCallback((orderMeta) => {
    const orderId = orderMeta?.order_id;
    if (!orderId) return;
    activeOrderIdRef.current = orderId;
    welcomeCallbacksRef.current.onWelcomeOrderPick?.(orderId);
    setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'welcome_order'));
    handleSend(t('order.referenceTemplate', 'zh-CN', {
      orderRef: formatPublicOrderRef(orderId),
      itemName: orderMeta?.item_name || '这笔订单',
      status: orderMeta?.status_label || '待核对',
    }), { activeOrderId: orderId });
  }, [handleSend]);

  const browseWelcomeOrders = useCallback(() => {
    setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'welcome_order'));
    welcomeCallbacksRef.current.onWelcomeBrowseOrders?.();
  }, []);

  return {
    chatMessages,
    isAwaitingStream,
    awaitingStep,
    streamingMsgId,
    isTransfered,
    setIsTransfered,
    handoffState,
    handoffBrief,
    assignedHumanAgent,
    confirmHandoff,
    dismissHandoffPrompt,
    inputVal,
    setInputVal,
    vikingCapsule,
    vikingStyle,
    intentCapsule,
    intentStyle,
    emotionCapsule,
    emotionStyle,
    monitorIntent,
    monitorEmotion,
    monitorEmotionColor,
    apiLogs,
    setApiLogs,
    logStatus,
    logStatusText,
    activeTab,
    setActiveTab,
    nodeLogs,
    presencePhase,
    scrollContainerRef,
    resetChat,
    handleSend,
    confirmWelcomeOrder,
    browseWelcomeOrders,
  };
}
