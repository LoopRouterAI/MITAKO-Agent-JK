import React, { useMemo, useState } from 'react';
import { X, Package, Sparkles, AlertCircle, Clock, CheckCircle2 } from 'lucide-react';
import t from '../../i18n/index.js';
import {
  formatOrderDate,
  getOrderDisplayName,
  getOrderStatusClass,
  getOrderTagLabel,
  sortOrdersForDemo,
} from '../../utils/orderHelpers.js';

const FILTERS = [
  { id: 'all', labelKey: 'order.filterAll' },
  { id: 'attention', labelKey: 'order.filterAttention' },
  { id: 'shipping', labelKey: 'order.filterShipping' },
  { id: 'done', labelKey: 'order.filterDone' },
];

function filterOrders(orders, filterId) {
  if (filterId === 'attention') {
    return orders.filter(o => o.tags?.includes('needs_attention') || o.delay_days > 30 || o.status === 'pending_shipment');
  }
  if (filterId === 'shipping') {
    return orders.filter(o => ['in_transit', 'pending_shipment', 'preorder'].includes(o.status) || o.order_type === 'lottery');
  }
  if (filterId === 'done') {
    return orders.filter(o => ['delivered', 'refunded'].includes(o.status));
  }
  return orders;
}

function OrderCard({ order, selected, onSelect }) {
  const item = order.items?.[0];
  const gradient = order.thumb_gradient || 'from-[var(--mitako-purple)] to-indigo-500';
  return (
    <button
      type="button"
      onClick={() => onSelect(order)}
      className={`w-full text-left rounded-2xl border p-3 transition-all active:scale-[0.99] focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/40 ${
        selected
          ? 'border-[var(--mitako-purple)] bg-[#7B61FF]/5 shadow-[0_0_0_1px_rgba(123,97,255,0.25)]'
          : 'border-slate-200 bg-white hover:border-[var(--mitako-purple)]/30 hover:shadow-sm'
      }`}
    >
      <div className="flex gap-3">
        <div className={`w-14 h-14 rounded-xl bg-gradient-to-br ${gradient} flex items-center justify-center text-2xl flex-shrink-0 shadow-inner`}>
          {item?.thumb_emoji || '📦'}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-sm font-bold text-slate-800 line-clamp-2 leading-snug">{getOrderDisplayName(order)}</h4>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border flex-shrink-0 ${getOrderStatusClass(order.status)}`}>
              {order.status_label || order.status}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">#{order.order_id}</p>
          <div className="flex flex-wrap items-center gap-1.5 mt-2">
            <span className="text-xs font-bold text-[var(--mitako-orange)] tabular-nums">
              {order.total_amount > 0 ? `¥${order.total_amount}` : t('order.lotteryFree')}
            </span>
            <span className="text-[10px] text-slate-400">{formatOrderDate(order.created_at)}</span>
            {order.order_type === 'lottery' && (
              <span className="text-[9px] font-bold text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded-md inline-flex items-center gap-0.5">
                <Sparkles className="w-3 h-3" />{t('order.typeLottery')}
              </span>
            )}
            {(order.tags || []).slice(0, 3).map(tag => (
              <span key={tag} className="text-[9px] font-semibold text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded-md">
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
  const sorted = useMemo(() => sortOrdersForDemo(orders), [orders]);
  const visible = useMemo(() => filterOrders(sorted, filter), [sorted, filter]);

  if (!open) return null;

  return (
    <div className="absolute inset-0 z-40 flex flex-col justify-end" role="dialog" aria-modal="true" aria-label={t('order.pickerTitle')}>
      <button type="button" className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]" onClick={onClose} aria-label={t('order.pickerClose')} />
      <div className="relative bg-white rounded-t-3xl shadow-[0_-12px_40px_rgba(15,23,42,0.15)] max-h-[78%] flex flex-col animate-fade-up border-t border-slate-100">
        <div className="px-4 pt-4 pb-2 flex items-center justify-between gap-2 border-b border-slate-100">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Package className="w-4 h-4 text-[var(--mitako-purple)] flex-shrink-0" />
              <h3 className="text-sm font-bold text-slate-800">{t('order.pickerTitle')}</h3>
            </div>
            {memberLabel && (
              <p className="text-[10px] text-slate-500 mt-0.5">{t('order.pickerMemberHint', 'zh-CN', { level: memberLabel })}</p>
            )}
          </div>
          <button type="button" onClick={onClose} className="touch-target w-9 h-9 rounded-xl bg-slate-100 flex items-center justify-center text-slate-500 hover:bg-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-3 py-2 flex gap-1.5 overflow-x-auto console-scroll flex-shrink-0">
          {FILTERS.map(f => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              className={`flex-shrink-0 text-[11px] font-bold px-3 py-1.5 rounded-full border transition-colors ${
                filter === f.id
                  ? 'bg-[var(--mitako-purple)] text-white border-[var(--mitako-purple)]'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300'
              }`}
            >
              {t(f.labelKey)}
            </button>
          ))}
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-3 pb-4 pt-1 space-y-2 console-scroll">
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

        <div className="px-4 py-2 border-t border-slate-100 bg-slate-50/80 flex items-center gap-2 text-[10px] text-slate-500 flex-shrink-0">
          <AlertCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
          <span>{t('order.pickerFootnote')}</span>
        </div>
      </div>
    </div>
  );
}

export function OrderQuickBar({ order, memberLabel, onOpenPicker }) {
  if (!order) return null;
  const isAttention = order.tags?.includes('needs_attention') || order.delay_days > 30;

  return (
    <button
      type="button"
      onClick={onOpenPicker}
      className="w-full px-3 py-2.5 bg-gradient-to-r from-[var(--mitako-orange)]/5 to-white border-b border-slate-100 flex items-center gap-2.5 min-w-0 text-left hover:from-[var(--mitako-orange)]/10 transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--mitako-orange)]/30"
    >
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${order.thumb_gradient || 'from-orange-400 to-rose-400'} flex items-center justify-center text-lg flex-shrink-0`}>
        {order.items?.[0]?.thumb_emoji || '📦'}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          {memberLabel && (
            <span className="text-[9px] font-bold text-[var(--mitako-purple)] bg-[#7B61FF]/10 border border-[#7B61FF]/20 px-1.5 py-0.5 rounded-md">
              {memberLabel}
            </span>
          )}
          {isAttention && (
            <span className="text-[9px] font-bold text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded-md inline-flex items-center gap-0.5">
              <Clock className="w-3 h-3" />{t('order.abnormalLabel')}
            </span>
          )}
          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-md border ${getOrderStatusClass(order.status)}`}>
            {order.status_label}
          </span>
        </div>
        <p className="text-xs font-semibold text-slate-700 truncate mt-0.5">{getOrderDisplayName(order)}</p>
        <p className="text-[10px] text-slate-400 font-mono truncate">#{order.order_id} · {t('order.tapToSwitch')}</p>
      </div>
      <CheckCircle2 className="w-4 h-4 text-slate-300 flex-shrink-0" aria-hidden="true" />
    </button>
  );
}
