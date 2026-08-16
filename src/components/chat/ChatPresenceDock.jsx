import React from 'react';
import { Bot, Headphones } from 'lucide-react';
import t from '../../i18n/index.js';
import { MITAKO_LOADING_AVATAR } from '../../constants/memeMap.js';

export default function ChatPresenceDock({ phase, handoffState = 'none' }) {
  if (!phase) return null;

  const isTyping = phase === 'typing';
  const isQueuing = handoffState === 'queuing';
  const isConnected = handoffState === 'connected';
  const isHuman = isQueuing || isConnected;

  const title = isTyping
    ? (isConnected ? t('presence.observerTyping') : (isQueuing ? t('presence.humanTyping') : t('presence.typing')))
    : (isConnected ? t('presence.observerRead') : (isQueuing ? t('presence.humanRead') : t('presence.read')));

  return (
    <div className="flex-shrink-0 px-3 py-2 border-t border-slate-200 bg-white" role="status" aria-live="polite" aria-label={title}>
      <div className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-[8px] border border-slate-200 bg-white shadow-[0_10px_24px_rgba(127,164,49,.14)]">
        {isHuman ? (
          <div className="w-8 h-8 rounded-[8px] bg-[var(--mitako-lime)] border border-slate-200 flex items-center justify-center text-[var(--mitako-ink)] flex-shrink-0">
            <Headphones className="w-4 h-4" aria-hidden="true" />
          </div>
        ) : (
          <div className="relative w-8 h-8 flex-shrink-0">
            <img src={MITAKO_LOADING_AVATAR} alt="" width={32} height={32} className="w-8 h-8 rounded-[8px] border border-slate-200 object-cover object-top" aria-hidden="true" />
            <span className="absolute -bottom-1 -right-1 w-4 h-4 rounded-[6px] bg-white border border-[var(--mitako-ink)] text-[var(--mitako-ink)] flex items-center justify-center">
              <Bot className="w-2.5 h-2.5" aria-hidden="true" />
            </span>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-bold truncate text-[var(--mitako-ink)]">{title}</p>
          {isTyping && (
            <div className="flex gap-1 mt-1" aria-hidden="true">
              {[0, 1, 2].map(i => (
                <span key={i} className="w-1.5 h-1.5 rounded-full animate-bounce bg-[var(--mitako-ink)]/50" style={{ animationDelay: `${i * 0.12}s` }} />
              ))}
            </div>
          )}
        </div>
        {!isTyping && (
          <span className="text-[11px] font-black text-[var(--mitako-ink)] bg-[var(--mitako-lime)] border border-slate-200 px-2 py-0.5 rounded-[8px] flex-shrink-0">
            OK
          </span>
        )}
      </div>
    </div>
  );
}
