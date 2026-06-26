import { useState, useRef, useCallback, useEffect } from 'react';
import t from '../i18n/index.js';
import { TEST_SCENARIOS } from '../constants/userOrders.js';
import { DEFAULT_ORDER_PRIORITY_WEIGHTS } from '../utils/orderHelpers.js';
import { buildLeftUserMeta, SPEAKER } from '../constants/chatSpeakers.js';
import { attachHandoffTransport } from './useHandoffSync.js';

/** 解析转人工系统消息的 i18n（后端 meta.i18n_key + i18n_params） */
function resolveHandoffSystemText(m) {
  const meta = m.meta || {};
  if (meta.i18n_key) {
    return t(meta.i18n_key, 'zh-CN', meta.i18n_params || {});
  }
  return m.content || '';
}

/** 从 SSE chunk 事件提取文本（兼容 content / text / delta） */
function extractChunkText(eventData) {
  const piece = eventData?.content ?? eventData?.text ?? eventData?.delta ?? '';
  return typeof piece === 'string' ? piece : String(piece ?? '');
}

/** 从 UI 消息重建多轮 history（SSE 竞态时的兜底） */
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
      hist.push({ role: 'assistant', content: `[人工] ${msg.content.text}` });
    }
  }
  return hist;
}

/** 将后端 node_start/node_end 事件规范化为前端 start/end 状态 */
function normalizeNodeStatus(data) {
  if (data.status === 'start' || data.status === 'end') return data.status;
  if (data.type === 'node_start') return 'start';
  if (data.type === 'node_end') return 'end';
  return data.status;
}

/**
 * SSE 聊天核心 Hook — 封装状态机、流式渲染与监控数据
 * @param {string} currentUser 当前演示用户 ID
 * @param {string} modelId 选用的 LLM 模型 ID
 */
