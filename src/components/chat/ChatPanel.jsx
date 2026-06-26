import React from 'react';
import { ChevronDown } from 'lucide-react';
import t from '../../i18n/index.js';
import PhoneFrame from './PhoneFrame.jsx';
import OrderPickerOverlay, { OrderQuickBar } from './OrderPickerOverlay.jsx';
import MessageList from './MessageList.jsx';
import ChatInput from './ChatInput.jsx';
import ChatPresenceDock from './ChatPresenceDock.jsx';

export default function ChatPanel({
  currentUser,
  onUserChange,
  order,
  memberLabel,
  orders,
  activeOrderId,
  orderPickerOpen,
  onOpenOrderPicker,
  onCloseOrderPicker,
  onSelectOrder,
  onReferenceOrder,
  messages,
  isAwaitingStream,
  awaitingStep,
  streamingMsgId,
  streamReplyEnabled,
  presencePhase,
  scrollRef,
  inputVal,
  setInputVal,
  handoffState,
  onSend,
  onBackToAi,
  onConfirmHandoff,
  onDismissHandoff,
  onConfirmWelcomeOrder,
  onBrowseWelcomeOrders,
  assignedHumanAgent,
}) {
  const isHumanConnected = handoffState === 'connected';
  const headerName = isHumanConnected && assignedHumanAgent?.name
    ? assignedHumanAgent.name
    : `${t('agent.role')} · ${t('agent.name')}`;
  const headerSub = isHumanConnected && assignedHumanAgent?.agent_id
    ? t('handoff.agentId', 'zh-CN', { id: assignedHumanAgent.agent_id })
    : t('agent.online');

  return (
    <PhoneFrame>
      <section className="relative flex flex-col min-h-0 overflow-hidden h-full bg-white @container/chat">
        <header className="px-3 py-2.5 border-b border-slate-100 flex flex-col gap-2 bg-white/50 flex-shrink-0">
          <div className="flex items-center gap-2.5 w-full min-w-0">
            <div className="relative flex-shrink-0">
              <img
                src="/xiaojiao_avatar.png"
                alt={t('agent.name')}
                width={40}
                height={40}
                className="w-10 h-10 rounded-xl border border-slate-200/60 object-cover"
              />
              <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 bg-emerald-400 border-2 border-white rounded-full" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-bold text-slate-800 leading-snug break-words">
                {headerName}
              </p>
              <span className={`inline-flex mt-1 text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                isHumanConnected
                  ? 'text-teal-700 bg-teal-50 border-teal-200/60'
                  : 'text-emerald-700 bg-emerald-50 border-emerald-200/60'
              }`}>
                {headerSub}
              </span>
            </div>
          </div>
          <div className="relative w-full">
            <label htmlFor="demo-user-select" className="sr-only">{t('users.selectLabel')}</label>
            <select
              id="demo-user-select"
              name="demo_user"
              value={currentUser}
              onChange={e => onUserChange(e.target.value)}
              aria-label={t('users.selectLabel')}
              className="w-full min-h-[40px] text-xs bg-white border border-slate-200 rounded-xl px-3 py-2 text-slate-700 outline-none focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/30 focus:border-[var(--mitako-purple)]/40 font-semibold appearance-none pr-8 truncate"
            >
              <option value="usr_001">{t('users.usr_001')}</option>
              <option value="usr_002">{t('users.usr_002')}</option>
              <option value="usr_003">{t('users.usr_003')}</option>
            </select>
            <ChevronDown className="w-4 h-4 absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          </div>
        </header>

        <OrderQuickBar order={order} memberLabel={memberLabel} onOpenPicker={onOpenOrderPicker} />

        <div className="flex flex-col flex-1 min-h-0 relative">
          <MessageList
            messages={messages}
            streamingMsgId={streamingMsgId}
            streamReplyEnabled={streamReplyEnabled}
            scrollRef={scrollRef}
            onConfirmHandoff={onConfirmHandoff}
            onDismissHandoff={onDismissHandoff}
            onConfirmWelcomeOrder={onConfirmWelcomeOrder}
            onBrowseWelcomeOrders={onBrowseWelcomeOrders}
          />
          {!streamReplyEnabled && (
            <ChatPresenceDock phase={presencePhase} handoffState={handoffState} />
          )}
        </div>

        <ChatInput
          inputVal={inputVal}
          setInputVal={setInputVal}
          handoffState={handoffState}
          isAwaitingStream={isAwaitingStream}
          onSend={onSend}
          onBackToAi={onBackToAi}
          onReferenceOrder={onReferenceOrder}
          hasOrder={orders?.length > 0}
        />

        <OrderPickerOverlay
          open={orderPickerOpen}
          orders={orders}
          activeOrderId={activeOrderId}
          memberLabel={memberLabel}
          onClose={onCloseOrderPicker}
          onSelect={onSelectOrder}
        />
      </section>
    </PhoneFrame>
  );
}
