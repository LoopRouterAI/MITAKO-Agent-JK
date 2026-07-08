import { defineComponent, createLibrary } from './cardRuntime.js';
import { z } from 'zod/v4';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  Check,
  ClipboardCheck,
  Gift,
  Headphones,
  Loader2,
  Package,
  Phone,
  Ticket,
  UserCheck,
} from 'lucide-react';
import t from '../../i18n/index.js';
import XiaoJiaoObserverTransition from '../chat/XiaoJiaoObserverTransition.jsx';
import { useLoadingHint } from '../../hooks/useLoadingHint.js';
import { sanitizePublicText } from '../../utils/publicText.js';
import { formatPublicOrderRef } from '../../utils/orderHelpers.js';

const shell = 'w-full max-w-[380px] rounded-lg border border-slate-200 bg-white text-left shadow-[0_16px_38px_rgba(16,19,31,0.08)] animate-fade-up';
const tile = 'rounded-lg border border-slate-200 bg-slate-50';
const primaryBtn = 'min-h-[44px] rounded-lg border border-slate-200 bg-[var(--mitako-lime)] px-4 py-2.5 text-sm font-black text-slate-950 shadow-[0_10px_24px_rgba(127,164,49,0.22)] transition-transform active:translate-y-[1px]';
const secondaryBtn = 'min-h-[42px] rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-black text-slate-800 hover:bg-slate-50';

function publicText(value) {
  return sanitizePublicText(value);
}

