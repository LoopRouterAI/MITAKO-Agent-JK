import React from 'react';
import { Headphones, Bot, X, ExternalLink, ClipboardList } from 'lucide-react';
import t from '../../i18n/index.js';

/** 人工接入后：移动端简报浮层，可跳转 PC 客服工作台 */
export default function HandoffBriefOverlay({
  open,
  brief,
  agent,
  onClose,
  onOpenDesk,
}) {
  if (!open || !brief) return null;

  const orders = brief.orders || [];
  const snippet = brief.conversation_snippet || [];

  return (
    <div className="absolute inset-0 z-40 flex items-end sm:items-center justify-center p-3 bg-slate-900/40 backdrop-blur-[2px] animate-fade-up">
      <div
        className="w-full max-w-md max-h-[min(82dvh,640px)] flex flex-col rounded-2xl border border-teal-200/60 bg-white shadow-2xl overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-labelledby="handoff-brief-title"
      >
        <div className="px-4 py-3 border-b border-teal-100 bg-gradient-to-r from-teal-50 to-emerald-50 flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center text-white flex-shrink-0">
            <Headphones className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p id="handoff-brief-title" className="text-sm font-bold text-slate-900">
              {t('handoff.overlayTitle')}
            </p>
            {agent?.agent_id && (
              <p className="text-xs text-teal-700 font-mono mt-0.5">
                {t('handoff.agentId', 'zh-CN', { id: agent.agent_id })}
                {agent?.name ? ` · ${agent.name}` : ''}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/80 text-slate-500"
            aria-label={t('handoff.overlayClose')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 console-scroll text-sm">
          <section>
            <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wide mb-1">{t('transfer.briefSummary')}</h4>
            <p className="text-slate-800 leading-relaxed">{brief.summary}</p>
          </section>
          {orders.length > 0 && (
            <section>
              <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wide mb-1">{t('transfer.briefOrders')}</h4>
              <ul className="space-y-1">
                {orders.map((o, i) => (
                  <li key={i} className="text-xs font-mono bg-slate-50 border border-slate-100 rounded-lg px-2 py-1.5">{o}</li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wide mb-1">{t('transfer.briefReason')}</h4>
            <p className="text-slate-700">{brief.why_ai_cannot_handle || brief.reason}</p>
          </section>
          {snippet.length > 0 && (
            <section>
              <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wide mb-2">{t('handoff.snippetTitle')}</h4>
              <div className="space-y-2">
                {snippet.slice(-6).map((m, i) => (
                  <div key={i} className={`text-xs rounded-xl px-3 py-2 ${m.role === 'user' ? 'bg-[var(--mitako-purple)]/10 text-slate-800 ml-4' : 'bg-slate-50 border border-slate-100 mr-4'}`}>
                    <span className="font-bold text-[10px] text-slate-400 block mb-0.5">{m.role === 'user' ? '用户' : 'AI'}</span>
                    {m.content}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

        <div className="p-3 border-t border-slate-100 flex flex-col gap-2 bg-slate-50/80">
          <button
            type="button"
            onClick={onOpenDesk}
            className="w-full min-h-[44px] rounded-xl bg-teal-600 hover:bg-teal-700 text-white text-sm font-bold flex items-center justify-center gap-2"
          >
            <ExternalLink className="w-4 h-4" />
            {t('handoff.openDesk')}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="w-full min-h-[40px] rounded-xl border border-slate-200 bg-white text-slate-700 text-xs font-semibold flex items-center justify-center gap-2"
          >
            <ClipboardList className="w-4 h-4" />
            {t('handoff.overlayDismiss')}
          </button>
        </div>
      </div>
    </div>
  );
}
