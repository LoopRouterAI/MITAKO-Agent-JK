import React from 'react';
import t from '../../i18n/index.js';

const STATUS_TEXT = {
  not_requested: t('conversationState.statusNotRequested'),
  requested: t('conversationState.statusRequested'),
  accepted: t('conversationState.statusAccepted'),
  queued: t('conversationState.statusQueued'),
  succeeded: t('conversationState.statusSucceeded'),
  failed: t('conversationState.statusFailed'),
  pending_human: t('conversationState.statusPendingHuman'),
};

const STATUS_STYLE = {
  queued: 'border-amber-200 bg-amber-50 text-amber-800',
  succeeded: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  failed: 'border-rose-200 bg-rose-50 text-rose-800',
  pending_human: 'border-amber-200 bg-amber-50 text-amber-800',
};

export default function ConversationStateCard({ state, compact = false }) {
  const action = state?.action_state || {};
  const nextStep = state?.next_step || {};
  const status = action.status || 'not_requested';
  if (!state || (!state.core_conclusion && !nextStep.label && status === 'not_requested')) return null;

  return (
    <section
      data-testid="conversation-state-card"
      className={`mx-3 rounded-[8px] border px-3 py-2 ${STATUS_STYLE[status] || 'border-slate-200 bg-slate-50 text-slate-700'}`}
      aria-label={t('conversationState.title')}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-black">{t('conversationState.title')}</p>
        <span className="rounded-[6px] border border-current/20 bg-white/70 px-2 py-0.5 text-[11px] font-black">
          {STATUS_TEXT[status] || t('conversationState.unknown')}
        </span>
      </div>
      {!compact && nextStep.label ? (
        <p className="mt-1 text-xs font-semibold leading-relaxed">{nextStep.label}</p>
      ) : null}
      {action.receipt_id ? (
        <p className="mt-1 break-all font-mono text-[11px] opacity-80">
          {t('conversationState.receipt')}：{action.receipt_id}
        </p>
      ) : null}
    </section>
  );
}
