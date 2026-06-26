import React from 'react';
import { Headphones } from 'lucide-react';
import RichTextContent from '../shared/RichTextContent.jsx';
import { CARD_RENDERERS } from '../cards/openUILibrary.jsx';
import t from '../../i18n/index.js';
import { StreamCursor } from './XiaoJiaoLoadingBubble.jsx';
import { resolveSpeakerStyle, SPEAKER } from '../../constants/chatSpeakers.js';
import { useMessageWindow } from '../../hooks/useMessageWindow.js';

function BotBubble({ msg, isStreaming, showStreamCursor, cardCallbacks }) {
  if (msg.type === 'custom') {
    const Card = CARD_RENDERERS[msg.content.cardType];
    if (!Card) return null;
    const extraProps = {};
    if (msg.content.cardType === 'handoff_prompt') {
      extraProps.onConfirm = cardCallbacks?.onConfirmHandoff;
      extraProps.onDismiss = cardCallbacks?.onDismissHandoff;
    }
    if (msg.content.cardType === 'welcome_order') {
      extraProps.onConfirm = cardCallbacks?.onConfirmWelcomeOrder;
      extraProps.onBrowse = cardCallbacks?.onBrowseWelcomeOrders;
    }
    return <Card.component props={{ ...msg.content.cardData, ...extraProps }} />;
  }
  const text = msg.content.text || '';
  const speaker = msg.user?.speaker === SPEAKER.HUMAN ? SPEAKER.HUMAN : SPEAKER.AI;
  const style = resolveSpeakerStyle(speaker);

  return (
    <div className={`px-4 py-3.5 text-[15px] leading-relaxed text-pretty max-w-full ${style.bubbleClass}`}>
      <div className="inline">
        <RichTextContent text={text} />
        {isStreaming && showStreamCursor && <StreamCursor />}
      </div>
    </div>
  );
}

function LeftAvatar({ user }) {
  const speaker = user?.speaker === SPEAKER.HUMAN ? SPEAKER.HUMAN : SPEAKER.AI;
  const style = resolveSpeakerStyle(speaker);

  if (speaker === SPEAKER.HUMAN) {
    return (
      <div
        className={`relative w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 self-start bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-md ${style.ringClass}`}
        aria-hidden="true"
      >
        <Headphones className="w-5 h-5" strokeWidth={2.2} />
        <span className="absolute -top-1 -right-1 text-[8px] font-black px-1 py-px rounded-md bg-white text-teal-700 border border-teal-200 leading-none">
          {user?.badge || style.badge}
        </span>
      </div>
    );
  }

  return (
    <div className="relative flex-shrink-0 self-start">
      <img
        src={user?.avatar || '/xiaojiao_avatar.png'}
        alt={user?.name || t('agent.name')}
        width={40}
        height={40}
        className={`w-10 h-10 rounded-xl border-2 border-white object-cover shadow-md ${style.ringClass}`}
      />
      <span className="absolute -top-1 -right-1 text-[8px] font-black px-1 py-px rounded-md bg-[var(--mitako-purple)] text-white border border-[#7B61FF]/40 leading-none">
        AI
      </span>
    </div>
  );
}

export default function MessageList({
  messages,
  streamingMsgId,
  streamReplyEnabled = false,
  scrollRef,
  onConfirmHandoff,
  onDismissHandoff,
  onConfirmWelcomeOrder,
  onBrowseWelcomeOrders,
}) {
  const { visibleMessages, hasOlder, loadingOlder, hiddenCount } = useMessageWindow(messages, scrollRef);

  const cardCallbacks = {
    onConfirmHandoff,
    onDismissHandoff,
    onConfirmWelcomeOrder,
    onBrowseWelcomeOrders,
  };

  return (
    <div
      ref={scrollRef}
      className="flex-1 min-h-0 overflow-y-auto p-4 md:p-5 space-y-4 console-scroll overscroll-y-contain touch-pan-y"
    >
      {hasOlder && (
        <div className="flex justify-center pb-1">
          <button
            type="button"
            disabled={loadingOlder}
            className="text-[11px] font-semibold text-slate-500 bg-white border border-slate-200 rounded-full px-3 py-1.5 shadow-sm disabled:opacity-60"
          >
            {loadingOlder ? t('chat.loadingOlder') : t('chat.loadOlder', 'zh-CN', { count: hiddenCount })}
          </button>
        </div>
      )}
      {visibleMessages.map(msg => {
        if (msg.position === 'right') {
          return (
            <div key={msg._id} className="flex justify-end animate-fade-up">
              <div className="max-w-[88%] px-4 py-3.5 rounded-2xl rounded-tr-md bg-gradient-to-br from-[var(--mitako-purple)] to-[var(--mitako-purple-deep)] text-white text-[15px] font-medium leading-relaxed shadow-md text-pretty">
                {msg.content.text}
              </div>
            </div>
          );
        }

        const speaker = msg.user?.speaker === SPEAKER.HUMAN ? SPEAKER.HUMAN : SPEAKER.AI;
        const style = resolveSpeakerStyle(speaker);
        const displayName = msg.user?.name || (speaker === SPEAKER.HUMAN ? t('speakers.humanName') : t('agent.name'));
        const agentId = msg.user?.agentId;

        return (
          <div key={msg._id} className="flex gap-3 items-start animate-fade-up">
            <LeftAvatar user={msg.user} />
            <div className="flex flex-col items-start w-full max-w-[96%] min-w-0 gap-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[11px] font-bold ${style.labelClass}`}>{displayName}</span>
                {agentId && (
                  <span className="text-[9px] font-mono font-bold text-teal-700 bg-teal-50 border border-teal-200/80 px-1.5 py-0.5 rounded-md">
                    {agentId}
                  </span>
                )}
              </div>
              <BotBubble
                msg={msg}
                isStreaming={msg._id === streamingMsgId}
                showStreamCursor={streamReplyEnabled}
                cardCallbacks={cardCallbacks}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
