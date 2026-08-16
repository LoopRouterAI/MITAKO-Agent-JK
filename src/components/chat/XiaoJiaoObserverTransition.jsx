import React from 'react';
import { Bot, Headphones } from 'lucide-react';
import t from '../../i18n/index.js';
import { MITAKO_AGENT_AVATAR } from '../../constants/memeMap.js';

export default function XiaoJiaoObserverTransition() {
  return (
    <div
      className="p-4 rounded-[8px] border border-slate-200 w-full max-w-[340px] animate-fade-up bg-white shadow-[0_12px_28px_rgba(127,164,49,.16)] overflow-hidden relative"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-3 relative z-10">
        <div className="relative w-12 h-12 flex-shrink-0 observer-shrinks">
          <img src={MITAKO_AGENT_AVATAR} alt="" className="w-12 h-12 rounded-[8px] border border-slate-200 object-cover object-top" />
          <span className="absolute -top-1 -right-1 w-5 h-5 rounded-[8px] bg-white border border-slate-200 text-[var(--mitako-ink)] flex items-center justify-center observer-badge-out">
            <Bot className="w-3 h-3" />
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <h4 className="text-xs font-black text-[var(--mitako-ink)]">{t('transfer.observerTitle')}</h4>
          <p className="text-[11px] text-slate-600 mt-0.5 text-pretty leading-relaxed">{t('transfer.observerDesc')}</p>
        </div>
        <div className="w-10 h-10 rounded-[8px] bg-[var(--mitako-lime)] border border-slate-200 flex items-center justify-center text-[var(--mitako-ink)] observer-human-in flex-shrink-0">
          <Headphones className="w-5 h-5" />
        </div>
      </div>
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          .observer-shrinks { animation: observerShrink 1.2s ease forwards 0.2s; }
          .observer-badge-out { animation: observerFade 0.8s ease forwards 0.6s; }
          .observer-human-in { animation: observerPop 0.5s ease forwards 0.9s; opacity: 0; }
          @keyframes observerShrink {
            0% { transform: scale(1); opacity: 1; }
            100% { transform: scale(0.72) translateX(-8px); opacity: 0.55; }
          }
          @keyframes observerFade { to { opacity: 0.35; transform: scale(0.85); } }
          @keyframes observerPop { from { opacity: 0; transform: scale(0.6); } to { opacity: 1; transform: scale(1); } }
        }
      `}</style>
    </div>
  );
}