export function useChatSSE(currentUser, modelId = 'deepseek-v4-flash', onTurnComplete = null, options = {}) {
  const {
    activeOrderId = null,
    streamReplyEnabled = false,
    orderPriorityWeights = DEFAULT_ORDER_PRIORITY_WEIGHTS,
    onWelcomeOrderPick = null,
    onWelcomeBrowseOrders = null,
  } = options;
  const activeOrderIdRef = useRef(activeOrderId);
  const streamReplyEnabledRef = useRef(streamReplyEnabled);
  const orderPriorityWeightsRef = useRef(orderPriorityWeights);
  const welcomeCallbacksRef = useRef({ onWelcomeOrderPick, onWelcomeBrowseOrders });

  useEffect(() => { activeOrderIdRef.current = activeOrderId; }, [activeOrderId]);
  useEffect(() => { streamReplyEnabledRef.current = streamReplyEnabled; }, [streamReplyEnabled]);
  useEffect(() => { orderPriorityWeightsRef.current = orderPriorityWeights; }, [orderPriorityWeights]);
  useEffect(() => {
    welcomeCallbacksRef.current = { onWelcomeOrderPick, onWelcomeBrowseOrders };
  }, [onWelcomeOrderPick, onWelcomeBrowseOrders]);
  const [chatMessages, setChatMessages] = useState([]);
  const [isAwaitingStream, setIsAwaitingStream] = useState(false);
  const [awaitingStep, setAwaitingStep] = useState('intent');
  const [streamingMsgId, setStreamingMsgId] = useState(null);
  const [isTransfered, setIsTransfered] = useState(false);
  const [handoffState, setHandoffState] = useState('none'); // none | prompt | queuing | connected
  const [handoffBrief, setHandoffBrief] = useState(null);
  const [assignedHumanAgent, setAssignedHumanAgent] = useState(null);
  const [inputVal, setInputVal] = useState('');

  const [vikingCapsule, setVikingCapsule] = useState('Viking: 未装载');
  const [vikingStyle, setVikingStyle] = useState('text-slate-500 bg-slate-100 border-slate-200/60');
  const [intentCapsule, setIntentCapsule] = useState('意图: 等待中');
  const [intentStyle, setIntentStyle] = useState('text-slate-500 bg-slate-100 border-slate-200/60');
  const [emotionCapsule, setEmotionCapsule] = useState('情绪: --');
  const [emotionStyle, setEmotionStyle] = useState('text-slate-500 bg-slate-100 border-slate-200/60');
  const [monitorIntent, setMonitorIntent] = useState('等待输入…');
  const [monitorEmotion, setMonitorEmotion] = useState('等待输入…');
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
  const handoffTokenRef = useRef('');
  const activeQueueIdRef = useRef(null);
  const handoffStateRef = useRef('none');
  const currentTurnUserValRef = useRef('');
  const lastIntentRef = useRef('');
  const lastEmotionRef = useRef(2);
  const chatMessagesRef = useRef([]);
  const abortControllerRef = useRef(null);
  const activeTurnIdRef = useRef(0);
  const readTimerRef = useRef(null);
  const typingTimerRef = useRef(null);
  const agentName = t('agent.name');
  const [presencePhase, setPresencePhase] = useState(null); // null | 'read' | 'typing'

  useEffect(() => { chatMessagesRef.current = chatMessages; }, [chatMessages]);

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

  /** 从 UI 消息快照同步 LLM 多轮 history（唯一可信来源） */
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
          next = [...next, {
            _id: sid,
            type: 'text',
            content: { text: resolveHandoffSystemText(m) },
            position: 'left',
            user: buildLeftUserMeta(SPEAKER.AI),
          }];
        } else if (m.role === 'human') {
          next = [...next, {
            _id: sid,
            type: 'text',
            content: { text: m.content },
            position: 'left',
            user: buildLeftUserMeta(SPEAKER.HUMAN, {
              agentId: m.agent_id || agent?.agent_id,
              name: agent?.name ? `专员${agent.name}` : undefined,
            }),
          }];
        } else if (m.role === 'observer') {
          next = [...next, {
            _id: sid,
            type: 'text',
            content: { text: m.content },
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
        const r = await fetch(`/api/v1/handoff/connect?session_id=${sessionId}`, { method: 'POST' });
        const data = r.ok ? await r.json() : null;
        if (!data?.ok || data?.status !== 'connected') return;
        agent = data.agent || agent;
        if (data.brief) setHandoffBrief(data.brief);
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
      const mr = await fetch(`/api/v1/handoff/messages/${sessionId}?since=${handoffMsgSinceRef.current}`);
      const md = mr.ok ? await mr.json() : null;
      if (md?.ok) ingestServerHandoffMessages(md.messages);
    } catch { /* 忽略 */ }
  }, [currentUser, ingestServerHandoffMessages]);

  const pollHandoffSync = useCallback(async () => {
    const sessionId = `session_${currentUser}`;
    const hs = handoffStateRef.current;
    if (hs !== 'queuing' && hs !== 'connected') return;

    try {
      const statusR = await fetch(`/api/v1/handoff/status/${sessionId}`);
      const statusData = statusR.ok ? await statusR.json() : null;
      if (statusData?.ok) {
        if (statusData.status === 'connected' && hs === 'queuing') {
          await completeHandoffConnection(activeQueueIdRef.current, statusData);
          return;
        }
        if (statusData.assigned_agent) setAssignedHumanAgent(statusData.assigned_agent);
      }

      if (handoffStateRef.current === 'connected' || statusData?.status === 'connected') {
        const msgR = await fetch(`/api/v1/handoff/messages/${sessionId}?since=${handoffMsgSinceRef.current}`);
        const msgData = msgR.ok ? await msgR.json() : null;
        if (msgData?.ok) ingestServerHandoffMessages(msgData.messages);
      }
    } catch { /* 忽略 */ }
  }, [completeHandoffConnection, currentUser, ingestServerHandoffMessages]);

  useEffect(() => {
    if (handoffState !== 'queuing' && handoffState !== 'connected') return undefined;
    const sessionId = `session_${currentUser}`;
    return attachHandoffTransport({
      sessionId,
      enabled: true,
      handoffToken: handoffTokenRef.current,
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
    setVikingCapsule('Viking: 未装载');
    setVikingStyle('text-slate-500 bg-slate-100 border-slate-200/60');
    setIntentCapsule('意图: 等待中');
    setIntentStyle('text-slate-500 bg-slate-100 border-slate-200/60');
    setEmotionCapsule('情绪: --');
    setEmotionStyle('text-slate-500 bg-slate-100 border-slate-200/60');
    setMonitorIntent('等待输入…');
    setMonitorEmotion('等待输入…');
    setMonitorEmotionColor('bg-slate-300');
    setNodeLogs([]);
    setApiLogs([]);
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
      fetch(`/api/v1/handoff/reset?session_id=session_${currentUser}`, { method: 'POST' }).catch(() => {});
    }
    activeTurnIdRef.current += 1;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    streamInFlightRef.current = false;
    streamFinalizedRef.current = false;
    historyDataRef.current = [];
    resetMonitor();

    const scanId = `welcome_scan_${Date.now()}`;
    setChatMessages([{
      _id: scanId,
      type: 'custom',
      content: { cardType: 'query_status', cardData: { step: 'query', streamReply: false } },
      position: 'left',
      user: buildLeftUserMeta(SPEAKER.AI),
    }]);

    try {
      const weightsJson = encodeURIComponent(JSON.stringify(orderPriorityWeightsRef.current));
      const res = await fetch(`/api/v1/welcome/${currentUser}?weights=${weightsJson}`);
      const data = res.ok ? await res.json() : null;
      await new Promise(r => setTimeout(r, 850));

      const msgs = [];
      if (data?.greeting) {
        msgs.push({
          _id: `welcome_greeting_${Date.now()}`,
          type: 'text',
          content: { text: data.greeting },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        });
      }
      if (data?.memory_line) {
        msgs.push({
          _id: `welcome_memory_${Date.now()}`,
          type: 'text',
          content: { text: data.memory_line },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        });
      }
      if (data?.order_line) {
        msgs.push({
          _id: `welcome_order_line_${Date.now()}`,
          type: 'text',
          content: { text: data.order_line },
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
              order_id: o.order_id,
              item_name: item?.name || o.order_id,
              status_label: o.status_label,
              status: o.status,
              reason: data.recommend_reason,
              thumb_emoji: item?.thumb_emoji,
              thumb_gradient: o.thumb_gradient,
            },
          },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        });
        welcomeCallbacksRef.current.onWelcomeOrderPick?.(o.order_id);
      }
      setChatMessages(msgs.length ? msgs : [{
        _id: `greeting_${Date.now()}`,
        type: 'text',
        content: { text: t(`greetings.${currentUser}`) },
        position: 'left',
        user: buildLeftUserMeta(SPEAKER.AI),
      }]);
    } catch (e) {
      console.error('welcome sequence failed:', e);
      setChatMessages([{
        _id: `greeting_${Date.now()}`,
        type: 'text',
        content: { text: t(`greetings.${currentUser}`) },
        position: 'left',
        user: buildLeftUserMeta(SPEAKER.AI),
      }]);
    }
  }, [agentName, currentUser, resetMonitor]);

  useEffect(() => { resetChat(); }, [currentUser, resetChat]);
  useEffect(() => { scrollToBottom(); }, [chatMessages, isAwaitingStream, streamingMsgId, scrollToBottom]);

  /** @deprecated 使用 syncHistoryFromUI — 保留兼容 handoff */
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

  /** 将助手回复写入 UI（有内容才建气泡，杜绝空气泡） */
  const revealAssistantMessage = useCallback((text, { streaming = false } = {}) => {
    const displayText = text ?? '';
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

  /** 累加 LLM 增量文本；流式模式实时刷新 UI */
  const appendAssistantDelta = useCallback((delta) => {
    if (!delta) return;
    if (activeQueryStatusIdRef.current && streamReplyEnabledRef.current) {
      const cardId = activeQueryStatusIdRef.current;
      setChatMessages(prev => prev.filter(msg => msg._id !== cardId));
      activeQueryStatusIdRef.current = null;
    }
    activeBotMsgTextRef.current += delta;
    if (streamReplyEnabledRef.current) {
      revealAssistantMessage(activeBotMsgTextRef.current, { streaming: true });
    }
  }, [revealAssistantMessage]);

  const appendCustomCard = useCallback((cardType, cardData) => {
    setChatMessages(prev => [...prev, {
      _id: `card_${Date.now()}`,
      type: 'custom',
      content: { cardType, cardData },
      position: 'left',
      user: buildLeftUserMeta(SPEAKER.AI),
    }]);
  }, []);

  const handleNodeTrace = useCallback((data) => {
    const nodeStatus = normalizeNodeStatus(data);
    setNodeLogs(prev => {
      const index = prev.findIndex(item => item.node === data.node);
      if (index === -1) return [...prev, { node: data.node, status: nodeStatus, desc: data.desc }];
      const next = [...prev];
      next[index] = { node: data.node, status: nodeStatus, desc: data.desc };
      return next;
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
      const levelMatch = data.desc.match(/级别=(L\d)/);
      const casesMatch = data.desc.match(/包含\s*(\d+)\s*条历史纠纷/);
      if (levelMatch) {
        const cases = casesMatch ? casesMatch[1] : '0';
        setVikingCapsule(`Viking: 已装载 ${levelMatch[1]} (${cases}条纠纷)`);
        setVikingStyle('text-emerald-600 bg-emerald-500/10 border-emerald-500/20');
      }
    }
  }, []);

  const handleUnifiedAnalysis = useCallback((data) => {
    setIntentCapsule(`意图: ${data.intent}`);
    setIntentStyle('text-indigo-500 bg-indigo-500/10 border-indigo-500/20');
    setMonitorIntent(data.intent);

    const emotionVal = data.emotion_level;
    let pillClass = 'text-emerald-600 bg-emerald-500/10 border-emerald-500/20';
    let text = `情绪: L${emotionVal} (平静)`;
    let mColor = 'bg-emerald-500';
    let mText = `Level ${emotionVal} (平静/感谢)`;

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
      mText = `Level ${emotionVal} (高危客诉/法务)`;
    }

    setEmotionCapsule(text);
    setEmotionStyle(pillClass);
    setMonitorEmotion(mText);
    setMonitorEmotionColor(mColor);
    lastEmotionRef.current = emotionVal;
    lastIntentRef.current = data.intent || '';

    // 后端已判定强制转人工时不再弹确认卡，避免与排队卡重复
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

  const handleApiLogging = useCallback((data) => {
    if (data.status === 'requesting') {
      setLogStatus('requesting');
      setLogStatusText(`请求中 (${data.attempt}/3)`);
      const cardId = `log_${data.stage}_${Date.now()}`;
      activeLogCardIdRef.current = cardId;
      const newLog = {
        id: cardId,
        stage: data.stage,
        model: data.model,
        api_key: data.api_key,
        attempt: data.attempt,
        payload: data.payload,
        responseStream: '连接中…\n',
        usage: null,
        duration: null,
        status: 'requesting',
      };
      apiLogsCacheRef.current[cardId] = newLog;
      setApiLogs(prev => [...prev, newLog]);
    } else if (data.status === 'chunk' && activeLogCardIdRef.current) {
      const cardId = activeLogCardIdRef.current;
      if (apiLogsCacheRef.current[cardId]) {
        const stream = apiLogsCacheRef.current[cardId].responseStream;
        const clean = stream.includes('连接中') ? '' : stream;
        apiLogsCacheRef.current[cardId].responseStream = clean + data.chunk + '\n';
        if (!apiLogThrottleTimerRef.current) {
          apiLogThrottleTimerRef.current = setTimeout(() => {
            setApiLogs(prev => prev.map(item => apiLogsCacheRef.current[item.id] ? { ...apiLogsCacheRef.current[item.id] } : item));
            apiLogThrottleTimerRef.current = null;
          }, 150);
        }
      }
    } else if (data.status === 'retrying' && activeLogCardIdRef.current) {
      setLogStatus('retrying');
      setLogStatusText(`重试中 (${data.attempt}/3)`);
      const cardId = activeLogCardIdRef.current;
      if (apiLogsCacheRef.current[cardId]) {
        apiLogsCacheRef.current[cardId].status = 'retrying';
        apiLogsCacheRef.current[cardId].attempt = data.attempt;
        apiLogsCacheRef.current[cardId].error_msg = data.error_msg;
      }
      setApiLogs(prev => prev.map(item => item.id === cardId ? { ...item, status: 'retrying', attempt: data.attempt, error_msg: data.error_msg } : item));
    } else if (data.status === 'success' && activeLogCardIdRef.current) {
      const cardId = activeLogCardIdRef.current;
      setLogStatus('success');
      setLogStatusText('已连接');
      if (apiLogThrottleTimerRef.current) {
        clearTimeout(apiLogThrottleTimerRef.current);
        apiLogThrottleTimerRef.current = null;
      }
      if (apiLogsCacheRef.current[cardId]) {
        apiLogsCacheRef.current[cardId].status = 'success';
        apiLogsCacheRef.current[cardId].usage = data.usage;
        apiLogsCacheRef.current[cardId].duration = data.duration;
      }
      setApiLogs(prev => prev.map(item => item.id === cardId ? { ...item, status: 'success', usage: data.usage, duration: data.duration, attempt: data.attempt } : item));
    } else if (data.status === 'error') {
      const cardId = activeLogCardIdRef.current || `log_${data.stage}_${Date.now()}`;
      activeLogCardIdRef.current = cardId;
      setLogStatus('error');
      setLogStatusText('调用失败');
      if (apiLogThrottleTimerRef.current) {
        clearTimeout(apiLogThrottleTimerRef.current);
        apiLogThrottleTimerRef.current = null;
      }
      const errorLog = {
        id: cardId,
        stage: data.stage || 'generate_reply',
        model: data.model,
        api_key: data.api_key,
        attempt: data.attempt || 1,
        payload: data.payload || null,
        responseStream: data.error_msg ? `ERROR: ${data.error_msg}\n` : 'ERROR: LLM 调用失败\n',
        usage: null,
        duration: data.duration || null,
        status: 'error',
        error_msg: data.error_msg,
      };
      apiLogsCacheRef.current[cardId] = errorLog;
      setApiLogs(prev => {
        const exists = prev.some(item => item.id === cardId);
        return exists
          ? prev.map(item => item.id === cardId ? { ...item, ...errorLog } : item)
          : [...prev, errorLog];
      });
    }
  }, []);

  const startHandoffQueue = useCallback((reason, brief = null, queueMeta = null) => {
    const hs = handoffStateRef.current;
    if (hs === 'queuing' || hs === 'connected') return;

    handoffMsgSinceRef.current = 0;
    handoffSyncedIdsRef.current = new Set();
    setHandoffState('queuing');
    if (brief) setHandoffBrief(brief);
    setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'handoff_prompt'));

    const queueId = `handoff_queue_${Date.now()}`;
    activeQueueIdRef.current = queueId;
    const position = queueMeta?.position ?? 2;
    const ahead = queueMeta?.ahead ?? 1;
    const eta = queueMeta?.eta ?? queueMeta?.eta_minutes ?? 2;

    setChatMessages(prev => [...prev, {
      _id: queueId,
      type: 'custom',
      content: {
        cardType: 'handoff_queue',
        cardData: { position, ahead, eta, reason: reason || '用户申请人工协助' },
      },
      position: 'left',
      user: buildLeftUserMeta(SPEAKER.AI),
    }]);
  }, []);

  const confirmHandoff = useCallback(async () => {
    const sessionId = `session_${currentUser}`;
    try {
      const res = await fetch('/api/v1/handoff/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: currentUser,
          session_id: sessionId,
          history: historyDataRef.current,
          reason: '用户主动申请人工客服',
          last_user_message: currentTurnUserValRef.current || '',
          intent: lastIntentRef.current,
          emotion_level: lastEmotionRef.current,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.handoff_token) handoffTokenRef.current = data.handoff_token;
        startHandoffQueue(data.reason, data.brief, data.queue);
        return;
      }
      console.error('handoff request failed:', res.status);
    } catch (e) {
      console.error('handoff request failed:', e);
    }
  }, [currentUser, startHandoffQueue]);

  const dismissHandoffPrompt = useCallback(() => {
    setHandoffState('none');
    setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'handoff_prompt'));
  }, []);

  const handleHandoff = useCallback((eventData = {}) => {
    cleanupStreamUI();

    const brief = eventData.brief || null;
    const reason = eventData.reason || '系统判定需人工介入';
    if (brief) setHandoffBrief(brief);

    if (!activeBotMsgTextRef.current?.trim()) {
      activeBotMsgTextRef.current = '这件事超出了虾饺的权限范围，已为您加急联系人类客服，排队期间您仍可继续发消息～ <meme: run>';
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

    const finalText = activeBotMsgTextRef.current.trim();
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

  const handleSend = useCallback(async (val) => {
    if (!val.trim() || streamInFlightRef.current) return;

    // 已接入人工：消息写入服务端，由轮询同步专员/旁听回复
    if (handoffStateRef.current === 'connected' && isTransfered) {
      const sessionId = `session_${currentUser}`;
      setChatMessages(prev => [...prev, {
        _id: `user_${Date.now()}`,
        type: 'text',
        content: { text: val },
        position: 'right',
      }]);
      historyDataRef.current.push({ role: 'user', content: val });
      try {
        await fetch('/api/v1/handoff/user-message', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, content: val, user_id: currentUser }),
        });
        await pollHandoffSync();
      } catch (e) {
        console.error('handoff user-message failed:', e);
      }
      return;
    }

    currentTurnUserValRef.current = val;
    const turnId = activeTurnIdRef.current + 1;
    activeTurnIdRef.current = turnId;
    streamInFlightRef.current = true;
    streamFinalizedRef.current = false;
    clearPresenceTimers();

    abortControllerRef.current = new AbortController();

    // 发送前：从 UI 快照重建 history（不含本条用户消息，后端会 append content）
    syncHistoryFromUI();

    // 用户继续发消息时收起未操作的转人工确认卡
    if (handoffStateRef.current === 'prompt') {
      setHandoffState('none');
      setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'handoff_prompt'));
    }

    setChatMessages(prev => [...prev, {
      _id: `user_${Date.now()}`,
      type: 'text',
      content: { text: val },
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
      const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abortControllerRef.current.signal,
        body: JSON.stringify({
          user_id: currentUser,
          session_id: `session_${currentUser}`,
          content: val,
          history: historyDataRef.current,
          model_id: modelId,
          active_order_id: activeOrderIdRef.current,
          stream_reply: streamReplyEnabledRef.current,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
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
          if (!streamReplyEnabledRef.current) {
            if (typingTimerRef.current) {
              clearTimeout(typingTimerRef.current);
              typingTimerRef.current = null;
            }
            setPresencePhase('typing');
            setAwaitingStep('reply');
          }
        } else if (eventType === 'chunk') {
          appendAssistantDelta(extractChunkText(eventData));
        } else if (eventType === 'card') {
          appendCustomCard(eventData.type, eventData.data);
        } else if (eventType === 'transfer') {
          handleHandoff(eventData);
        } else if (eventType === 'handoff_brief') {
          setHandoffBrief(eventData.brief || eventData);
        } else if (eventType === 'api_log') {
          handleApiLogging(eventData);
        } else if (eventType === 'done') {
          const fallbackReply = (eventData.reply || eventData.reply_draft || '').trim();
          if (fallbackReply && !activeBotMsgTextRef.current.trim()) {
            activeBotMsgTextRef.current = fallbackReply;
          }
          finalizeStream(val, turnId);
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
      console.error('SSE error:', e);
      clearPresenceTimers();
      if (activeQueryStatusIdRef.current) {
        const cardId = activeQueryStatusIdRef.current;
        setChatMessages(prev => prev.filter(msg => msg._id !== cardId));
        activeQueryStatusIdRef.current = null;
      }
      if (!activeBotMsgTextRef.current?.trim()) {
        const errId = `bot_err_${Date.now()}`;
        activeBotMsgIdRef.current = errId;
        setChatMessages(prev => [...prev, {
          _id: errId,
          type: 'text',
          content: { text: `${t('errors.network')} <meme: sweat>` },
          position: 'left',
          user: buildLeftUserMeta(SPEAKER.AI),
        }]);
        streamFinalizedRef.current = true;
        setIsAwaitingStream(false);
      }
    } finally {
      if (turnId !== activeTurnIdRef.current) return;
      if (!streamFinalizedRef.current) {
        finalizeStream(val, turnId);
      }
      streamInFlightRef.current = false;
      abortControllerRef.current = null;
    }
  }, [appendAssistantDelta, appendCustomCard, clearPresenceTimers, currentUser, finalizeStream, handleApiLogging, handleHandoff, handleNodeTrace, handleUnifiedAnalysis, isTransfered, modelId, pollHandoffSync, syncHistoryFromUI]);

  const confirmWelcomeOrder = useCallback((orderMeta) => {
    const orderId = orderMeta?.order_id;
    if (!orderId) return;
    welcomeCallbacksRef.current.onWelcomeOrderPick?.(orderId);
    setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'welcome_order'));
    handleSend(t('order.referenceTemplate', 'zh-CN', { orderId }));
  }, [handleSend]);

  const browseWelcomeOrders = useCallback(() => {
    setChatMessages(prev => prev.filter(m => m.content?.cardType !== 'welcome_order'));
    welcomeCallbacksRef.current.onWelcomeBrowseOrders?.();
  }, []);

  const handleSwitchUser = useCallback((userId, onUserChange) => {
    activeTurnIdRef.current += 1;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    historyDataRef.current = [];
    if (streamFlushRafRef.current) cancelAnimationFrame(streamFlushRafRef.current);
    streamFlushRafRef.current = null;
    activeBotMsgIdRef.current = null;
    activeBotMsgTextRef.current = '';
    activeQueryStatusIdRef.current = null;
    streamInFlightRef.current = false;
    setIsAwaitingStream(false);
    setStreamingMsgId(null);
    clearPresenceTimers();
    onUserChange(userId);
  }, [clearPresenceTimers]);

  const runTestCase = useCallback((caseIndex, onUserChange) => {
    const scenario = TEST_SCENARIOS[caseIndex];
    if (!scenario) return;
    handleSwitchUser(scenario.userId, onUserChange);
    let stepIdx = 0;
    const runNext = () => {
      if (stepIdx >= scenario.messages.length) return;
      const text = scenario.messages[stepIdx];
      const trySend = () => {
        if (streamInFlightRef.current) {
          setTimeout(trySend, 800);
          return;
        }
        handleSend(text);
        stepIdx += 1;
        if (stepIdx < scenario.messages.length) setTimeout(runNext, 6500);
      };
      setTimeout(trySend, 500);
    };
    setTimeout(runNext, 800);
  }, [handleSend, handleSwitchUser]);

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
    handleSwitchUser,
    runTestCase,
    confirmWelcomeOrder,
    browseWelcomeOrders,
  };
}
