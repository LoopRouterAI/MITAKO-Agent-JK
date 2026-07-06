import React from 'react';
import { ClipboardList, Headphones, X } from 'lucide-react';
import t from '../../i18n/index.js';

export default function HandoffBriefOverlay({ open, brief, agent, onClose }) {
  if (!open || !brief) return null;

  const orders = brief.orders || [];
  const snippet = brief.conversation_snippet || [];

  return (
    <div className="absolute inset-0 z-40 flex items-end sm:items-center justify-center p-3 bg-slate-900/35 animate-fade-up">
      <div
        className="w-full max-w-md max-h-[min(82dvh,640px)] flex flex-col rounded-[8px] border border-slate-200 bg-white shadow-[0_24px_56px_rgba(127,164,49,.18)] overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-labelledby="handoff-brief-title"
      >
        <div className="px-4 py-3 border-b border-slate-200 bg-[var(--mitako-lime)] flex items-start gap-3">
          <div className="w-11 h-11 rounded-[8px] bg-white border border-slate-200 flex items-center justify-center text-[var(--mitako-ink)] flex-shrink-0">
            <Headphones className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p id="handoff-brief-title" className="text-sm font-black text-[var(--mitako-ink)]">
              {t('handoff.overlayTitle')}
            </p>
            {agent?.agent_id && (
              <p className="text-xs text-[var(--mitako-ink)] mt-0.5">
                {agent?.name || t('speakers.humanName')}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-[8px] bg-white border border-slate-200 text-[var(--mitako-ink)]"
            aria-label={t('handoff.overlayClose')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 console-scroll text-sm">
          <section>
            <h4 className="text-xs font-black text-slate-500 uppercase tracking-wide mb-1">{t('transfer.briefSummary')}</h4>
            <p className="text-slate-800 leading-relaxed">{brief.summary}</p>
          </section>
          {orders.length > 0 && (
            <section>
              <h4 className="text-xs font-black text-slate-500 uppercase tracking-wide mb-1">{t('transfer.briefOrders')}</h4>
              <ul className="space-y-1">
                {orders.map((o, i) => (
                  <li key={i} className="text-xs font-mono bg-[#f7f7f2] border border-slate-200 rounded-[8px] px-2 py-1.5">{o}</li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <h4 className="text-xs font-black text-slate-500 uppercase tracking-wide mb-1">{t('transfer.briefReason')}</h4>
            <p className="text-slate-700">{brief.reason || '已为您转接人工客服继续处理。'}</p>
          </section>
          {snippet.length > 0 && (
            <section>
              <h4 className="text-xs font-black text-slate-500 uppercase tracking-wide mb-2">{t('handoff.snippetTitle')}</h4>
              <div className="space-y-2">
                {snippet.slice(-6).map((m, i) => (
                  <div key={i} className={`text-xs rounded-[8px] px-3 py-2 border border-slate-200 ${m.role === 'user' ? 'bg-[var(--mitako-lime)] ml-4' : 'bg-white mr-4'}`}>
                    <span className="font-black text-[10px] text-slate-500 block mb-0.5">{m.role === 'user' ? t('desk.roleUser') : t('desk.roleAi')}</span>
                    {m.content}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

        <div className="p-3 border-t border-slate-200 flex flex-col gap-2 bg-white">
          <button
            type="button"
            onClick={onClose}
            className="w-full min-h-[44px] rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border border-slate-200 shadow-[0_10px_24px_rgba(127,164,49,.14)] text-sm font-black flex items-center justify-center gap-2"
          >
            <ClipboardList className="w-4 h-4" />
            {t('handoff.overlayDismiss')}
          </button>
        </div>
      </div>
    </div>
  );
}
