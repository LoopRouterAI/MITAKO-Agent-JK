import React, { useState, useEffect, useCallback, useRef } from 'react';
import { PanelRightOpen, PanelRightClose, Trash2, UsersRound } from 'lucide-react';
import AppHeader from './components/layout/AppHeader.jsx';
import ChatPanel from './components/chat/ChatPanel.jsx';
import AgentMonitor from './components/monitor/AgentMonitor.jsx';
import { useChatSSE } from './hooks/useChatSSE.js';
import { useUserOrders } from './hooks/useUserOrders.js';
import {
  DEFAULT_ORDER_PRIORITY_WEIGHTS,
  extractOrderIdFromText,
  formatPublicOrderRef,
  getOrderDisplayName,
} from './utils/orderHelpers.js';
import t from './i18n/index.js';

const FALLBACK_MODELS = [
  { id: 'standard-service', label: '标准回复', description: '用于客服回复、意图识别与服务记录整理', configured: true },
  { id: 'backup-service', label: '备用回复', description: '用于服务高峰时兜底', configured: true },
];

const STREAM_PREF_KEY = 'mitako_stream_reply_v1';

const DEMO_USERS = [
  { id: 'usr_001', tone: '延期 180 天' },
  { id: 'usr_002', tone: '抽奖质疑' },
  { id: 'usr_003', tone: '破损售后' },
  { id: 'usr_004', tone: '正常在途' },
  { id: 'usr_005', tone: '新用户' },
  { id: 'usr_006', tone: '未成年退款' },
];