function IconBox({ children, tone = 'lime' }) {
  return (
    <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-slate-200 shadow-[0_8px_18px_rgba(16,19,31,0.06)] ${
      tone === 'lime' ? 'bg-[var(--mitako-lime-soft)]' : 'bg-white'
    }`}>
      {children}
    </div>
  );
}

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
      <div className={`${shell} p-4 select-none`}>
        <div className="mb-4 flex items-center justify-between gap-3 border-b border-slate-200 pb-3">
          <div className="flex items-center gap-3">
            <IconBox><Gift className="h-5 w-5" aria-hidden="true" /></IconBox>
            <div>
              <p className="text-sm font-black text-slate-950">
                {isVirtual ? t('cards.compensationVirtualTitle') : t('cards.compensationCouponTitle')}
              </p>
              <p className="text-xs font-semibold text-slate-500">待客服确认</p>
            </div>
          </div>
          <span className="rounded-md border border-slate-200 bg-[var(--mitako-lime)] px-2 py-1 text-xs font-black">建议</span>
        </div>
        {isVirtual ? (
          <div className="mb-3 grid gap-2">
            <div className={`${tile} flex items-center gap-3 p-3`}>
              <Ticket className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
              <div>
                <h4 className="text-xs font-black text-slate-900">500 平台积分</h4>
                <p className="mt-0.5 text-[11px] text-slate-500">客服确认后可作为关怀权益处理</p>
              </div>
            </div>
            <div className={`${tile} flex items-center gap-3 p-3`}>
              <Package className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
              <div>
                <h4 className="text-xs font-black text-slate-900">优先发货标记</h4>
                <p className="mt-0.5 text-[11px] text-slate-500">提交后进入服务处理清单</p>
              </div>
            </div>
          </div>
        ) : (
          <div className={`${tile} mb-3 flex items-center gap-3 p-4`}>
            <div className="font-mono text-3xl font-black tabular-nums text-slate-950">
              <span className="mr-0.5 text-sm font-semibold">¥</span>{amount}
            </div>
            <div className="border-l border-slate-200 pl-3">
              <h4 className="text-xs font-black text-slate-900">补偿申请建议</h4>
              <p className="mt-1 text-[11px] text-slate-500">客服确认后再执行</p>
            </div>
          </div>
        )}
        <p className="text-pretty text-[11px] leading-relaxed text-slate-600">{publicText(msg)}</p>
      </div>
    );
  },
});

export const OrderProgressCard = defineComponent({
  name: 'OrderProgressCard',
  props: z.object({
    order_id: z.string(),
    item_name: z.string(),
    total_amount: z.number().optional(),
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
      if (status === 'completed') return 'bg-[var(--mitako-lime)] text-slate-950';
      if (status === 'current') return 'bg-white text-slate-950';
      if (status === 'delayed') return 'bg-white text-red-700';
      return 'bg-slate-100 text-slate-500';
    };
    return (
      <div className={`${shell} p-4 select-none`}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <span className="text-xs font-black text-slate-950">{t('cards.orderProgressTitle')}</span>
          <span className="font-mono text-[10px] text-slate-500">{formatPublicOrderRef(order_id)}</span>
        </div>
        <div className={`${tile} mb-3 flex gap-3 p-3`}>
          <IconBox><Package className="h-5 w-5" aria-hidden="true" /></IconBox>
          <div className="min-w-0 flex-1">
            <h4 className="truncate text-xs font-black text-slate-900">{publicText(item_name)}</h4>
            {typeof total_amount === 'number' && (
              <p className="mt-0.5 font-mono text-[10px] font-semibold text-slate-500">¥{total_amount}</p>
            )}
          </div>
        </div>
        <div className="grid grid-cols-5 gap-1.5 rounded-lg border border-slate-200 bg-white p-2">
          {progress_steps.map((step, idx) => (
            <div key={`${step.label}-${idx}`} className="min-w-0 text-center">
              <div className={`mx-auto flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 text-[10px] font-black ${statusClass(step.status)}`}>
                {step.status === 'completed' ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : idx + 1}
              </div>
              <span className="mt-1.5 block text-[9px] font-black leading-tight text-slate-700">{publicText(step.label)}</span>
              <span className="mt-0.5 block text-[8px] leading-tight text-slate-500">{publicText(step.date)}</span>
            </div>
          ))}
        </div>
        {delay_reason && (
          <div className="mt-3 flex gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] text-red-700">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
            <span className="text-pretty">异常说明：{publicText(delay_reason)}</span>
          </div>
        )}
      </div>
    );
  },
});

export const QueryStatusCard = defineComponent({
  name: 'QueryStatusCard',
  props: z.object({
    step: z.string(),
    streamReply: z.boolean().optional(),
    headline: z.string().optional(),
    hintOverride: z.string().optional(),
  }),
  component: ({ props }) => {
    const { step, streamReply = true, headline, hintOverride } = props;
    const hint = useLoadingHint(step, step !== 'done');
    const stepsList = [
      { key: 'intent', label: t('cards.queryStepIntent') },
      { key: 'query', label: t('cards.queryStepQuery') },
      { key: 'compensate', label: t('cards.queryStepCompensate') },
      { key: 'reply', label: t('cards.queryStepReply') },
    ];
    const stepOrder = ['intent', 'query', 'compensate', 'reply', 'done'];
    const currentIdx = step === 'done' ? 99 : stepOrder.indexOf(step);
    const activeStep = stepsList.find(item => stepOrder.indexOf(item.key) === currentIdx) || stepsList[0];
    const showTyping = step === 'reply' && !streamReply;
    const progressPct = step === 'done' ? 100 : Math.max(8, ((currentIdx + 1) / stepsList.length) * 100);
    const titleMap = {
      intent: '正在召唤AI客服',
      query: '正在同步订单与服务记录',
      compensate: '正在匹配处理方案',
      reply: '正在整理可回复内容',
      done: '已完成核实',
    };
    const statusHints = {
      intent: '先理解您想问什么，再决定要查订单、物流、售后还是VIP客服协助。',
      query: '正在同步订单、物流节点与服务上下文。',
      compensate: '正在按客服 SOP 匹配可建议方案；退款、补发、拒赔仍需VIP客服或甲方系统确认。',
      reply: '正在把查询结果整理成用户能听懂的回复。',
      done: '本轮处理已结束。',
    };
    const liveTitle = publicText(headline) || titleMap[step] || titleMap.intent;

    return (
      <div className={`${shell} overflow-hidden select-none`}>
        <div className="p-4 sm:p-5">
          <div className="mb-4 flex items-start gap-3">
            <div className="relative flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-[var(--mitako-lime-soft)] shadow-[0_8px_18px_rgba(16,19,31,0.06)]">
              {step !== 'done' && (
                <motion.span
                  className="absolute inset-1 rounded-[8px] border-2 border-[var(--mitako-lime-deep)]"
                  animate={{ scale: [0.86, 1.08, 0.86], opacity: [0.35, 0.82, 0.35] }}
                  transition={{ duration: 1.4, repeat: Infinity, ease: 'easeInOut' }}
                  aria-hidden="true"
                />
              )}
              <Loader2 className={`relative h-5 w-5 text-[var(--mitako-ink)] ${step !== 'done' ? 'animate-spin' : ''}`} aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <p className="flex items-center gap-2 text-xs font-black text-slate-950">{liveTitle}</p>
              <p className="mt-1 text-[11px] leading-snug text-slate-600">
                当前环节：<span className="font-black text-slate-900">{activeStep.label}</span>
                {showTyping && <span className="text-slate-900"> / {t('agent.typing')}</span>}
              </p>
            </div>
          </div>
          <div className="mb-4 h-2 overflow-hidden rounded-none border border-slate-200 bg-white">
            <motion.div
              className="h-full bg-[var(--mitako-lime)]"
              initial={false}
              animate={{ width: `${progressPct}%` }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            />
          </div>
          <p className="text-pretty mb-4 min-h-[2.75rem] text-[14px] font-semibold leading-relaxed text-slate-800" role="status" aria-live="polite">
            {showTyping ? t('agent.typing') : publicText(hintOverride) || hint}
          </p>
          <div className="mb-3 rounded-lg border border-slate-200 bg-[var(--mitako-lime-soft)] px-3 py-2 text-[11px] font-semibold leading-relaxed text-slate-700">
            {statusHints[step] || statusHints.intent}
            {step !== 'done' && (
              <span className="ml-1 inline-flex align-middle">
                {[0, 1, 2].map(i => (
                  <span
                    key={i}
                    className="mx-0.5 inline-block h-1.5 w-1.5 rounded-full bg-[var(--mitako-ink)]/45 animate-bounce"
                    style={{ animationDelay: `${i * 0.12}s` }}
                  />
                ))}
              </span>
            )}
          </div>
          <div className="grid grid-cols-4 gap-1.5 rounded-lg border border-slate-200 bg-white p-2.5">
            {stepsList.map((item, idx) => {
              const orderIdx = stepOrder.indexOf(item.key);
              const isCompleted = step === 'done' || orderIdx < currentIdx;
              const isActive = step !== 'done' && orderIdx === currentIdx;
              return (
                <div key={item.key} className="text-center">
                  <div className={`mx-auto flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-[11px] font-black transition-all ${
                    isCompleted || isActive ? 'bg-[var(--mitako-lime)] text-slate-950' : 'bg-slate-50 text-slate-400'
                  }`}>
                    {isCompleted ? <Check className="h-4 w-4" aria-hidden="true" /> : idx + 1}
                  </div>
                  <span className={`mt-1.5 block text-[9px] font-black leading-tight ${isActive ? 'text-slate-950' : 'text-slate-500'}`}>{item.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  },
});

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
    const { order_id, item_name, status_label, reason, onConfirm, onBrowse } = props;
    return (
      <div className={`${shell} overflow-hidden`}>
        <div className="flex items-center gap-2 border-b border-slate-200 bg-[var(--mitako-lime)] px-4 py-3">
          <Package className="h-4 w-4" aria-hidden="true" />
          <span className="text-xs font-black text-slate-950">{t('welcome.suggestTitle')}</span>
        </div>
        <div className="flex gap-3 p-4">
          <IconBox tone="white"><Package className="h-6 w-6" aria-hidden="true" /></IconBox>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-black leading-snug text-slate-900">{publicText(item_name)}</p>
            <p className="mt-0.5 font-mono text-[11px] text-slate-500">{formatPublicOrderRef(order_id)}</p>
            {status_label && (
              <span className="mt-2 inline-flex rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-black text-slate-900">
                {publicText(status_label)}
              </span>
            )}
            {reason && (
              <p className="mt-2 text-[11px] leading-snug text-slate-600">
                {t('welcome.suggestReasonPrefix')}：{publicText(reason)}
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-2 px-4 pb-4">
          <button type="button" onClick={() => onConfirm?.({ order_id, item_name })} className={primaryBtn}>
            {t('welcome.suggestConfirm')}
          </button>
          <button type="button" onClick={() => onBrowse?.()} className={secondaryBtn}>
            {t('welcome.suggestBrowse')}
          </button>
        </div>
      </div>
    );
  },
});

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
      <div className={`${shell} p-4 select-none`}>
        <div className="mb-3 flex items-start gap-3">
          <IconBox><Headphones className="h-5 w-5" aria-hidden="true" /></IconBox>
          <div>
            <h4 className="text-sm font-black text-slate-950">{t('transfer.promptTitle')}</h4>
            <p className="text-pretty mt-1 text-[11px] leading-relaxed text-slate-600">{t('transfer.promptDesc')}</p>
            {emotionLevel >= 4 && (
              <p className="mt-1.5 text-[10px] font-bold text-red-700">当前情绪较强，VIP客服会更适合继续处理。</p>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-2 xs:flex-row">
          <button type="button" onClick={() => onConfirm?.()} className={`${primaryBtn} flex-1 text-xs`}>
            {t('transfer.promptConfirm')}
          </button>
          <button type="button" onClick={() => onDismiss?.()} className={`${secondaryBtn} flex-1 text-xs`}>
            {t('transfer.promptDismiss')}
          </button>
        </div>
      </div>
    );
  },
});

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
      <div className={`${shell} p-4`}>
        <div className="flex items-center gap-3">
          <IconBox>{connected ? <UserCheck className="h-5 w-5" aria-hidden="true" /> : <Phone className="h-5 w-5" aria-hidden="true" />}</IconBox>
          <div className="min-w-0">
            <h4 className="text-xs font-black text-slate-950">
              {connected ? t('cards.transferConnected') : t('transfer.queueTitle')}
            </h4>
            {!connected ? (
              <>
                <p className="text-pretty mt-0.5 text-[10px] leading-relaxed text-slate-600">{t('transfer.queueBusy')}</p>
                <p className="mt-0.5 text-pretty text-[10px] text-slate-600">{t('transfer.queueDesc', 'zh-CN', { ahead, eta })}</p>
                <p className="mt-1 font-mono text-[10px] text-slate-500">{t('transfer.queuePosition', 'zh-CN', { position })}</p>
              </>
            ) : (
              <p className="mt-0.5 text-[10px] text-slate-500">{t('cards.transferConnectedDesc')}</p>
            )}
            {reason && !connected && (
              <p className="mt-1 truncate text-[9px] text-slate-600">原因：{publicText(reason)}</p>
            )}
          </div>
        </div>
      </div>
    );
  },
});

export const ObserverTransitionCard = defineComponent({
  name: 'ObserverTransitionCard',
  props: z.object({}),
  component: () => <XiaoJiaoObserverTransition />,
});

export const TransferStatusCard = defineComponent({
  name: 'TransferStatusCard',
  props: z.object({ status: z.string() }),
  component: ({ props }) => {
    const calling = props.status === 'calling';
    return (
      <div className={`${shell} flex items-center gap-3 p-4`}>
        <IconBox>{calling ? <Phone className="h-5 w-5" aria-hidden="true" /> : <UserCheck className="h-5 w-5" aria-hidden="true" />}</IconBox>
        <div>
          <h4 className="text-xs font-black text-slate-950">{calling ? t('cards.transferCalling') : t('cards.transferConnected')}</h4>
          <p className="text-pretty mt-0.5 text-[10px] text-slate-500">
            {calling ? t('cards.transferCallingDesc') : t('cards.transferConnectedDesc')}
          </p>
        </div>
      </div>
    );
  },
});

export const BusinessActionCard = defineComponent({
  name: 'BusinessActionCard',
  props: z.object({
    sop: z.any(),
    action: z.any(),
  }),
  component: ({ props }) => {
    const sop = props.sop || {};
    const action = props.action || {};
    const publicActionType = String(action.type || '');
    const actionLabelMap = {
      after_sales_card: '售后处理卡',
      warehouse_task: '仓库核查任务',
      ticket: '客服授权工单',
      none: '继续核对',
      service_after_sales_card: '售后处理卡',
      service_warehouse_task: '仓库核查任务',
      service_finance_refund_review: '退款复核',
      service_qc_sop_proposal: '服务质检建议',
      service_private_domain_task: '后续跟进任务',
    };
    const actionLabel = publicText(actionLabelMap[publicActionType] || action.label || '待客服确认');
    const sopLabel = publicText(sop.sop_branch || t('cards.generalInquiry'));
    const order = sop.order_snapshot || {};
    const orderRef = sop.order_id ? formatPublicOrderRef(sop.order_id) : '';
    const orderStatus = publicText(order.status_label || order.status || '已定位订单');
    const orderItem = publicText(order.item_name || '');
    const reasonText = publicText(action.reason || t('cards.businessAuditDefault'));
    const summaryRows = orderRef
      ? [
          ['咨询订单', orderRef],
          ['当前状态', orderStatus],
          ...(orderItem ? [['相关商品', orderItem]] : []),
          [t('cards.businessTicketType'), sopLabel],
          [t('cards.businessPlannedAction'), actionLabel],
        ]
      : [
          [t('cards.businessTicketType'), sopLabel],
          [t('cards.businessPlannedAction'), actionLabel],
        ];
    return (
      <div className={`${shell} p-4`} role="status" aria-live="polite">
        <div className="mb-3 flex items-start gap-2">
          <IconBox><ClipboardCheck className="h-4.5 w-4.5" aria-hidden="true" /></IconBox>
          <div>
            <p className="text-xs font-black text-slate-950">
              {orderRef ? '订单服务进度' : t('cards.businessActionTitle')}
            </p>
            <p className="text-[10px] text-slate-500">
              {orderRef ? '已核对当前订单信息，下面是可继续处理的状态。' : t('cards.businessActionProgressNote')}
            </p>
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-gradient-to-r from-[var(--mitako-lime-soft)] to-white px-3 py-2 text-[11px]">
          {summaryRows.map(([label, value]) => (
            <div key={label} className="flex items-start justify-between gap-3 py-1">
              <span className="shrink-0 text-slate-500">{label}</span>
              <span className="text-right font-black leading-snug text-slate-900">{value}</span>
            </div>
          ))}
        </div>
        <p className="text-pretty mt-3 text-[11px] leading-relaxed text-slate-600">{reasonText}</p>
        {action.requires_human && (
          <p className="mt-2 inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] font-black text-amber-800">
            <AlertTriangle className="h-3 w-3" aria-hidden="true" /> {t('cards.requiresHuman')}
          </p>
        )}
      </div>
    );
  },
});

export const mitakoOpenUILibrary = createLibrary({
  components: [
    CompensationCard,
    OrderProgressCard,
    QueryStatusCard,
    WelcomeOrderCard,
    HandoffPromptCard,
    HandoffQueueCard,
    ObserverTransitionCard,
    TransferStatusCard,
    BusinessActionCard,
  ],
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
  business_action: BusinessActionCard,
};
