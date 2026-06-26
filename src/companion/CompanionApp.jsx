import React, { useEffect, useState } from 'react';
import { PanelRightOpen, PanelRightClose, Sparkles } from 'lucide-react';
import PhoneFrame from '../components/chat/PhoneFrame.jsx';
import AgentMonitor from '../components/monitor/AgentMonitor.jsx';
import CompanionMessageList from './CompanionMessageList.jsx';
import CompanionChatFooter from './CompanionChatFooter.jsx';
import CompanionOrderPicker from './CompanionOrderPicker.jsx';
import CompanionActionSheet from './CompanionActionSheet.jsx';
import CompanionAdventureEnterModal from './CompanionAdventureEnterModal.jsx';
import AdventureLoadingOverlay from './AdventureLoadingOverlay.jsx';
import CompanionShareDemoModal from './CompanionShareDemoModal.jsx';
import CompanionAdventureContextModal from './CompanionAdventureContextModal.jsx';
import OnboardingFlow from './OnboardingFlow.jsx';
import { useCompanionChat } from './hooks/useCompanionChat.js';
import { useCompanionOrders } from './hooks/useCompanionOrders.js';
import t from '../i18n/index.js';

const FALLBACK_MODELS = [
  { id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash', description: 'SenseNova 高性能对话模型', configured: false },
  { id: 'agnes-2.0-flash', label: 'Agnes 2.0 Flash', description: 'Agnes AI Hub 主力模型', configured: false },
];

const COMPANION_USER_KEY = 'mitako_companion_user_id_v1';

function getOrCreateUserId() {
  try {
    const saved = sessionStorage.getItem(COMPANION_USER_KEY);
    if (saved) return saved;
    const id = `cmp_${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem(COMPANION_USER_KEY, id);
    return id;
  } catch {
    return `cmp_${Math.random().toString(36).slice(2, 10)}`;
  }
}

/** Companion 用户端 — 粉色多巴胺 + 手机框 + 右侧调试 Monitor（对齐客服 Agent） */
export default function CompanionApp() {
  const [userId] = useState(getOrCreateUserId);
  const [models, setModels] = useState(FALLBACK_MODELS);
  const [selectedModelId, setSelectedModelId] = useState('deepseek-v4-flash');
  const chat = useCompanionChat(userId, selectedModelId);
  const orderState = useCompanionOrders(userId);
  const [input, setInput] = useState('');
  const [monitorOpen, setMonitorOpen] = useState(false);
  const [orderPickerOpen, setOrderPickerOpen] = useState(false);
  const [actionSheetOpen, setActionSheetOpen] = useState(false);
  const [adventureModalOpen, setAdventureModalOpen] = useState(false);
  const [adventureBusy, setAdventureBusy] = useState(false);
  const [shareDemoOpen, setShareDemoOpen] = useState(false);
  const [contextModalOpen, setContextModalOpen] = useState(false);
  const [contextResetBusy, setContextResetBusy] = useState(false);
  const [modalWorldPrefill, setModalWorldPrefill] = useState('原神 · 提瓦特大陆');

  useEffect(() => {
    if (chat.adventureEnterRequest?.world) {
      setModalWorldPrefill(chat.adventureEnterRequest.world);
      setAdventureModalOpen(true);
      chat.clearAdventureEnterRequest();
    }
  }, [chat.adventureEnterRequest, chat.clearAdventureEnterRequest]);

  useEffect(() => {
    fetch('/api/v1/models')
      .then(r => r.json())
      .then(data => {
        if (data.models?.length) {
          setModels(data.models);
          setSelectedModelId(data.default_model_id || 'deepseek-v4-flash');
        }
      })
      .catch(() => {});
  }, []);

  if (chat.persona === null) {
    return (
      <div className="min-h-[100dvh] bg-gradient-to-br from-rose-50 via-white to-purple-50 flex items-center justify-center p-4">
        <div className="text-center space-y-3">
          <div className="w-12 h-12 mx-auto rounded-2xl bg-gradient-to-br from-rose-300 to-fuchsia-400 animate-pulse" />
          <p className="text-sm text-slate-500">{t('companion.personaLoading')}</p>
        </div>
      </div>
    );
  }

  if (!chat.persona?.onboarded) {
    return (
      <div className="min-h-[100dvh] bg-gradient-to-br from-rose-50 via-white to-purple-50 flex items-center justify-center p-4">
        <div className="w-full max-w-md glass-panel p-2">
          <OnboardingFlow onComplete={chat.savePersona} />
        </div>
      </div>
    );
  }

  const { agent_name: agentName, user_title: userTitle } = chat.persona;
  const isCsMode = chat.persona?.agent_mode === 'cs_parttime' && !chat.adventureActive;

  const handlePickOrder = (orderId) => {
    setInput(t('order.referenceTemplate', 'zh-CN', { orderId }));
    setOrderPickerOpen(false);
  };

  const handleEnterAdventure = () => setAdventureModalOpen(true);

  const handleConfirmAdventure = async (world) => {
    setAdventureModalOpen(false);
    setAdventureBusy(true);
    try {
      await chat.startAdventure(world);
    } catch (e) {
      console.error(e);
      setAdventureModalOpen(true);
    } finally {
      setAdventureBusy(false);
    }
  };

  const handleOpenShareDemo = () => setShareDemoOpen(true);

  const handleResetAdventureContext = async (mode) => {
    setContextResetBusy(true);
    try {
      await chat.resetAdventureContext(mode);
    } finally {
      setContextResetBusy(false);
    }
  };

  const handlePickChoice = (choice) => {
    if (chat.streaming) return;
    chat.sendAdventureChoice(choice);
  };

  return (
    <div className="w-full max-w-7xl mx-auto min-h-[100dvh] h-[100dvh] flex flex-col p-3 md:p-5 text-slate-800 relative bg-gradient-to-br from-rose-50 via-white to-fuchsia-50">
      <header className="flex-shrink-0 mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold text-rose-500 uppercase tracking-wider">{t('companion.badge')}</p>
          <h1 className="text-lg font-bold text-slate-800">{t('companion.title')}</h1>
          <p className="text-xs text-slate-500">{t('companion.subtitle')}</p>
        </div>
        <div className="flex gap-2 text-xs">
          <a href="/companion-desk" target="_blank" rel="noopener noreferrer" className="px-3 py-1.5 rounded-full bg-white border border-rose-100 text-rose-600 font-semibold hover:bg-rose-50">
            {t('companion.linkObsDesk')}
          </a>
          <a href="/" className="px-3 py-1.5 rounded-full bg-white border border-slate-100 text-slate-500 hover:text-[var(--mitako-purple)]">
            {t('companion.linkCs')}
          </a>
        </div>
      </header>

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-4 relative items-stretch">
        <div className="min-h-0 flex flex-col lg:col-span-7 h-full max-h-full overflow-hidden">
          <PhoneFrame>
            <section id="companion-phone-root" className="relative flex flex-col min-h-0 overflow-hidden h-full bg-white isolate">
              <CompanionOrderPicker
                open={orderPickerOpen}
                onClose={() => setOrderPickerOpen(false)}
                orders={orderState.orders}
                activeOrderId={null}
                onSelect={handlePickOrder}
              />
              <header className="px-3 py-2.5 border-b border-rose-100 flex items-center gap-2.5 bg-gradient-to-r from-rose-50 to-white flex-shrink-0">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-rose-300 to-fuchsia-400 flex items-center justify-center shadow-sm">
                  <Sparkles className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] font-bold text-slate-800">{agentName}</p>
                  <span className={`inline-flex mt-0.5 text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                    chat.adventureActive
                      ? 'text-violet-700 bg-violet-50 border-violet-200/80'
                      : 'text-rose-700 bg-rose-50 border-rose-200/80'
                  }`}>
                    {chat.adventureActive
                      ? t('companion.adventureModeBadge', 'zh-CN', { world: chat.adventureSession?.world_title || '冒险' })
                      : `${userTitle} · ${isCsMode ? t('companion.csParttimeBadge') : t('companion.modeCompanion')}`}
                  </span>
                </div>
              </header>

              <CompanionMessageList
                messages={chat.messages}
                streaming={chat.streaming}
                persona={chat.persona}
                cardCallbacks={chat.cardCallbacks}
                scrollRef={chat.scrollRef}
                adventureActive={chat.adventureActive}
                onOpenContextModal={() => setContextModalOpen(true)}
              />

              <AdventureLoadingOverlay
                open={Boolean(chat.adventureLoading)}
                world={chat.adventureLoading?.world}
                phase={chat.adventureLoading?.phase}
                progress={chat.adventureLoading?.progress}
              />

              <div className="relative z-20 flex-shrink-0 shadow-[0_-4px_24px_rgba(124,58,237,0.08)]">
                <CompanionChatFooter
                  input={input}
                  setInput={setInput}
                  streaming={chat.streaming}
                  onSend={chat.sendMessage}
                  hasOrders={orderState.orders.length > 0}
                  onOpenOrderPicker={() => setOrderPickerOpen(true)}
                  onOpenActionSheet={() => setActionSheetOpen(true)}
                  isCsMode={isCsMode}
                  adventureActive={chat.adventureActive}
                  lastChoices={chat.lastChoices}
                  onPickChoice={handlePickChoice}
                  persona={chat.persona}
                  adventureMessages={chat.adventureActive ? chat.messages : []}
                />
              </div>

              <CompanionActionSheet
                open={actionSheetOpen}
                onClose={() => setActionSheetOpen(false)}
                adventureActive={chat.adventureActive}
                onEnterAdventure={handleEnterAdventure}
                onExitAdventure={() => chat.exitAdventure()}
                onOpenShareDemo={handleOpenShareDemo}
                onOpenContextModal={() => setContextModalOpen(true)}
              />
              <CompanionAdventureContextModal
                open={contextModalOpen}
                onClose={() => setContextModalOpen(false)}
                onReset={handleResetAdventureContext}
                busy={contextResetBusy || chat.streaming}
                messageCount={chat.adventureActive ? chat.messages.length : 0}
              />
              <CompanionShareDemoModal
                open={shareDemoOpen}
                onClose={() => setShareDemoOpen(false)}
                onSimulateSku={() => chat.simulateShareFromApp('sku')}
                onSimulateArticle={() => chat.simulateShareFromApp('article')}
              />
              <CompanionAdventureEnterModal
                open={adventureModalOpen}
                onClose={() => !adventureBusy && setAdventureModalOpen(false)}
                onConfirm={handleConfirmAdventure}
                busy={adventureBusy}
                initialWorld={modalWorldPrefill}
              />
            </section>
          </PhoneFrame>
        </div>

        <div
          className={`
            ${monitorOpen ? 'flex' : 'hidden lg:flex'}
            lg:col-span-5 min-h-0 flex-col flex-1 h-full max-h-full overflow-hidden
            fixed lg:relative inset-x-0 bottom-0 z-50 lg:z-auto
            max-h-[85dvh] lg:max-h-none rounded-t-2xl lg:rounded-[var(--radius-panel)]
            shadow-[0_-8px_40px_rgba(15,23,42,0.12)] lg:shadow-none
            bg-white/95 lg:bg-transparent backdrop-blur-md lg:backdrop-blur-none
          `}
        >
          <AgentMonitor
            monitorIntent={chat.monitorEmotion.label}
            monitorEmotion={chat.monitorEmotion.level}
            monitorEmotionColor={chat.monitorEmotionColor}
            vikingCapsule={chat.memoryCapsule}
            vikingStyle={chat.memoryStyle}
            intentCapsule={chat.adventureActive ? 'adventure' : (isCsMode ? 'cs_parttime' : 'companion')}
            intentStyle={chat.adventureActive ? 'bg-violet-100 text-violet-700 border-violet-200' : 'bg-rose-100 text-rose-700 border-rose-200'}
            emotionCapsule={`L${chat.monitorEmotion.level}`}
            emotionStyle="bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200"
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
            streamReplyEnabled={false}
            onStreamReplyChange={() => {}}
            orderPriorityWeights={{}}
            onOrderWeightChange={() => {}}
            showOrderPriority={false}
            memoryItems={chat.memoryItems}
            onClearMessages={chat.streaming ? undefined : () => chat.clearChat().catch(console.error)}
            onCloseMobile={() => setMonitorOpen(false)}
          />
        </div>

        <button
          type="button"
          onClick={() => setMonitorOpen(v => !v)}
          className="lg:hidden fixed right-4 bottom-[5.5rem] z-[60] touch-target w-12 h-12 rounded-full bg-[var(--mitako-purple)] text-white shadow-lg flex items-center justify-center"
          aria-label={monitorOpen ? t('monitor.toggleHide') : t('monitor.toggleShow')}
        >
          {monitorOpen ? <PanelRightClose className="w-5 h-5" /> : <PanelRightOpen className="w-5 h-5" />}
        </button>
      </div>

    </div>
  );
}