function DemoUserSwitcher({ currentUser, onChange }) {
  return (
    <section className="relative z-30 mb-3 rounded-[8px] border border-[var(--mitako-ink)] bg-white/92 px-3 py-2 shadow-[3px_3px_0_rgba(17,20,17,.75)] md:mb-4">
      <div className="flex items-center gap-2 overflow-hidden">
        <div className="hidden shrink-0 items-center gap-1.5 rounded-[8px] bg-[var(--mitako-lime-soft)] px-2.5 py-1.5 text-[11px] font-black text-[var(--mitako-ink)] sm:flex">
          <UsersRound className="h-3.5 w-3.5" aria-hidden="true" />
          {t('users.selectLabel')}
        </div>
        <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto console-scroll py-0.5">
          {DEMO_USERS.map(user => {
            const active = user.id === currentUser;
            return (
              <button
                key={user.id}
                type="button"
                onClick={() => onChange(user.id)}
                className={`min-h-[36px] shrink-0 rounded-[8px] border px-3 text-left transition-[background-color,transform,box-shadow] active:scale-[0.98] ${
                  active
                    ? 'border-[var(--mitako-ink)] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] shadow-[2px_2px_0_rgba(17,20,17,.82)]'
                    : 'border-slate-200 bg-white text-slate-700 hover:bg-[var(--mitako-lime-soft)]'
                }`}
                aria-pressed={active}
              >
                <span className="block text-[11px] font-black leading-tight">{t(`users.${user.id}`)}</span>
                <span className="block text-[9px] font-bold leading-tight text-slate-500">{user.tone}</span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function getInternalOpsMode() {
  if (typeof window === 'undefined') return false;
  const params = new URLSearchParams(window.location.search);
  return params.get('ops') === '1' || params.get('dev') === '1';
}

export default function App() {
  const [currentUser, setCurrentUser] = useState('usr_001');
  const [monitorOpen, setMonitorOpen] = useState(() => {
    if (typeof window === 'undefined') return true;
    return window.matchMedia('(min-width: 1024px)').matches;
  });
  const [models, setModels] = useState(FALLBACK_MODELS);
  const [selectedModelId, setSelectedModelId] = useState('standard-service');
  const [streamReplyEnabled, setStreamReplyEnabled] = useState(() => {
    try {
      return sessionStorage.getItem(STREAM_PREF_KEY) === '1';
    } catch {
      return false;
    }
  });
  const [orderPickerOpen, setOrderPickerOpen] = useState(false);
  const [orderPriorityWeights, setOrderPriorityWeights] = useState(DEFAULT_ORDER_PRIORITY_WEIGHTS);
  const internalOpsMode = getInternalOpsMode();

  const {
    orders,
    userProfile,
    activeOrderId,
    selectOrder,
  } = useUserOrders(currentUser, orderPriorityWeights);

  const refreshModels = useCallback(() => {
    fetch('/api/v1/models')
      .then(r => r.json())
      .then(data => {
        if (data.models?.length) setModels(data.models);
        if (data.default_model_id) setSelectedModelId(data.default_model_id);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch('/api/v1/models')
      .then(r => r.json())
      .then(data => {
        if (data.models?.length) {
          setModels(data.models);
          setSelectedModelId(data.default_model_id || 'standard-service');
        }
      })
      .catch(() => { /* 使用本地 fallback */ });
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem(STREAM_PREF_KEY, streamReplyEnabled ? '1' : '0');
    } catch {
      /* 隐私模式等场景忽略 */
    }
  }, [streamReplyEnabled]);

  const chat = useChatSSE(currentUser, selectedModelId, refreshModels, {
    activeOrderId,
    streamReplyEnabled,
    orderPriorityWeights,
    onWelcomeOrderPick: selectOrder,
    onWelcomeBrowseOrders: () => setOrderPickerOpen(true),
    onClearActiveOrder: () => selectOrder(null),
  });

  const confirmHandoffRef = useRef(chat.confirmHandoff);
  confirmHandoffRef.current = chat.confirmHandoff;

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('e2e') !== '1') return undefined;
    window.__MITAKO_E2E__ = {
      confirmHandoff: async () => {
        await confirmHandoffRef.current?.();
      },
      getHandoffState: () => chat.handoffState,
    };
    return () => {
      delete window.__MITAKO_E2E__;
    };
  }, [chat.handoffState]);

  const memberLabel = userProfile?.member_label || '';

  const applyOrderReference = useCallback((order) => {
    if (!order) return;
    selectOrder(order.order_id);
    const message = t('order.referenceTemplate', 'zh-CN', {
      orderRef: formatPublicOrderRef(order.order_id),
      itemName: getOrderDisplayName(order),
      status: order.status_label || order.status || '待核对',
    });
    chat.handleSend(message, { activeOrderId: order.order_id });
  }, [selectOrder, chat]);

  const handleReferenceOrder = () => {
    setOrderPickerOpen(true);
  };

  const handleInputChange = (val) => {
    chat.setInputVal(val);
    const extracted = extractOrderIdFromText(val);
    if (extracted && orders.some(o => o.order_id === extracted)) {
      selectOrder(extracted);
    }
  };

  const handleBackToAi = () => {
    chat.setIsTransfered(false);
    chat.resetChat();
  };

  const handleDemoUserChange = (userId) => {
    if (userId === currentUser) return;
    chat.prepareUserSwitch();
    setOrderPickerOpen(false);
    selectOrder(null);
    setCurrentUser(userId);
  };

  const updateWeight = (key, value) => {
    const num = Number(value);
    if (Number.isNaN(num)) return;
    setOrderPriorityWeights(prev => ({ ...prev, [key]: num }));
  };

  return (
    <div className="mitako-ppt-scope w-full max-w-7xl mx-auto min-h-[100dvh] h-[100dvh] flex flex-col p-3 md:p-5 text-slate-800 relative">
      <a href="#main-content" className="skip-link">
        {t('app.skipToMain')}
      </a>
      <AppHeader />
      <DemoUserSwitcher currentUser={currentUser} onChange={handleDemoUserChange} />

      <div className={`flex-1 min-h-0 grid grid-cols-1 ${monitorOpen ? 'lg:grid-cols-12 gap-4' : ''} relative items-stretch`}>
        <div id="main-content" className={`min-h-0 flex flex-col h-full max-h-full overflow-hidden ${monitorOpen ? 'lg:col-span-7' : ''}`}>
          <ChatPanel
            key={currentUser}
            memberLabel={memberLabel}
            orders={orders}
            activeOrderId={activeOrderId}
            orderPickerOpen={orderPickerOpen}
            onCloseOrderPicker={() => setOrderPickerOpen(false)}
            onSelectOrder={applyOrderReference}
            messages={chat.chatMessages}
            isAwaitingStream={chat.isAwaitingStream}
            awaitingStep={chat.awaitingStep}
            streamingMsgId={chat.streamingMsgId}
            streamReplyEnabled={streamReplyEnabled}
            presencePhase={chat.presencePhase}
            scrollRef={chat.scrollContainerRef}
            inputVal={chat.inputVal}
            setInputVal={handleInputChange}
            handoffState={chat.handoffState}
            assignedHumanAgent={chat.assignedHumanAgent}
            onSend={chat.handleSend}
            onBackToAi={handleBackToAi}
            onConfirmHandoff={chat.confirmHandoff}
            onDismissHandoff={chat.dismissHandoffPrompt}
            onReferenceOrder={handleReferenceOrder}
            onConfirmWelcomeOrder={chat.confirmWelcomeOrder}
            onBrowseWelcomeOrders={chat.browseWelcomeOrders}
          />
        </div>

        {monitorOpen && (
          <div
            className={`
              flex
              lg:col-span-5 min-h-0 flex-col flex-1 h-full max-h-full overflow-hidden
              fixed lg:relative inset-x-0 bottom-0 z-50 lg:z-auto
              max-h-[85dvh] lg:max-h-none
              rounded-t-[8px] lg:rounded-[8px]
              bg-white
              overscroll-y-contain
            `}
          >
            <AgentMonitor
              monitorIntent={chat.monitorIntent}
              monitorEmotion={chat.monitorEmotion}
              monitorEmotionColor={chat.monitorEmotionColor}
              vikingCapsule={chat.vikingCapsule}
              vikingStyle={chat.vikingStyle}
              intentCapsule={chat.intentCapsule}
              intentStyle={chat.intentStyle}
              emotionCapsule={chat.emotionCapsule}
              emotionStyle={chat.emotionStyle}
              activeTab={chat.activeTab}
              setActiveTab={chat.setActiveTab}
              apiLogs={chat.apiLogs}
              setApiLogs={chat.setApiLogs}
              logStatus={chat.logStatus}
              logStatusText={chat.logStatusText}
              nodeLogs={chat.nodeLogs}
              models={models}
              selectedModelId={selectedModelId}
              onModelChange={setSelectedModelId}
              streamReplyEnabled={streamReplyEnabled}
              onStreamReplyChange={setStreamReplyEnabled}
              orderPriorityWeights={orderPriorityWeights}
              onOrderWeightChange={updateWeight}
              onCloseMobile={() => setMonitorOpen(false)}
              onClearMessages={chat.resetChat}
              showServiceControls={internalOpsMode}
              showOrderPriority={internalOpsMode}
            />
          </div>
        )}

        <div className="fixed bottom-[5.5rem] right-4 z-[60] flex items-center gap-2 lg:bottom-6">
          {!monitorOpen && (
            <button
              type="button"
              data-testid="clear-chat-history"
              onClick={chat.resetChat}
              className="touch-target h-12 rounded-[8px] border-2 border-[var(--mitako-ink)] bg-white px-3 text-xs font-black text-[var(--mitako-ink)] shadow-[4px_4px_0_rgba(17,20,17,.9)] transition-transform active:scale-95 focus-visible:ring-2 focus-visible:ring-white/80"
              aria-label={t('monitor.clearMessages')}
            >
              <span className="inline-flex items-center gap-1">
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">{t('monitor.clearMessages')}</span>
              </span>
            </button>
          )}
          <button
            type="button"
            data-testid="service-status-toggle"
            onClick={() => setMonitorOpen(v => !v)}
            className="touch-target flex h-12 min-w-12 items-center justify-center gap-2 rounded-[8px] border-2 border-[var(--mitako-ink)] bg-[var(--mitako-lime)] px-3 text-[var(--mitako-ink)] shadow-[4px_4px_0_rgba(17,20,17,.9)] transition-transform active:scale-95 focus-visible:ring-2 focus-visible:ring-white/80"
            aria-label={monitorOpen ? t('monitor.toggleHide') : t('monitor.toggleShow')}
          >
            {monitorOpen ? <PanelRightClose className="w-5 h-5" aria-hidden="true" /> : <PanelRightOpen className="w-5 h-5" aria-hidden="true" />}
            <span className="hidden text-xs font-black lg:inline">{monitorOpen ? t('monitor.toggleHide') : t('monitor.toggleShow')}</span>
          </button>
        </div>

      </div>

      <footer className="text-center py-2 text-[11px] text-slate-400 flex-shrink-0 hidden sm:block">
        MITAKO {t('app.brandTag')}
      </footer>
    </div>
  );
}
