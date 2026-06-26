import React from 'react';
import t from '../../i18n/index.js';
import { useLoadingHint } from '../../hooks/useLoadingHint.js';

/** 等待 SSE 首包时的二次元 Loading 气泡 */
export default function XiaoJiaoLoadingBubble({ step = 'intent' }) {
  const hint = useLoadingHint(step, true);

  return (
    <div
      className="px-4 py-3.5 rounded-2xl rounded-tl-md bg-gradient-to-br from-white to-[#7B61FF]/5 border border-[#7B61FF]/15 shadow-sm max-w-[92%]"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-3">
        <div className="relative w-10 h-10 flex-shrink-0" aria-hidden="true">
          <span className="absolute inset-0 rounded-xl bg-[var(--mitako-lime)]/30 animate-pulse" />
          <span className="absolute inset-1 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-lg">
            🦐
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-bold text-[var(--mitako-purple)] mb-1">{t('loading.title')}</p>
          <p className="text-[13px] text-slate-700 leading-snug text-pretty transition-opacity duration-200">
            {hint}
          </p>
          <div className="flex gap-1 mt-2" aria-hidden="true">
            {[0, 1, 2].map(i => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-[var(--mitako-purple)]/40 animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 流式输出时的打字机光标 */
export function StreamCursor() {
  return (
    <span
      className="inline-block w-[2px] h-[1em] ml-0.5 align-[-2px] bg-[var(--mitako-purple)] animate-pulse"
      aria-hidden="true"
    />
  );
}
