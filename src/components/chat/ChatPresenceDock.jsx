import React from 'react';
import { Bot, Headphones } from 'lucide-react';
import t from '../../i18n/index.js';

/** 非流式模式：输入框上方的独占临时状态区（不参与消息流滚动，避免层级遮蔽） */
export default function ChatPresenceDock({ phase, handoffState = 'none' }) {
  if (!phase) return null;

  const isTyping = phase === 'typing';
  const isQueuing = handoffState === 'queuing';
  const isConnected = handoffState === 'connected';
  const isHuman = isQueuing || isConnected;

  let title;
  if (isTyping) {
    title = isConnected ? t('presence.observerTyping') : (isQueuing ? t('presence.humanTyping') : t('presence.typing'));
  } else {
    title = isConnected ? t('presence.observerRead') : (isQueuing ? t('presence.humanRead') : t('presence.read'));
  }

  return (
    <div
      className="flex-shrink-0 px-3 py-2 border-t border-slate-100/90 bg-gradient-to-r from-slate-50/95 via-white/95 to-slate-50/95 backdrop-blur-sm"
      role="status"
      aria-live="polite"
      aria-label={title}
    >
      <div
        className={`flex items-center gap-2.5 px-3.5 py-2.5 rounded-2xl border shadow-sm ${
          isTyping
            ? isHuman
              ? 'bg-teal-500/8 border-teal-300/40'
              : 'bg-[#7B61FF]/8 border-[#7B61FF]/20'
            : 'bg-white border-slate-200/80'
        }`}
      >
        {isHuman ? (
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center text-white flex-shrink-0">
            <Headphones className="w-4 h-4" aria-hidden="true" />
          </div>
        ) : (
          <div className="relative w-8 h-8 flex-shrink-0">
            <img
              src="/xiaojiao_avatar.png"
              alt=""
              width={32}
              height={32}
              className="w-8 h-8 rounded-xl border border-white object-cover"
              aria-hidden="true"
            />
            <span className="absolute -bottom-1 -right-1 w-4 h-4 rounded-md bg-[var(--mitako-purple)] text-white flex items-center justify-center">
              <Bot className="w-2.5 h-2.5" aria-hidden="true" />
            </span>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className={`text-[13px] font-semibold truncate ${
            isTyping
              ? isHuman ? 'text-teal-700' : 'text-[var(--mitako-purple)]'
              : 'text-slate-700'
          }`}>
            {title}
          </p>
          {isTyping && (
            <div className="flex gap-1 mt-1" aria-hidden="true">
              {[0, 1, 2].map(i => (
                <span
                  key={i}
                  className={`w-1.5 h-1.5 rounded-full animate-bounce ${
                    isHuman ? 'bg-teal-500/50' : 'bg-[var(--mitako-purple)]/50'
                  }`}
                  style={{ animationDelay: `${i * 0.12}s` }}
                />
              ))}
            </div>
          )}
        </div>
        {!isTyping && (
          <span className="text-[11px] font-bold text-emerald-600 bg-emerald-50 border border-emerald-200/80 px-2 py-0.5 rounded-full flex-shrink-0">
            ✓
          </span>
        )}
      </div>
    </div>
  );
}
