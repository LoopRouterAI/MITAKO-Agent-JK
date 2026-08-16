import React from 'react';
import t from '../../i18n/index.js';
import { useLoadingHint } from '../../hooks/useLoadingHint.js';
import { MITAKO_LOADING_AVATAR } from '../../constants/memeMap.js';

export default function XiaoJiaoLoadingBubble({ step = 'intent' }) {
  const hint = useLoadingHint(step, true);

  return (
    <div
      className="px-4 py-3.5 rounded-[8px] bg-white border border-slate-200 shadow-[0_10px_24px_rgba(127,164,49,.14)] max-w-[92%]"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-3">
        <img
          src={MITAKO_LOADING_AVATAR}
          alt=""
          width={40}
          height={40}
          className="w-10 h-10 flex-shrink-0 rounded-[8px] bg-white border border-slate-200 object-cover object-top"
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-black text-[var(--mitako-ink)] mb-1">{t('loading.title')}</p>
          <p className="text-[13px] text-slate-700 leading-snug text-pretty transition-opacity duration-200">{hint}</p>
          <div className="flex gap-1 mt-2" aria-hidden="true">
            {[0, 1, 2].map(i => (
              <span key={i} className="w-1.5 h-1.5 rounded-full bg-[var(--mitako-ink)]/50 animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function StreamCursor() {
  return <span className="inline-block w-[2px] h-[1em] ml-0.5 align-[-2px] bg-[var(--mitako-ink)] animate-pulse" aria-hidden="true" />;
}
