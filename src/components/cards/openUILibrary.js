import { defineComponent, createLibrary } from '@openuidev/react-lang';
import { z } from 'zod/v4';
import { Check, AlertTriangle, Gift, Ticket, Package, Loader2, Phone, UserCheck } from 'lucide-react';
import t from '../../i18n/index.js';

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

/** 核实进度 — 对齐 SOP 四步 */
export const QueryStatusCard = defineComponent({
  name: 'QueryStatusCard',
  props: z.object({ step: z.string() }),
  component: ({ props }) => {
    const { step } = props;
    const stepsList = [
      { key: 'intent', label: t('cards.queryStepIntent') },
      { key: 'query', label: t('cards.queryStepQuery') },
      { key: 'compensate', label: t('cards.queryStepCompensate') },
      { key: 'reply', label: t('cards.queryStepReply') },
    ];
    const stepOrder = ['intent', 'query', 'compensate', 'reply', 'done'];
    const currentIdx = step === 'done' ? 99 : stepOrder.indexOf(step);

    return (
      <div className="glass-panel p-4 w-full max-w-[340px] text-left select-none animate-fade-up">
        <div className="flex justify-between items-center mb-3">
          <span className="text-[11px] font-bold text-[var(--mitako-purple)] flex items-center gap-1.5">
            <Loader2 className={`w-3.5 h-3.5 ${step !== 'done' ? 'animate-spin' : ''}`} />
            {t('cards.queryTitle')}
          </span>
          <span className="text-[9px] font-mono text-slate-400">{step.toUpperCase()}</span>
        </div>
        <div className="flex justify-between bg-slate-50/70 p-2 rounded-xl border border-slate-100 mb-3">
          {stepsList.map((st, idx) => {
            const orderIdx = stepOrder.indexOf(st.key);
            const isCompleted = step === 'done' || orderIdx < currentIdx;
            const isActive = step !== 'done' && orderIdx === currentIdx;
            return (
              <div key={st.key} className="flex flex-col items-center flex-1">
                <div className={`w-7 h-7 rounded-full border flex items-center justify-center text-[10px] font-bold transition-all ${
                  isCompleted ? 'bg-emerald-50 border-emerald-200 text-emerald-600' :
                  isActive ? 'bg-[#C8FF1A]/20 border-[var(--mitako-lime-deep)] text-slate-800 shadow-[var(--shadow-lime)]' :
                  'bg-white border-slate-200 text-slate-400'
                }`}>
                  {isCompleted ? <Check className="w-3.5 h-3.5" /> : idx + 1}
                </div>
                <span className={`text-[9px] mt-1 font-semibold text-center ${isActive ? 'text-slate-900' : 'text-slate-400'}`}>{st.label}</span>
              </div>
            );
          })}
        </div>
      </div>
    );
  },
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
  components: [CompensationCard, OrderProgressCard, QueryStatusCard, TransferStatusCard],
});

export const CARD_RENDERERS = {
  compensation: CompensationCard,
  order_progress: OrderProgressCard,
  query_status: QueryStatusCard,
  transfer_status: TransferStatusCard,
};
