import { defineComponent, createLibrary } from '@openuidev/react-lang';
import { z } from 'zod/v4';
import { Check, AlertTriangle, Gift, Ticket, Package, Loader2, Phone, UserCheck, Sparkles } from 'lucide-react';
import t from '../../i18n/index.js';
import XiaoJiaoObserverTransition from '../chat/XiaoJiaoObserverTransition.jsx';
import { useLoadingHint } from '../../hooks/useLoadingHint.js';
import { getOrderDisplayName, getOrderStatusClass, formatOrderDate } from '../../utils/orderHelpers.js';

/** 补偿申请卡片 — SOP 申请制话术 */
export const CompensationCard = defineComponent({
  name: 'CompensationCard',
  props: z.object({
    type: z.string(),
    amount: z.number().optional(),
    msg: z.string(),
  }),
  component: ({ props }) => {
    const { type, amount, msg } = props;
    const isVirtual = type === 'virtual_pack';
    return (
      <div className="glass-panel p-5 w-full max-w-[340px] text-left select-none relative overflow-hidden animate-fade-up">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-bold text-[var(--mitako-purple)] tracking-wide flex items-center gap-1.5">
            <Gift className="w-3.5 h-3.5" />
            {isVirtual ? t('cards.compensationVirtualTitle') : t('cards.compensationCouponTitle')}
          </span>
          <span className="text-[10px] text-slate-400 font-mono uppercase">Pending</span>
        </div>
        {isVirtual ? (
          <div className="space-y-2.5 mb-3">
            <div className="flex items-center gap-3 bg-slate-50/80 p-3 rounded-xl border border-slate-100">
              <Ticket className="w-5 h-5 text-[var(--mitako-purple)] flex-shrink-0" />
              <div>
                <h4 className="text-xs font-bold text-slate-800">500 平台积分</h4>
                <p className="text-[11px] text-slate-500 mt-0.5">申请提交后，下次下单可折抵 5 元</p>
              </div>
            </div>
            <div className="flex items-center gap-3 bg-slate-50/80 p-3 rounded-xl border border-slate-100">
              <Package className="w-5 h-5 text-[var(--mitako-lime-deep)] flex-shrink-0" />
              <div>
                <h4 className="text-xs font-bold text-slate-800">优先发货标记</h4>
                <p className="text-[11px] text-slate-500 mt-0.5">申请提交后，系统将挂载出荷顺位</p>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 bg-[#7B61FF]/5 p-4 rounded-xl border border-[#7B61FF]/12 mb-3">
            <div className="text-3xl font-black text-[var(--mitako-purple)] tabular-nums">
              <span className="text-sm font-semibold mr-0.5">¥</span>{amount}
            </div>
            <div className="border-l border-slate-200 pl-3">
              <h4 className="text-xs font-bold text-slate-800">免邮补偿券</h4>
              <p className="text-[11px] text-slate-500 mt-1">有效期 30 天 · 待审核激活</p>
            </div>
          </div>
        )}
        <p className="text-[11px] text-slate-500 leading-relaxed text-pretty">{msg}</p>
      </div>
    );
  },
});

/** 物流进度卡片 */
export const OrderProgressCard = defineComponent({
  name: 'OrderProgressCard',
  props: z.object({
    order_id: z.string(),
    item_name: z.string(),
    total_amount: z.number(),
    progress_steps: z.array(z.object({
      label: z.string(),
      status: z.string(),
      date: z.string(),
    })),
    delay_reason: z.string().optional(),
  }),
  component: ({ props }) => {
    const { order_id, item_name, total_amount, progress_steps, delay_reason } = props;
    const statusClass = (status) => {
      if (status === 'completed') return 'bg-emerald-50 border-emerald-200 text-emerald-600';
      if (status === 'current') return 'bg-[#7B61FF]/10 border-[#7B61FF]/30 text-[var(--mitako-purple)]';
      if (status === 'delayed') return 'bg-[#FF8B38]/10 border-[#FF8B38]/30 text-[var(--mitako-orange)] animate-pulse';
      return 'bg-slate-50 border-slate-200 text-slate-400';
    };
    return (
      <div className="glass-panel p-4 w-full max-w-[380px] text-left select-none animate-fade-up">
        <div className="flex justify-between items-center mb-3">
          <span className="text-[11px] font-bold text-[var(--mitako-purple)]">{t('cards.orderProgressTitle')}</span>
          <span className="text-[10px] text-slate-400 font-mono">#{order_id}</span>
        </div>
        <div className="bg-slate-50/80 p-3 rounded-xl border border-slate-100 mb-3 flex gap-3">
          <div className="w-10 h-10 rounded-lg bg-white border border-slate-200 flex items-center justify-center">
            <Package className="w-5 h-5 text-[var(--mitako-purple)]" />
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="text-xs font-bold text-slate-800 truncate">{item_name}</h4>
            <p className="text-[10px] text-slate-500 font-medium tabular-nums">¥{total_amount}</p>
          </div>
        </div>
        <div className="flex justify-between px-1 py-2 bg-slate-50/60 rounded-xl border border-slate-100">
          {progress_steps.map((step, idx) => (
            <div key={idx} className="flex flex-col items-center flex-1">
              <div className={`w-7 h-7 rounded-full border flex items-center justify-center text-[10px] font-bold ${statusClass(step.status)}`}>
                {step.status === 'completed' ? <Check className="w-3.5 h-3.5" /> : idx + 1}
              </div>
              <span className="text-[9px] font-semibold text-slate-600 mt-1.5 text-center">{step.label}</span>
              <span className="text-[8px] text-slate-400 mt-0.5 text-center leading-tight">{step.date}</span>
            </div>
          ))}
        </div>
        {delay_reason && (
          <div className="mt-3 px-3 py-2 bg-amber-500/5 border border-amber-500/15 rounded-xl text-[10px] text-amber-700 flex gap-2">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            <span className="text-pretty">异常说明：{delay_reason}</span>
          </div>
        )}
      </div>
    );
  },
});

/** 核实进度 — 唯一 Loading 气泡（查单/物流/权益/回复四步） */
export const QueryStatusCard = defineComponent({
  name: 'QueryStatusCard',
  props: z.object({
    step: z.string(),
    streamReply: z.boolean().optional(),
  }),
  component: ({ props }) => {
    const { step, streamReply = true } = props;
    const hint = useLoadingHint(step, step !== 'done');
    const stepsList = [
      { key: 'intent', label: t('cards.queryStepIntent'), icon: '💬' },
      { key: 'query', label: t('cards.queryStepQuery'), icon: '📦' },
      { key: 'compensate', label: t('cards.queryStepCompensate'), icon: '🎁' },
      { key: 'reply', label: t('cards.queryStepReply'), icon: '✨' },
    ];
    const stepOrder = ['intent', 'query', 'compensate', 'reply', 'done'];
    const currentIdx = step === 'done' ? 99 : stepOrder.indexOf(step);
    const activeStep = stepsList.find(s => stepOrder.indexOf(s.key) === currentIdx) || stepsList[0];
    const showTyping = step === 'reply' && !streamReply;
    const progressPct = step === 'done' ? 100 : Math.max(8, ((currentIdx + 1) / stepsList.length) * 100);

    return (
      <div className="relative w-full text-left select-none animate-fade-up overflow-hidden rounded-2xl border border-[#7B61FF]/25 bg-gradient-to-br from-white via-[#7B61FF]/[0.06] to-[#42C8FF]/[0.08] shadow-[0_12px_40px_rgba(123,97,255,0.14)]">
        <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-2xl" aria-hidden="true">
          <div className="absolute -inset-y-4 -left-1/2 w-1/2 bg-gradient-to-r from-transparent via-[#7B61FF]/12 to-transparent animate-[scan_2.4s_ease-in-out_infinite]" />
        </div>

        <div className="relative p-4 sm:p-5">
          <div className="flex items-start gap-3 mb-4">
            <div className="relative w-12 h-12 flex-shrink-0">
              <span className="absolute inset-0 rounded-2xl bg-[var(--mitako-lime)]/20 animate-pulse" />
              <img src="/xiaojiao_avatar.png" alt="" className="relative w-12 h-12 rounded-2xl border-2 border-white object-cover shadow-md" />
              <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-emerald-400 border-2 border-white rounded-full" />
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <p className="text-xs font-bold text-[var(--mitako-purple)] flex items-center gap-2">
                <Loader2 className={`w-4 h-4 flex-shrink-0 ${step !== 'done' ? 'animate-spin' : ''}`} />
                {t('cards.queryTitle')}
              </p>
              <p className="text-[11px] text-slate-600 mt-1 leading-snug">
                当前环节：<span className="font-semibold text-slate-800">{activeStep.label}</span>
                {showTyping && <span className="text-[var(--mitako-purple)]"> · {t('agent.typing')}</span>}
              </p>
            </div>
          </div>

          <div className="mb-4">
            <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-[var(--mitako-purple)] to-[var(--mitako-lime-deep)] transition-all duration-500 ease-out"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>

          <p className="text-[14px] text-slate-800 leading-relaxed text-pretty mb-4 min-h-[2.75rem] font-medium" role="status" aria-live="polite">
            {showTyping ? t('agent.typing') : hint}
          </p>

          <div className="grid grid-cols-4 gap-1.5 bg-white/80 backdrop-blur-sm p-2.5 rounded-2xl border border-slate-100/90">
            {stepsList.map((st, idx) => {
              const orderIdx = stepOrder.indexOf(st.key);
              const isCompleted = step === 'done' || orderIdx < currentIdx;
              const isActive = step !== 'done' && orderIdx === currentIdx;
              return (
                <div key={st.key} className="flex flex-col items-center text-center">
                  <div className={`w-8 h-8 rounded-xl border flex items-center justify-center text-[11px] font-bold transition-all ${
                    isCompleted ? 'bg-emerald-50 border-emerald-200 text-emerald-600' :
                    isActive ? 'bg-[#C8FF1A]/35 border-[var(--mitako-lime-deep)] text-slate-900 shadow-[0_0_14px_rgba(200,255,26,0.35)] scale-105' :
                    'bg-slate-50 border-slate-200 text-slate-400'
                  }`}>
                    {isCompleted ? <Check className="w-4 h-4" /> : isActive ? st.icon : idx + 1}
                  </div>
                  <span className={`text-[9px] mt-1.5 font-semibold leading-tight ${isActive ? 'text-slate-900' : 'text-slate-400'}`}>{st.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  },
});

/** 欢迎语推荐订单卡 — 进线时询问是否咨询最可能订单 */
export const WelcomeOrderCard = defineComponent({
  name: 'WelcomeOrderCard',
  props: z.object({
    order_id: z.string(),
    item_name: z.string(),
    status_label: z.string().optional(),
    status: z.string().optional(),
    reason: z.string().optional(),
    thumb_emoji: z.string().optional(),
    thumb_gradient: z.string().optional(),
    onConfirm: z.any().optional(),
    onBrowse: z.any().optional(),
  }),
  component: ({ props }) => {
    const { order_id, item_name, status_label, status, reason, thumb_emoji, thumb_gradient, onConfirm, onBrowse } = props;
    const gradient = thumb_gradient || 'from-[var(--mitako-purple)] to-indigo-500';
    return (
      <div className="w-full rounded-2xl border border-[#7B61FF]/20 bg-white shadow-[0_8px_32px_rgba(123,97,255,0.1)] overflow-hidden animate-fade-up">
        <div className="px-4 py-3 bg-gradient-to-r from-[#7B61FF]/8 to-[#C8FF1A]/10 border-b border-slate-100 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-[var(--mitako-purple)]" />
          <span className="text-xs font-bold text-slate-800">{t('welcome.suggestTitle')}</span>
        </div>
        <div className="p-4 flex gap-3">
          <div className={`w-14 h-14 rounded-xl bg-gradient-to-br ${gradient} flex items-center justify-center text-2xl flex-shrink-0`}>
            {thumb_emoji || '📦'}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold text-slate-800 leading-snug">{item_name}</p>
            <p className="text-[11px] font-mono text-slate-500 mt-0.5">#{order_id}</p>
            {status_label && (
              <span className={`inline-flex mt-2 text-[10px] font-bold px-2 py-0.5 rounded-full border ${getOrderStatusClass(status || 'pending_shipment')}`}>
                {status_label}
              </span>
            )}
            {reason && (
              <p className="text-[11px] text-slate-600 mt-2 leading-snug">
                {t('welcome.suggestReasonPrefix')}：{reason}
              </p>
            )}
          </div>
        </div>
        <div className="px-4 pb-4 flex flex-col gap-2">
          <button
            type="button"
            onClick={() => onConfirm?.({ order_id, item_name })}
            className="w-full min-h-[44px] rounded-xl bg-[var(--mitako-purple)] hover:bg-[var(--mitako-purple-deep)] text-white text-sm font-bold transition-colors"
          >
            {t('welcome.suggestConfirm')}
          </button>
          <button
            type="button"
            onClick={() => onBrowse?.()}
            className="w-full min-h-[40px] rounded-xl border border-slate-200 bg-white text-slate-700 text-xs font-semibold hover:bg-slate-50"
          >
            {t('welcome.suggestBrowse')}
          </button>
        </div>
      </div>
    );
  },
});

/** 转人工确认卡 — 情绪偏高时由 OpenUI 渲染 */
export const HandoffPromptCard = defineComponent({
  name: 'HandoffPromptCard',
  props: z.object({
    emotionLevel: z.number().optional(),
    onConfirm: z.any().optional(),
    onDismiss: z.any().optional(),
  }),
  component: ({ props }) => {
    const { emotionLevel, onConfirm, onDismiss } = props;
    return (
      <div className="glass-panel p-4 w-full max-w-[340px] text-left select-none animate-fade-up border border-rose-200/60 bg-gradient-to-br from-rose-50/90 to-white">
        <div className="flex items-start gap-3 mb-3">
          <div className="w-10 h-10 rounded-xl bg-rose-100 flex items-center justify-center flex-shrink-0">
            <HeadphonesIcon className="w-5 h-5 text-rose-600" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-slate-900">{t('transfer.promptTitle')}</h4>
            <p className="text-[11px] text-slate-600 mt-1 text-pretty leading-relaxed">{t('transfer.promptDesc')}</p>
            {emotionLevel >= 4 && (
              <p className="text-[10px] text-rose-600 font-semibold mt-1.5">当前情绪较激动，人工专员可能更合适</p>
            )}
          </div>
        </div>
        <div className="flex flex-col xs:flex-row gap-2">
          <button
            type="button"
            onClick={() => onConfirm?.()}
            className="flex-1 touch-target text-xs font-bold text-white bg-[var(--mitako-purple)] hover:brightness-105 px-4 py-2.5 rounded-xl transition-transform active:scale-[0.98]"
          >
            {t('transfer.promptConfirm')}
          </button>
          <button
            type="button"
            onClick={() => onDismiss?.()}
            className="flex-1 touch-target text-xs font-bold text-slate-600 bg-white border border-slate-200 px-4 py-2.5 rounded-xl hover:bg-slate-50"
          >
            {t('transfer.promptDismiss')}
          </button>
        </div>
      </div>
    );
  },
});

function HeadphonesIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M3 18v-6a9 9 0 0 1 18 0v6" />
      <path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z" />
    </svg>
  );
}

/** 转人工排队卡 — 排队期间用户仍可继续与 AI 对话 */
export const HandoffQueueCard = defineComponent({
  name: 'HandoffQueueCard',
  props: z.object({
    position: z.number(),
    ahead: z.number(),
    eta: z.number(),
    reason: z.string().optional(),
    status: z.string().optional(),
  }),
  component: ({ props }) => {
    const { position, ahead, eta, reason, status } = props;
    const connected = status === 'connected';
    return (
      <div className={`p-4 rounded-2xl border w-full max-w-[340px] animate-fade-up ${
        connected
          ? 'bg-[#7B61FF]/8 border-[#7B61FF]/20 text-[var(--mitako-purple)]'
          : 'bg-amber-50/90 border-amber-200 text-amber-900'
      }`}>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-white flex items-center justify-center shadow-sm flex-shrink-0">
            {connected ? <UserCheck className="w-5 h-5" /> : <Phone className="w-5 h-5 animate-pulse" />}
          </div>
          <div className="min-w-0">
            <h4 className="text-xs font-bold">
              {connected ? t('cards.transferConnected') : t('transfer.queueTitle')}
            </h4>
            {!connected && (
              <>
                <p className="text-[10px] mt-0.5 text-pretty leading-relaxed">
                  {t('transfer.queueBusy')}
                </p>
                <p className="text-[10px] mt-0.5 text-pretty opacity-90">
                  {t('transfer.queueDesc', 'zh-CN', { ahead, eta })}
                </p>
                <p className="text-[10px] font-mono mt-1 opacity-80">
                  {t('transfer.queuePosition', 'zh-CN', { position })}
                </p>
              </>
            )}
            {connected && (
              <p className="text-[10px] text-slate-500 mt-0.5">{t('cards.transferConnectedDesc')}</p>
            )}
            {reason && !connected && (
              <p className="text-[9px] text-amber-700/80 mt-1 truncate">原因：{reason}</p>
            )}
          </div>
        </div>
      </div>
    );
  },
});

/** 虾饺退下旁听过渡卡 */
export const ObserverTransitionCard = defineComponent({
  name: 'ObserverTransitionCard',
  props: z.object({}),
  component: () => <XiaoJiaoObserverTransition />,
});

/** 转人工状态卡 */
export const TransferStatusCard = defineComponent({
  name: 'TransferStatusCard',
  props: z.object({ status: z.string() }),
  component: ({ props }) => {
    const calling = props.status === 'calling';
    return (
      <div className={`p-4 rounded-2xl border w-full max-w-[340px] flex items-center gap-3 animate-fade-up ${
        calling ? 'bg-amber-50/90 border-amber-200 text-amber-800' : 'bg-[#7B61FF]/8 border-[#7B61FF]/20 text-[var(--mitako-purple)]'
      }`}>
        <div className="w-10 h-10 rounded-xl bg-white flex items-center justify-center shadow-sm">
          {calling ? <Phone className="w-5 h-5 animate-pulse" /> : <UserCheck className="w-5 h-5" />}
        </div>
        <div>
          <h4 className="text-xs font-bold">{calling ? t('cards.transferCalling') : t('cards.transferConnected')}</h4>
          <p className="text-[10px] text-slate-500 mt-0.5 text-pretty">
            {calling ? t('cards.transferCallingDesc') : t('cards.transferConnectedDesc')}
          </p>
        </div>
      </div>
    );
  },
});

export const mitakoOpenUILibrary = createLibrary({
  components: [CompensationCard, OrderProgressCard, QueryStatusCard, WelcomeOrderCard, HandoffPromptCard, HandoffQueueCard, ObserverTransitionCard, TransferStatusCard],
});

export const CARD_RENDERERS = {
  compensation: CompensationCard,
  order_progress: OrderProgressCard,
  query_status: QueryStatusCard,
  welcome_order: WelcomeOrderCard,
  handoff_prompt: HandoffPromptCard,
  handoff_queue: HandoffQueueCard,
  observer_transition: ObserverTransitionCard,
  transfer_status: TransferStatusCard,
};
