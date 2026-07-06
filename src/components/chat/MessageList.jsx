import React from 'react';
import { Headphones } from 'lucide-react';
import RichTextContent from '../shared/RichTextContent.jsx';
import { CARD_RENDERERS } from '../cards/openUILibrary.jsx';
import t from '../../i18n/index.js';
import { StreamCursor } from './XiaoJiaoLoadingBubble.jsx';
import { resolveSpeakerStyle, SPEAKER } from '../../constants/chatSpeakers.js';
import { useMessageWindow } from '../../hooks/useMessageWindow.js';
import { MITAKO_AGENT_AVATAR } from '../../constants/memeMap.js';

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
        className={`relative w-10 h-10 rounded-[8px] border border-slate-200 flex items-center justify-center flex-shrink-0 self-start bg-[var(--mitako-lime)] text-[var(--mitako-ink)] shadow-[0_10px_24px_rgba(127,164,49,.14)] ${style.ringClass}`}
        aria-hidden="true"
      >
        <Headphones className="w-5 h-5" strokeWidth={2.2} />
        <span className="absolute -top-1 -right-1 text-[8px] font-black px-1 py-px rounded-[8px] bg-white text-[var(--mitako-ink)] border border-[var(--mitako-ink)] leading-none">
          {user?.badge || style.badge}
        </span>
      </div>
    );
  }

  return (
    <div className="relative flex-shrink-0 self-start">
      <img
        src={user?.avatar || MITAKO_AGENT_AVATAR}
        alt={user?.name || t('agent.name')}
        width={40}
        height={40}
        className={`w-10 h-10 rounded-[8px] border border-slate-200 object-cover shadow-[0_10px_24px_rgba(127,164,49,.14)] ${style.ringClass}`}
      />
      <span className="absolute -top-1 -right-1 text-[8px] font-black px-1 py-px rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border border-[var(--mitako-ink)] leading-none">
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
  const { visibleMessages, hasOlder, loadingOlder, hiddenCount, loadOlder } = useMessageWindow(messages, scrollRef);

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
            onClick={loadOlder}
            disabled={loadingOlder}
            aria-label={loadingOlder ? t('chat.loadingOlder') : t('chat.loadOlder', 'zh-CN', { count: hiddenCount })}
            className="text-[11px] font-semibold text-[var(--mitako-ink)] bg-white border border-slate-200 rounded-[8px] px-3 py-1.5 disabled:opacity-60"
          >
            {loadingOlder ? t('chat.loadingOlder') : t('chat.loadOlder', 'zh-CN', { count: hiddenCount })}
          </button>
        </div>
      )}
      {visibleMessages.map(msg => {
        if (msg.position === 'right') {
          return (
            <div key={msg._id} className="flex justify-end animate-fade-up">
              <div className="max-w-[88%] px-4 py-3.5 rounded-[8px] bg-[var(--mitako-lime)] border border-slate-200 text-[var(--mitako-ink)] text-[15px] font-medium leading-relaxed shadow-[0_12px_28px_rgba(127,164,49,.16)] text-pretty">
                <RichTextContent text={msg.content.text} variant="user" />
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
                  <span className="text-[9px] font-bold text-[var(--mitako-ink)] bg-white border border-[var(--mitako-ink)] px-1.5 py-0.5 rounded-[8px]">
                    {t('speakers.humanBadge')}
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
