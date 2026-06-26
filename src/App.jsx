import React, { useState, useEffect, useCallback, useRef } from 'react';
import { PanelRightOpen, PanelRightClose } from 'lucide-react';
import AppHeader from './components/layout/AppHeader.jsx';
import ChatPanel from './components/chat/ChatPanel.jsx';
import AgentMonitor from './components/monitor/AgentMonitor.jsx';
import { useChatSSE } from './hooks/useChatSSE.js';
import { useUserOrders } from './hooks/useUserOrders.js';
import { extractOrderIdFromText, DEFAULT_ORDER_PRIORITY_WEIGHTS } from './utils/orderHelpers.js';
import t from './i18n/index.js';

const FALLBACK_MODELS = [
  { id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash', description: 'SenseNova 高性能对话模型', configured: false },
  { id: 'agnes-2.0-flash', label: 'Agnes 2.0 Flash', description: 'Agnes AI Hub 主力模型', configured: false },
];

const STREAM_PREF_KEY = 'mitako_stream_reply_v1';

export default function App() {
  const [currentUser, setCurrentUser] = useState('usr_001');
  const [showTestConsole, setShowTestConsole] = useState(false);
  const [monitorOpen, setMonitorOpen] = useState(false);
  const [models, setModels] = useState(FALLBACK_MODELS);
  const [selectedModelId, setSelectedModelId] = useState('deepseek-v4-flash');
  const [streamReplyEnabled, setStreamReplyEnabled] = useState(() => {
    try {
      return sessionStorage.getItem(STREAM_PREF_KEY) === '1';
    } catch {
      return false;
    }
  });
  const [orderPickerOpen, setOrderPickerOpen] = useState(false);
  const [orderPriorityWeights, setOrderPriorityWeights] = useState(DEFAULT_ORDER_PRIORITY_WEIGHTS);

  const {
    orders,
    userProfile,
    activeOrder,
    activeOrderId,
    selectOrder,
  } = useUserOrders(currentUser, orderPriorityWeights);

  const refreshModels = useCallback(() => {
    fetch('/api/v1/models')
      .then(r => r.json())
      .then(data => {
        if (data.models?.length) setModels(data.models);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch('/api/v1/models')
      .then(r => r.json())
      .then(data => {
        if (data.models?.length) {
          setModels(data.models);
          setSelectedModelId(data.default_model_id || 'deepseek-v4-flash');
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
  });

  const confirmHandoffRef = useRef(chat.confirmHandoff);
  confirmHandoffRef.current = chat.confirmHandoff;

  // E2E 桥接：/?e2e=1 暴露 confirmHandoff，供 Playwright 真实触发（无定时器竞态）
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
    chat.setInputVal(t('order.referenceTemplate', 'zh-CN', { orderId: order.order_id }));
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

  const updateWeight = (key, value) => {
    const num = Number(value);
    if (Number.isNaN(num)) return;
    setOrderPriorityWeights(prev => ({ ...prev, [key]: num }));
  };

  return (
    <div className="w-full max-w-7xl mx-auto min-h-[100dvh] h-[100dvh] flex flex-col p-3 md:p-5 text-slate-800 relative">
      <a href="#main-content" className="skip-link">
        {t('app.skipToMain')}
      </a>
      <AppHeader
        showTestConsole={showTestConsole}
        setShowTestConsole={setShowTestConsole}
        onRunTest={(i) => chat.runTestCase(i, setCurrentUser)}
        onReset={chat.resetChat}
      />

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-4 relative items-stretch">
        <div id="main-content" className="min-h-0 flex flex-col lg:col-span-7 h-full max-h-full overflow-hidden">
          <ChatPanel
            currentUser={currentUser}
            onUserChange={(id) => chat.handleSwitchUser(id, setCurrentUser)}
            order={activeOrder}
            memberLabel={memberLabel}
            orders={orders}
            activeOrderId={activeOrderId}
            orderPickerOpen={orderPickerOpen}
            onOpenOrderPicker={() => setOrderPickerOpen(true)}
            onCloseOrderPicker={() => setOrderPickerOpen(false)}
            onSelectOrder={applyOrderReference}
            messages={chat.chatMessages}
            isAwaitingStream={chat.isAwaitingStream}
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

        <div
          className={`
            ${monitorOpen ? 'flex' : 'hidden lg:flex'}
            lg:col-span-5 min-h-0 flex-col flex-1 h-full max-h-full overflow-hidden
            fixed lg:relative inset-x-0 bottom-0 z-50 lg:z-auto
            max-h-[85dvh] lg:max-h-none
            rounded-t-2xl lg:rounded-[var(--radius-panel)]
            shadow-[0_-8px_40px_rgba(15,23,42,0.12)] lg:shadow-none
            bg-white/95 lg:bg-transparent backdrop-blur-md lg:backdrop-blur-none
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
          />
        </div>

        <button
          type="button"
          onClick={() => setMonitorOpen(v => !v)}
          className="lg:hidden fixed right-4 bottom-[5.5rem] z-[60] touch-target w-12 h-12 rounded-full bg-[var(--mitako-purple)] text-white shadow-lg flex items-center justify-center active:scale-95 transition-transform focus-visible:ring-2 focus-visible:ring-white/80"
          aria-label={monitorOpen ? t('monitor.toggleHide') : t('monitor.toggleShow')}
        >
          {monitorOpen ? <PanelRightClose className="w-5 h-5" aria-hidden="true" /> : <PanelRightOpen className="w-5 h-5" aria-hidden="true" />}
        </button>
      </div>

      <footer className="text-center py-2 text-[11px] text-slate-400 flex-shrink-0 hidden sm:block">
        MITAKO {t('app.brandTag')}
      </footer>
    </div>
  );
}
