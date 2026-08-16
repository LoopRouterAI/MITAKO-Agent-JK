import React, { useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X, Package, AlertCircle, Clock, CheckCircle2 } from 'lucide-react';
import t from '../../i18n/index.js';
import {
  formatOrderDate,
  formatPublicOrderRef,
  getOrderDisplayName,
  getOrderStatusClass,
  getOrderTagLabel,
  sortOrdersByPriority,
} from '../../utils/orderHelpers.js';

const FILTERS = [
  { id: 'all', labelKey: 'order.filterAll' },
  { id: 'attention', labelKey: 'order.filterAttention' },
  { id: 'shipping', labelKey: 'order.filterShipping' },
  { id: 'done', labelKey: 'order.filterDone' },
];

const ATTENTION_TAGS = ['needs_attention', 'delay_risk', 'damage_claim', 'minor_refund', 'lottery_rule_question'];

function hasAttentionSignal(order) {
  const tags = order.tags || [];
  return tags.some(tag => ATTENTION_TAGS.includes(tag)) || (order.delay_days || 0) > 30;
}

function getOrderFocusReason(order) {
  const tags = order.tags || [];
  if (tags.includes('minor_refund')) return '未成年人退款材料待审核，需要客服按材料清单和风控边界处理。';
  if (tags.includes('damage_claim')) return '用户已提交破损售后诉求，需要核对图片、开箱视频和签收节点。';
  if (tags.includes('lottery_rule_question')) return '用户质疑中奖率或活动规则，需要解释公示口径并保留复核入口。';
  if ((order.delay_days || 0) > 30) return `已等待约 ${order.delay_days} 天，优先核对出荷、清关或仓库节点。`;
  if (tags.includes('delay_risk')) return '存在延期风险，需按预售或供应链公告给出明确时间口径。';
  if (tags.includes('newly_shipped')) return '刚发货或刚清关，适合告知当前物流节点和预计更新节奏。';
  if (order.status === 'pending_shipment') return '订单仍在待出库阶段，如未超承诺期可说明仓库处理节奏。';
  if (order.status === 'preorder') return '预售商品需核对到货排期、尾款或取消规则。';
  if (order.status === 'refunded') return '历史售后已处理，可用于核对过往服务记录。';
  return '状态正常，可直接咨询订单、物流、商品或售后细节。';
}

function filterOrders(orders, filterId) {
  if (filterId === 'attention') {
    return orders.filter(hasAttentionSignal);
  }
  if (filterId === 'shipping') {
    return orders.filter(o => ['in_transit', 'pending_shipment', 'preorder'].includes(o.status));
  }
  if (filterId === 'done') {
    return orders.filter(o => ['delivered', 'refunded'].includes(o.status));
  }
  return orders;
}

