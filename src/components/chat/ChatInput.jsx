import React from 'react';
import { Send, Headphones, AtSign } from 'lucide-react';
import t from '../../i18n/index.js';

export default function ChatInput({
  inputVal,
  setInputVal,
  handoffState,
  isAwaitingStream,
  onSend,
  onBackToAi,
  onReferenceOrder,
  hasOrder,
}) {
  const submit = () => {
    if (!inputVal.trim() || isAwaitingStream) return;
    onSend(inputVal);
    setInputVal('');
  };

  const isConnected = handoffState === 'connected';
  const isQueuing = handoffState === 'queuing';
  const placeholder = isConnected
    ? t('input.placeholderTransferred')
    : isQueuing
    ? t('input.placeholderQueuing')
    : t('input.placeholder');

  return (
    <div className="relative p-3 md:p-4 border-t border-slate-100 bg-[var(--surface-muted)] flex flex-col gap-2 flex-shrink-0">
      {(isConnected || isQueuing) && (
        <div className={`py-2 px-3 rounded-xl flex flex-col gap-2 text-xs font-semibold ${
          isConnected ? 'bg-rose-600/95 text-white' : 'bg-amber-500/10 text-amber-900 border border-amber-200/80'
        }`} data-testid="handoff-status-banner">
          <div className="flex items-center gap-2">
            <Headphones className={`w-4 h-4 flex-shrink-0 ${isQueuing ? 'animate-pulse text-amber-600' : ''}`} />
            <span className="text-pretty">{isConnected ? t('transfer.banner') : t('transfer.bannerQueuing')}</span>
          </div>
          {isConnected && (
            <button
              type="button"
              onClick={onBackToAi}
              className="text-[11px] font-bold text-rose-700 bg-white px-3 py-1.5 rounded-lg self-start"
            >
              {t('transfer.backToAi')}
            </button>
          )}
        </div>
      )}

      {/* flex-nowrap 防止发送按钮被压成竖排 */}
      <div className="flex items-stretch gap-2 flex-nowrap min-w-0">
        {hasOrder && (
          <button
            type="button"
            onClick={onReferenceOrder}
            aria-label={t('order.referenceBtn')}
            className="touch-target flex-shrink-0 w-11 h-11 text-[var(--mitako-orange)] bg-[var(--mitako-orange)]/10 border border-[var(--mitako-orange)]/25 hover:bg-[var(--mitako-orange)]/15 rounded-xl flex items-center justify-center focus-visible:ring-2 focus-visible:ring-[var(--mitako-orange)]/40"
          >
            <AtSign className="w-4 h-4" aria-hidden="true" />
          </button>
        )}
        <input
          type="text"
          name="chat_message"
          autoComplete="off"
          spellCheck={false}
          aria-label={placeholder}
          value={inputVal}
          onChange={e => setInputVal(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit(); }}
          placeholder={placeholder}
          disabled={isAwaitingStream}
          className="flex-1 min-w-0 min-h-[44px] bg-white border border-slate-200 focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/30 focus:border-[var(--mitako-purple)]/40 outline-none rounded-xl px-3 text-[15px] text-slate-800 placeholder-slate-400 transition-colors disabled:opacity-60 touch-manipulation"
        />
        <button
          type="button"
          onClick={submit}
          disabled={isAwaitingStream || !inputVal.trim()}
          aria-label={t('input.send')}
          className="touch-target flex-shrink-0 h-11 min-w-[44px] px-3 rounded-xl bg-[var(--mitako-purple)] hover:bg-[var(--mitako-purple-deep)] text-white font-bold text-sm whitespace-nowrap transition-[transform,background-color] active:scale-[0.98] disabled:bg-slate-200 disabled:text-slate-400 flex items-center justify-center gap-1 focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/40"
        >
          <span className="hidden @[360px]/chat:inline">{t('input.send')}</span>
          <Send className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
