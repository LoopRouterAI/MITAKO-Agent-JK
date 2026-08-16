/** 订单优先级打分 — 与运行态面板权重配置对齐 */

export const DEFAULT_ORDER_PRIORITY_WEIGHTS = {
  needs_attention: 100,
  delay_risk: 50,
  had_consultation: 30,
  pending_shipment: 20,
  refund_history: 25,
  lottery_win: 5,
  damage_claim: 75,
  minor_refund: 90,
  lottery_rule_question: 70,
  delay_days: 0.15,
};

export function scoreOrder(order, weights = DEFAULT_ORDER_PRIORITY_WEIGHTS) {
  if (!order) return 0;
  let score = 0;
  const tags = order.tags || [];
  if (tags.includes('needs_attention')) score += weights.needs_attention ?? 0;
  if (tags.includes('delay_risk')) score += weights.delay_risk ?? 0;
  if (tags.includes('had_consultation')) score += weights.had_consultation ?? 0;
  if (tags.includes('refund_history')) score += weights.refund_history ?? 0;
  if (tags.includes('lottery_win')) score += weights.lottery_win ?? 0;
  if (tags.includes('damage_claim')) score += weights.damage_claim ?? 0;
  if (tags.includes('minor_refund')) score += weights.minor_refund ?? 0;
  if (tags.includes('lottery_rule_question')) score += weights.lottery_rule_question ?? 0;
  if (order.status === 'pending_shipment') score += weights.pending_shipment ?? 0;
  score += (order.delay_days || 0) * (weights.delay_days ?? 0);
  return score;
}

export function sortOrdersByPriority(orders = [], weights = DEFAULT_ORDER_PRIORITY_WEIGHTS) {
  return [...orders].sort((a, b) => {
    const diff = scoreOrder(b, weights) - scoreOrder(a, weights);
    if (diff !== 0) return diff;
    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
  });
}

const STATUS_STYLE = {
  pending_shipment: 'bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-[var(--mitako-ink)]',
  in_transit: 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]',
  delivered: 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]',
  refunded: 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]',
  preorder: 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]',
  after_sales_review: 'bg-[var(--mitako-lime-soft)] text-[var(--mitako-ink)] border-[var(--mitako-ink)]',
};

const TAG_LABELS = {
  needs_attention: '需关注',
  delay_risk: '延误风险',
  had_consultation: '曾咨询',
  refund_history: '曾退款',
  lottery_win: '抽奖所得',
  lottery_rule_question: '抽奖复核',
  damage_claim: '售后中',
  minor_refund: '未成年退款',
  newly_shipped: '刚发货',
  preorder: '预售',
};

export function getOrderStatusClass(status) {
  return STATUS_STYLE[status] || 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]';
}

export function getOrderTagLabel(tag) {
  return TAG_LABELS[tag] || tag;
}

export function getOrderDisplayName(order) {
  if (!order) return '';
  return order.items?.[0]?.name || order.display_name || formatPublicOrderRef(order.order_id);
}

export function formatPublicOrderRef(value, prefix = '订单') {
  const raw = String(value || '').trim();
  if (!raw) return `${prefix} -`;
  const compact = raw.replace(/[^a-zA-Z0-9]/g, '');
  const code = (compact || raw).slice(-6).toUpperCase();
  return `${prefix} #${code}`;
}

export function extractOrderIdFromText(text) {
  const m = String(text || '').match(/ORD_\d{4}_\d+/);
  return m ? m[0] : null;
}

export function formatOrderDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  } catch {
    return '—';
  }
}

export function pickRecommendedOrder(orders = [], weights = DEFAULT_ORDER_PRIORITY_WEIGHTS) {
  const sorted = sortOrdersByPriority(orders, weights);
  return sorted[0] || null;
}