function OrderCard({ order, selected, onSelect }) {
  const item = order.items?.[0];
  const focusReason = getOrderFocusReason(order);
  return (
    <button
      type="button"
      data-testid="order-card"
      onClick={() => onSelect(order)}
      className={`w-full text-left rounded-[8px] border p-3 transition-all active:scale-[0.99] ${
        selected
          ? 'border-[var(--mitako-ink)] bg-[var(--mitako-lime)] shadow-[0_12px_28px_rgba(127,164,49,.16)]'
          : 'border-[var(--mitako-ink)] bg-white hover:bg-[var(--mitako-lime)]'
      }`}
    >
      <div className="flex gap-3">
        <div className="w-14 h-14 rounded-[8px] bg-white border border-slate-200 flex items-center justify-center flex-shrink-0">
          <Package className="w-6 h-6 text-[var(--mitako-ink)]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-sm font-bold text-slate-800 line-clamp-2 leading-snug">{getOrderDisplayName(order)}</h4>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-[8px] border flex-shrink-0 ${getOrderStatusClass(order.status)}`}>
              {order.status_label || order.status}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">{formatPublicOrderRef(order.order_id)}</p>
          <p className="mt-2 rounded-[8px] border border-slate-200 bg-white/80 px-2 py-1.5 text-[10px] font-semibold leading-snug text-slate-600">
            <span className="font-black text-[var(--mitako-ink)]">{t('order.cardReasonLabel')}：</span>{focusReason}
          </p>
          <div className="flex flex-wrap items-center gap-1.5 mt-2">
            <span className="text-xs font-bold text-[var(--mitako-orange)] tabular-nums">
              {order.total_amount > 0 ? `¥${order.total_amount}` : t('order.lotteryFree')}
            </span>
            <span className="text-[10px] text-slate-400">{formatOrderDate(order.created_at)}</span>
            {order.order_type === 'lottery' && (
              <span className="text-[9px] font-bold text-[var(--mitako-ink)] bg-white border border-[var(--mitako-ink)] px-1.5 py-0.5 rounded-[8px] inline-flex items-center gap-0.5">
                {t('order.typeLottery')}
              </span>
            )}
            {(order.tags || []).slice(0, 3).map(tag => (
              <span key={tag} className="text-[9px] font-semibold text-[var(--mitako-ink)] bg-white border border-[var(--mitako-ink)] px-1.5 py-0.5 rounded-[8px]">
                {getOrderTagLabel(tag)}
              </span>
            ))}
          </div>
        </div>
      </div>
    </button>
  );
}

/** 电商风格订单选择浮层 — @ 引用或点击订单条打开 */
export default function OrderPickerOverlay({ open, orders, activeOrderId, memberLabel, onClose, onSelect }) {
  const [filter, setFilter] = useState('all');
  const sorted = useMemo(() => sortOrdersByPriority(orders), [orders]);
  const visible = useMemo(() => filterOrders(sorted, filter), [sorted, filter]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute inset-0 z-40 flex flex-col justify-end"
          role="dialog"
          aria-modal="true"
          aria-label={t('order.pickerTitle')}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
      <motion.button
        type="button"
        className="absolute inset-0 bg-[rgba(15,23,42,.28)]"
        onClick={onClose}
        aria-label={t('order.pickerClose')}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      />
      <motion.div
        className="relative bg-white rounded-t-[8px] shadow-[0_-18px_42px_rgba(127,164,49,.14)] max-h-[78%] flex flex-col border-t-2 border-x border-slate-200"
        initial={{ y: 46, opacity: 0, scale: 0.985 }}
        animate={{ y: 0, opacity: 1, scale: 1 }}
        exit={{ y: 28, opacity: 0, scale: 0.985 }}
        transition={{ type: 'spring', stiffness: 420, damping: 34, mass: 0.8 }}
      >
        <div className="px-4 pt-4 pb-2 flex items-center justify-between gap-2 border-b border-slate-200">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Package className="w-4 h-4 text-[var(--mitako-purple)] flex-shrink-0" />
              <h3 className="text-sm font-bold text-slate-800">{t('order.pickerTitle')}</h3>
            </div>
            {memberLabel && (
              <p className="text-[10px] text-slate-500 mt-0.5">{t('order.pickerMemberHint', 'zh-CN', { level: memberLabel })}</p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label={t('order.pickerClose')} className="touch-target w-9 h-9 rounded-[8px] bg-white border border-slate-200 flex items-center justify-center text-[var(--mitako-ink)] hover:bg-[var(--mitako-lime)]">
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        <div className="px-3 py-2 flex gap-1.5 overflow-x-auto console-scroll flex-shrink-0">
          {FILTERS.map(f => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              className={`flex-shrink-0 text-[11px] font-bold px-3 py-1.5 rounded-[8px] border transition-colors ${
                filter === f.id
                  ? 'bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-[var(--mitako-ink)] shadow-[0_10px_24px_rgba(127,164,49,.14)]'
                  : 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)] hover:bg-[var(--mitako-lime)]'
              }`}
            >
              {t(f.labelKey)}
            </button>
          ))}
        </div>

        <div className="relative flex-1 min-h-0">
          <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-5 bg-gradient-to-b from-white via-white/90 to-transparent backdrop-blur-[1px]" aria-hidden="true" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-7 bg-gradient-to-t from-white via-white/90 to-transparent backdrop-blur-[1px]" aria-hidden="true" />
          <div className="h-full overflow-y-auto overscroll-contain px-3 pb-5 pt-2 space-y-2 console-scroll [scrollbar-gutter:stable]">
            {visible.length === 0 ? (
              <p className="text-center text-xs text-slate-400 py-8">{t('order.pickerEmpty')}</p>
            ) : visible.map(order => (
              <OrderCard
                key={order.order_id}
                order={order}
                selected={order.order_id === activeOrderId}
                onSelect={(o) => { onSelect(o); onClose(); }}
              />
            ))}
          </div>
        </div>

        <div className="px-4 py-2 border-t border-slate-200 bg-white flex items-center gap-2 text-[10px] text-slate-500 flex-shrink-0">
          <AlertCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
          <span>{t('order.pickerFootnote')}</span>
        </div>
      </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function OrderQuickBar({ order, memberLabel, onOpenPicker }) {
  if (!order) return null;
  const isAttention = hasAttentionSignal(order);

  return (
    <button
      type="button"
      onClick={onOpenPicker}
      className="w-full px-3 py-2.5 bg-white border-b border-slate-200 flex items-center gap-2.5 min-w-0 text-left hover:bg-[var(--mitako-lime)] transition-colors"
    >
      <div className="w-10 h-10 rounded-[8px] bg-[var(--mitako-lime)] border border-slate-200 flex items-center justify-center flex-shrink-0">
        <Package className="w-5 h-5 text-[var(--mitako-ink)]" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          {memberLabel && (
            <span className="text-[9px] font-bold text-[var(--mitako-ink)] bg-white border border-[var(--mitako-ink)] px-1.5 py-0.5 rounded-[8px]">
              {memberLabel}
            </span>
          )}
          {isAttention && (
            <span className="text-[9px] font-bold text-[var(--mitako-ink)] bg-white border border-[var(--mitako-ink)] px-1.5 py-0.5 rounded-[8px] inline-flex items-center gap-0.5">
              <Clock className="w-3 h-3" />{t('order.abnormalLabel')}
            </span>
          )}
          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-[8px] border ${getOrderStatusClass(order.status)}`}>
            {order.status_label}
          </span>
        </div>
        <p className="mt-0.5 line-clamp-2 break-words text-xs font-semibold text-slate-700">{getOrderDisplayName(order)}</p>
        <p className="break-words font-mono text-[11px] text-slate-500">{formatPublicOrderRef(order.order_id)} · {t('order.tapToSwitch')}</p>
      </div>
      <CheckCircle2 className="w-4 h-4 text-slate-300 flex-shrink-0" aria-hidden="true" />
    </button>
  );
}
