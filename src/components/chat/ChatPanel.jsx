import React from 'react';
import t from '../../i18n/index.js';
import PhoneFrame from './PhoneFrame.jsx';
import OrderPickerOverlay from './OrderPickerOverlay.jsx';
import MessageList from './MessageList.jsx';
import ChatInput from './ChatInput.jsx';
import ChatPresenceDock from './ChatPresenceDock.jsx';
import XiaoJiaoLoadingBubble from './XiaoJiaoLoadingBubble.jsx';
import ConversationStateCard from '../shared/ConversationStateCard.jsx';
import { MITAKO_AGENT_AVATAR } from '../../constants/memeMap.js';

export default function ChatPanel({
  memberLabel,
  orders,
  activeOrderId,
  orderPickerOpen,
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
  conversationState,
  onSend,
  onStop,
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
  const headerSub = isHumanConnected ? t('cards.transferConnected') : t('agent.online');

  return (
    <PhoneFrame>
      <section className="relative flex flex-col min-h-0 overflow-hidden h-full bg-white @container/chat">
        <header className="px-3 py-2.5 border-b border-slate-200 flex flex-col gap-2 bg-white flex-shrink-0">
          <div className="flex items-center gap-2.5 w-full min-w-0">
            <div className="relative flex-shrink-0">
              <img
                src={MITAKO_AGENT_AVATAR}
                alt={t('agent.name')}
                width={40}
                height={40}
                className="w-10 h-10 rounded-[8px] border border-slate-200 object-cover"
              />
              <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-[var(--mitako-lime)] border border-slate-200 rounded-[4px]" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-bold text-slate-800 leading-snug break-words">
                {headerName}
              </p>
              <span className={`inline-flex mt-1 text-[10px] font-black px-2 py-0.5 rounded-[8px] border border-slate-200 text-[var(--mitako-ink)] ${
                isHumanConnected
                  ? 'bg-[var(--mitako-lime)]'
                  : 'bg-white'
              }`}>
                {headerSub}
              </span>
            </div>
          </div>
        </header>

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
          {isAwaitingStream && streamReplyEnabled && (
            <div className="absolute bottom-3 left-3 right-3 pointer-events-none">
              <XiaoJiaoLoadingBubble step={awaitingStep} />
            </div>
          )}
          {!streamReplyEnabled && (
            <ChatPresenceDock phase={presencePhase} handoffState={handoffState} />
          )}
        </div>

        <ConversationStateCard state={conversationState} />

        <ChatInput
          inputVal={inputVal}
          setInputVal={setInputVal}
          handoffState={handoffState}
          isAwaitingStream={isAwaitingStream}
          onSend={onSend}
          onStop={onStop}
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
