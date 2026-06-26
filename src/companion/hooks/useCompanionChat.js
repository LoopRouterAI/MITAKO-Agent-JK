import React, { useCallback, useEffect, useRef, useState } from 'react';
import { expandAdventureMentions, expandGalgameSlash } from '../adventureMentions.js';
import { companionFetch, absorbCompanionToken } from '../../lib/companionClient.js';
import t from '../../i18n/index.js';

/** Companion SSE 对话 + 右侧 Monitor 状态（对齐客服 Agent） */
export function useCompanionChat(userId, modelId = 'deepseek-v4-flash') {
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [persona, setPersona] = useState(null);
  const [watchOrders, setWatchOrders] = useState([]);
  const [wishlist, setWishlist] = useState([]);
  const [apiLogs, setApiLogs] = useState([]);
  const [nodeLogs, setNodeLogs] = useState([]);
  const [logStatus, setLogStatus] = useState('idle');
  const [activeTab, setActiveTab] = useState('reasoning');
  const [monitorEmotion, setMonitorEmotion] = useState({ level: 3, label: '平稳' });
  const [monitorEmotionColor, setMonitorEmotionColor] = useState('#7B61FF');
  const [monitorSafety, setMonitorSafety] = useState({ status: 'pass', reason: '' });
  const [memoryItems, setMemoryItems] = useState([]);
  const [memoryCapsule, setMemoryCapsule] = useState('记忆: 加载中');
  const [memoryStyle, setMemoryStyle] = useState('text-slate-500 bg-slate-100 border-slate-200/60');
  const [adventureActive, setAdventureActive] = useState(false);
  const [adventureSession, setAdventureSession] = useState(null);
  const [adventureMessages, setAdventureMessages] = useState([]);
  const [adventureLoading, setAdventureLoading] = useState(null);
  const [adventureEnterRequest, setAdventureEnterRequest] = useState(null);
  const [lastChoices, setLastChoices] = useState([]);
  const scrollRef = useRef(null);
  const adventureStreamIdRef = useRef(null);

  const loadPersona = useCallback(async () => {
    const r = await companionFetch(`/api/v2/companion/persona/${encodeURIComponent(userId)}`);
    const data = await r.json();
    if (data.ok) setPersona(data.persona);
  }, [userId]);

  const loadMessages = useCallback(async () => {
    const r = await companionFetch(`/api/v2/companion/messages/${encodeURIComponent(userId)}?limit=50`);
    const data = await r.json();
    if (data.ok) setMessages(data.messages || []);
  }, [userId]);

  const loadWatchOrders = useCallback(async () => {
    const r = await companionFetch(`/api/v2/companion/watch/orders/${encodeURIComponent(userId)}`);
    const data = await r.json();
    if (data.ok) setWatchOrders(data.orders || []);
  }, [userId]);

  const loadWishlist = useCallback(async () => {
    const r = await companionFetch(`/api/v2/companion/wishlist/${encodeURIComponent(userId)}`);
    const data = await r.json();
    if (data.ok) setWishlist(data.items || []);
  }, [userId]);

  const loadMemories = useCallback(async () => {
    const r = await companionFetch(`/api/v2/companion/memory/${encodeURIComponent(userId)}?limit=30`);
    const data = await r.json();
    if (!data.ok) return;
    const items = data.items || [];
    setMemoryItems(items);
    const total = data.total || items.length;
    const level = data.viking_level || 'L0';
    if (total > 0) {
      setMemoryCapsule(`OpenViking: ${level} · ${total} 条`);
      setMemoryStyle('text-emerald-600 bg-emerald-500/10 border-emerald-500/20');
    } else {
      setMemoryCapsule('OpenViking: 待积累');
      setMemoryStyle('text-slate-500 bg-slate-100 border-slate-200/60');
    }
  }, [userId]);

  const loadAdventureSession = useCallback(async () => {
    const r = await companionFetch(`/api/v2/companion/adventure/session/${encodeURIComponent(userId)}`);
    const data = await r.json();
    if (!data.ok) return;
    const sess = data.session;
    setAdventureSession(sess);
    setAdventureActive(Boolean(sess?.active));
  }, [userId]);

  const loadAdventureMessages = useCallback(async () => {
    const r = await companionFetch(`/api/v2/companion/adventure/messages/${encodeURIComponent(userId)}?limit=80`);
    const data = await r.json();
    if (!data.ok) return;
    const msgs = data.messages || [];
    setAdventureMessages(msgs);
    const lastAssistant = [...msgs].reverse().find(m => m.role === 'assistant');
    setLastChoices(lastAssistant?.choices || []);
  }, [userId]);

  useEffect(() => {
    loadPersona();
    loadMessages();
    loadWatchOrders();
    loadWishlist();
    loadMemories();
    loadAdventureSession().then(() => loadAdventureMessages());
  }, [loadPersona, loadMessages, loadWatchOrders, loadWishlist, loadMemories, loadAdventureSession, loadAdventureMessages]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: streaming ? 'auto' : 'smooth' });
  }, [messages, adventureMessages, streaming, adventureActive, lastChoices]);

  const savePersona = async (body) => {
    const r = await companionFetch(`/api/v2/companion/persona/${encodeURIComponent(userId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, model_id: modelId }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'save_failed');
    absorbCompanionToken(data);
    setPersona(data.persona);
    return data.persona;
  };

  const addWatchOrder = async (orderId, notifyOn = 'status_change') => {
    const r = await companionFetch('/api/v2/companion/watch/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, order_id: orderId, notify_on: notifyOn }),
    });
    const data = await r.json();
    if (!data.ok) throw new Error('watch_failed');
    await loadWatchOrders();
    return data.watch;
  };

  const addWishlistItem = async (productId, note = '') => {
    const r = await companionFetch('/api/v2/companion/wishlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, product_id: productId, note }),
    });
    const data = await r.json();
    if (!data.ok) throw new Error('wishlist_failed');
    await loadWishlist();
    return data.item;
  };

  const searchProducts = async (q) => {
    const r = await companionFetch(`/api/v2/companion/products/search?q=${encodeURIComponent(q)}&limit=8`);
    const data = await r.json();
    return data.ok ? (data.products || []) : [];
  };

  const appendCustomCard = useCallback((cardType, cardData, target = 'normal') => {
    const item = {
      id: `card_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      role: 'assistant',
      type: 'custom',
      content: { cardType, cardData },
    };
    if (target === 'adventure') {
      setAdventureMessages(prev => [...prev, item]);
    } else {
      setMessages(prev => [...prev, item]);
    }
  }, []);

  const executeTool = useCallback(async (action, payload = {}) => {
    const r = await companionFetch('/api/v2/companion/tools/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, action, payload }),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.detail || 'tool_failed');
    return data.result;
  }, [userId]);

  const onWatchSubmit = useCallback(async ({ order_id }) => {
    await executeTool('watch_order', { order_id });
    await loadWatchOrders();
  }, [executeTool, loadWatchOrders]);

  const onProductSearch = useCallback(async ({ query }) => {
    const result = await executeTool('search_products', { query });
    return result?.products || [];
  }, [executeTool]);

  const onAddWishlist = useCallback(async ({ product_id, note }) => {
    await executeTool('add_wishlist', { product_id, note: note || '' });
    await loadWishlist();
  }, [executeTool, loadWishlist]);

  const setMode = async (mode) => {
    const r = await companionFetch(`/api/v2/companion/persona/${encodeURIComponent(userId)}/mode`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    const data = await r.json();
    if (data.ok) setPersona(data.persona);
    return data.persona;
  };

  const processSseBlock = (block, handlers) => {
    block = block.trim();
    if (!block) return;
    let eventType = 'message';
    let dataStr = '';
    for (const line of block.split('\n')) {
      const trimmed = line.trim();
      if (trimmed.startsWith('event:')) eventType = trimmed.substring(6).trim();
      else if (trimmed.startsWith('data:')) dataStr = trimmed.substring(5).trim();
    }
    if (!dataStr) return;
    let payload = {};
    try {
      payload = JSON.parse(dataStr.replace(/\r/g, '').trim());
    } catch {
      return;
    }
    handlers(eventType, payload);
  };

  const consumeSseStream = async (res, handleEvent) => {
    if (!res.body) throw new Error('empty_body');
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || '';
      for (const block of blocks) processSseBlock(block, handleEvent);
    }
    if (buffer.trim()) processSseBlock(buffer, handleEvent);
  };

  /** Talkie 式分档清除冒险上下文 — messages | chapter */
  const resetAdventureContext = useCallback(async (mode = 'messages') => {
    if (streaming) return;
    const r = await companionFetch('/api/v2/companion/adventure/reset-context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, mode }),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.detail || 'reset_adventure_failed');
    setAdventureMessages([]);
    setLastChoices([]);
    setApiLogs(prev => prev.filter(l => l.stage !== 'adventure_review'));
    const toastKey = mode === 'chapter' ? 'adventureResetDoneChapter' : 'adventureResetDoneMessages';
    setAdventureMessages([{
      id: `sys_${Date.now()}`,
      role: 'assistant',
      mode: 'adventure',
      content: t(`companion.${toastKey}`),
      systemNotice: true,
    }]);
    return data;
  }, [userId, streaming]);

  const clearChat = useCallback(async () => {
    if (streaming) return;
    if (adventureActive) {
      return resetAdventureContext('messages');
    }
    const r = await companionFetch(`/api/v2/companion/messages/${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.detail || 'clear_failed');
    setMessages([]);
    setApiLogs([]);
    setNodeLogs([]);
    setLogStatus('idle');
    setMonitorEmotion({ level: 3, label: '平稳' });
    await loadMemories();
  }, [userId, streaming, adventureActive, loadMemories, resetAdventureContext]);

  const handleMemoryEvent = useCallback((payload) => {
    if (payload.items) setMemoryItems(payload.items);
    if (payload.line) {
      setMemoryCapsule(payload.line);
      const total = payload.total || (payload.items || []).length;
      setMemoryStyle(
        total > 0 || payload.viking_level
          ? 'text-emerald-600 bg-emerald-500/10 border-emerald-500/20'
          : 'text-slate-500 bg-slate-100 border-slate-200/60',
      );
    }
    if (payload.status === 'saved') {
      loadMemories();
    }
  }, [loadMemories]);

  const buildAdventureEventHandler = (cardTarget = 'adventure') => {
    let gotReply = false;
    const pushNode = (node, status, desc) => {
      setNodeLogs(prev => [...prev, { node, status, desc }]);
    };
    const patchAdventureMsg = (messageId, patch) => {
      if (!messageId) return;
      setAdventureMessages(prev => prev.map(m => (m.id === messageId ? { ...m, ...patch } : m)));
    };
    return (eventType, payload) => {
      if (eventType === 'safety') {
        setMonitorSafety({ status: payload.status, reason: payload.reason || '' });
        pushNode('safety_fence', 'end', `${payload.layer || 'check'} · ${payload.status} · ${payload.reason || 'pass'}`);
      } else if (eventType === 'review') {
        const r = payload.result || {};
        pushNode(
          `review_${payload.phase || '?'}`,
          'end',
          `${r.action || 'PASS'} · ${r.code || ''} · ${r.reason || 'ok'}`,
        );
      } else if (eventType === 'api_log') {
        const log = {
          ...payload,
          id: payload.id || `advlog_${Date.now()}`,
          payload: payload.payload || {},
          responseStream: payload.responseStream ?? '',
        };
        setApiLogs(prev => [log, ...prev].slice(0, 16));
        if (payload.stage?.includes('review')) {
          pushNode(payload.stage, 'end', log.responseStream?.slice(0, 80) || log.status);
        } else if (payload.stage === 'adventure_narrative') {
          pushNode('adventure_narrative', 'end', `叙事完成 · ${log.duration || 0}ms`);
        } else if (payload.stage?.startsWith('adventure_illust')) {
          pushNode(payload.stage, 'end', log.responseStream?.slice(0, 80) || log.status);
        }
      } else if (eventType === 'bible_ready') {
        pushNode('world_bible', 'end', payload.bible?.era_label || 'bible');
      } else if (eventType === 'illust_queued' || eventType === 'illust_generating') {
        patchAdventureMsg(payload.message_id, {
          illust: { status: eventType === 'illust_generating' ? 'generating' : 'queued' },
        });
      } else if (eventType === 'illust_ready') {
        patchAdventureMsg(payload.message_id, {
          illust: {
            status: 'ready',
            url: payload.url,
            aspect: payload.aspect,
            size: payload.size,
            asset_id: payload.asset_id,
          },
        });
      } else if (eventType === 'illust_failed' || eventType === 'illust_skipped') {
        if (eventType === 'illust_failed') {
          patchAdventureMsg(payload.message_id, { illust: { status: 'failed' } });
        }
      } else if (eventType === 'card') {
        appendCustomCard(payload.type, payload.data || {}, cardTarget);
      } else if (eventType === 'loading') {
        setAdventureLoading({
          world: payload.world || '',
          phase: payload.phase || 'rift',
          progress: payload.progress || 0,
        });
        if (payload.phase === 'ready') {
          setTimeout(() => setAdventureLoading(null), 900);
        }
      } else if (eventType === 'session') {
        setAdventureSession(payload.session || null);
        setAdventureActive(Boolean(payload.session?.active));
      } else if (eventType === 'choices') {
        setLastChoices(payload.choices || []);
      } else if (eventType === 'chunk') {
        setAdventureLoading(prev => (prev
          ? { ...prev, phase: 'narrative', progress: Math.max(prev.progress || 0, 72) }
          : prev));
        const sid = adventureStreamIdRef.current || `stream_${Date.now()}`;
        adventureStreamIdRef.current = sid;
        const content = payload.content ?? '';
        setAdventureMessages(prev => {
          const idx = prev.findIndex(m => m.id === sid);
          if (idx >= 0) {
            return prev.map(m => (m.id === sid ? { ...m, content, streaming: true } : m));
          }
          return [...prev, { id: sid, role: 'assistant', content, streaming: true, mode: 'adventure' }];
        });
      } else if (eventType === 'adventure_exit') {
        setAdventureActive(false);
        setAdventureSession(prev => (prev ? { ...prev, active: false } : null));
        setLastChoices([]);
        if (payload.message) {
          setMessages(prev => [...prev, {
            id: `sys_${Date.now()}`,
            role: 'assistant',
            content: payload.message,
          }]);
        }
      } else if (eventType === 'message') {
        gotReply = true;
        const choices = payload.choices || [];
        setLastChoices(choices);
        adventureStreamIdRef.current = null;
        setAdventureMessages(prev => {
          const base = prev.filter(m => !m.streaming);
          return [...base, {
            id: payload.id || Date.now(),
            role: payload.role || 'assistant',
            content: payload.content,
            mode: 'adventure',
            inner: payload.inner || null,
            dialogues: payload.dialogues || null,
            tts_plain: payload.tts_plain || null,
            illust: payload.illust
              ? { status: payload.illust.status || 'queued', type: payload.illust.type, ...payload.illust }
              : null,
          }];
        });
      } else if (eventType === 'done') {
        setLogStatus('ok');
        setStreaming(false);
      }
      return gotReply;
    };
  };

  const startAdventure = async (worldSetting) => {
    if (streaming) return;
    setStreaming(true);
    setLogStatus('requesting');
    setAdventureMessages([]);
    setLastChoices([]);
    setAdventureLoading({ world: worldSetting, phase: 'rift', progress: 6 });
    const streamId = `stream_${Date.now()}`;
    adventureStreamIdRef.current = streamId;
    setAdventureMessages([{ id: streamId, role: 'assistant', content: '', streaming: true, mode: 'adventure' }]);
    setNodeLogs([]);
    setApiLogs([]);
    setActiveTab('reasoning');
    let gotReply = false;

    try {
      const r = await companionFetch('/api/v2/companion/adventure/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          world_setting: worldSetting,
          world_title: worldSetting.slice(0, 24),
          model_id: modelId,
        }),
      });
      if (!r.ok) throw new Error(`adventure_start_${r.status}`);

      const handler = buildAdventureEventHandler('adventure');
      await consumeSseStream(r, (eventType, payload) => {
        handler(eventType, payload);
        if (eventType === 'message') gotReply = true;
        if (eventType === 'done') setStreaming(false);
      });

      await loadAdventureSession();
      if (!gotReply) throw new Error('no_opening');
      setLogStatus('ok');
    } catch (e) {
      console.error(e);
      setLogStatus('error');
      setAdventureActive(false);
      setAdventureLoading(null);
      throw e;
    } finally {
      setStreaming(false);
    }
  };

  const exitAdventure = async () => {
    if (streaming) return;
    try {
      await companionFetch('/api/v2/companion/adventure/exit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, message: '/退出冒险', model_id: modelId }),
      });
    } catch (e) {
      console.error(e);
    }
    setAdventureActive(false);
    setAdventureSession(prev => (prev ? { ...prev, active: false } : null));
    setLastChoices([]);
    setMessages(prev => [...prev, {
      id: `sys_${Date.now()}`,
      role: 'assistant',
      content: '已退出冒险模式～日常陪伴的记忆还在，我们继续聊吧。',
    }]);
  };

  const sendAdventureMessage = async (text, { choiceId, choicePick } = {}) => {
    const content = text.trim();
    if (!content || streaming || !adventureActive) return;

    const exitCmds = ['/退出冒险', '/退出', '/exit', '/结束冒险', '/quit', '退出冒险'];
    if (exitCmds.includes(content) || exitCmds.includes(content.toLowerCase())) {
      await exitAdventure();
      return;
    }

    const apiMessage = expandAdventureMentions(expandGalgameSlash(content), persona);

    setStreaming(true);
    setLogStatus('requesting');
    setNodeLogs([]);
    setActiveTab('reasoning');
    setLastChoices([]);
    const tempId = `u_${Date.now()}`;
    const streamId = `stream_${Date.now()}`;
    adventureStreamIdRef.current = streamId;
    setAdventureMessages(prev => [
      ...prev,
      {
        id: tempId,
        role: 'user',
        content,
        mode: 'adventure',
        choiceId,
        choicePick: Boolean(choicePick),
      },
      { id: streamId, role: 'assistant', content: '', streaming: true, mode: 'adventure' },
    ]);
    let gotReply = false;

    try {
      const res = await companionFetch('/api/v2/companion/adventure/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, message: apiMessage, model_id: modelId }),
      });
      if (!res.ok) throw new Error(`adventure_chat_${res.status}`);

      const handler = buildAdventureEventHandler('adventure');
      await consumeSseStream(res, (eventType, payload) => {
        handler(eventType, payload);
        if (eventType === 'message') gotReply = true;
        if (eventType === 'adventure_exit') gotReply = true;
      });

      if (!gotReply) {
        setAdventureMessages(prev => [...prev, {
          id: Date.now(),
          role: 'assistant',
          content: '故事书页卡了一下～再选一次选项或重新输入吧。',
          mode: 'adventure',
        }]);
        setLogStatus('error');
      } else {
        setLogStatus('ok');
      }
    } catch (e) {
      console.error(e);
      setLogStatus('error');
      setAdventureMessages(prev => [...prev, {
        id: Date.now(),
        role: 'assistant',
        content: '冒险线路暂时中断，但我还在～请再试一次，或输入 /退出冒险 回到日常。',
        mode: 'adventure',
      }]);
    } finally {
      setStreaming(false);
    }
  };

  const sendAdventureChoice = (choice) => {
    if (!choice || streaming || !adventureActive) return;
    const label = choice.label || String(choice.id);
    sendAdventureMessage(label, { choiceId: choice.id, choicePick: true });
  };

  const loadShareCatalog = async () => {
    const r = await companionFetch('/api/v2/companion/share/catalog?limit=12');
    const data = await r.json();
    if (!data.ok) return { skus: [], articles: [] };
    return { skus: data.skus || [], articles: data.articles || [] };
  };

  const simulateShareFromApp = useCallback(async (type = 'sku') => {
    try {
      const catalog = await loadShareCatalog();
      const pool = type === 'article' ? (catalog.articles || []) : (catalog.skus || []);
      const item = pool[0];
      if (!item) return;
      const target = adventureActive ? 'adventure' : 'normal';
      appendCustomCard('companion_share', { ...item, source: 'mitako_app' }, target);
    } catch (e) {
      console.error(e);
    }
  }, [adventureActive, appendCustomCard]);

  const showShareCatalog = useCallback(async () => {
    await simulateShareFromApp('sku');
  }, [simulateShareFromApp]);

  const sendMessage = async (text) => {
    const content = text.trim();
    if (!content || streaming) return;

    const helpCmds = ['/help', '/帮助', '/指令'];
    if (helpCmds.includes(content.toLowerCase())) {
      const helpText = adventureActive
        ? '冒险指令：/退出冒险 · 输入 1/2/3 选选项 · 自由输入推进剧情'
        : '可用指令：/冒险 [世界观] · /订单 [订单号] · /help';
      const push = adventureActive ? setAdventureMessages : setMessages;
      push(prev => [...prev, { id: `help_${Date.now()}`, role: 'assistant', content: helpText }]);
      return;
    }

    const enterWorld = content.match(/^\/(?:冒险|adventure|进入冒险)\s*(.*)$/i);
    if (enterWorld && !adventureActive) {
      const world = (enterWorld[1] || '').trim() || '自由幻想世界';
      setAdventureEnterRequest({ world });
      return;
    }

    if (adventureActive) {
      await sendAdventureMessage(content);
      return;
    }

    setStreaming(true);
    setLogStatus('requesting');
    setNodeLogs([]);
    const tempId = `u_${Date.now()}`;
    setMessages(prev => [...prev, { id: tempId, role: 'user', content }]);
    let gotReply = false;

    try {
      const res = await companionFetch('/api/v2/companion/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, message: content, model_id: modelId }),
      });
      if (!res.ok) throw new Error(`chat_failed_${res.status}`);
      if (!res.body) throw new Error('empty_body');

      let gotReply = false;

      const handleEvent = (eventType, payload) => {
        if (eventType === 'thinking') {
          const node = payload.node || 'graph';
          const desc = payload.desc || '';
          if (payload.type === 'node_start') {
            setNodeLogs(prev => [...prev, { node, status: 'start', desc }]);
          } else {
            setNodeLogs(prev => [...prev, { node, status: 'end', desc }]);
          }
        } else if (eventType === 'emotion') {
          setMonitorEmotion({ level: payload.level, label: payload.label });
          if (payload.color) setMonitorEmotionColor(payload.color);
        } else if (eventType === 'safety') {
          setMonitorSafety({ status: payload.status, reason: payload.reason || '' });
        } else if (eventType === 'api_log') {
          setApiLogs(prev => [payload, ...prev].slice(0, 12));
        } else if (eventType === 'memory') {
          handleMemoryEvent(payload);
        } else if (eventType === 'mode_switch') {
          setPersona(prev => (prev ? { ...prev, agent_mode: payload.mode } : prev));
        } else if (eventType === 'card') {
          appendCustomCard(payload.type, payload.data || {});
        } else if (eventType === 'message') {
          gotReply = true;
          setMessages(prev => [...prev, { id: payload.id || Date.now(), role: 'assistant', content: payload.content }]);
        } else if (eventType === 'done') {
          setLogStatus('ok');
        }
      };

      await consumeSseStream(res, handleEvent);

      if (!gotReply) {
        const fallback = '我在呢～刚才有点卡顿，你可以再说一遍吗？';
        setMessages(prev => [...prev, { id: Date.now(), role: 'assistant', content: fallback }]);
        setLogStatus('error');
      } else {
        setLogStatus('ok');
      }
      await loadPersona();
    } catch (e) {
      console.error(e);
      setLogStatus('error');
      setMessages(prev => [...prev, {
        id: Date.now(),
        role: 'assistant',
        content: '连接出了点问题，但我还在～请再试一次。',
      }]);
    } finally {
      setStreaming(false);
    }
  };

  const clearAdventureEnterRequest = useCallback(() => setAdventureEnterRequest(null), []);

  const logStatusText = logStatus === 'requesting' ? '请求中…'
    : logStatus === 'error' ? '异常'
    : logStatus === 'ok' ? '完成'
    : '待命';

  return {
    messages: adventureActive ? adventureMessages : messages,
    persona,
    streaming,
    watchOrders,
    wishlist,
    savePersona,
    sendMessage,
    startAdventure,
    exitAdventure,
    sendAdventureMessage,
    sendAdventureChoice,
    loadShareCatalog,
    showShareCatalog,
    simulateShareFromApp,
    adventureLoading,
    adventureEnterRequest,
    clearAdventureEnterRequest,
    adventureActive,
    adventureSession,
    lastChoices,
    addWatchOrder,
    addWishlistItem,
    searchProducts,
    setMode,
    reload: loadMessages,
    scrollRef,
    apiLogs,
    setApiLogs,
    nodeLogs,
    logStatus,
    logStatusText,
    activeTab,
    setActiveTab,
    monitorEmotion,
    monitorEmotionColor,
    monitorSafety,
    memoryItems,
    memoryCapsule,
    memoryStyle,
    clearChat,
    resetAdventureContext,
    cardCallbacks: {
      onWatchSubmit,
      onProductSearch,
      onAddWishlist,
    },
  };
}
