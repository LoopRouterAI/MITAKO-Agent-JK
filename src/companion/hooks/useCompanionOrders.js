import { useState, useEffect, useCallback, useMemo } from 'react';
import { companionFetch } from '../../lib/companionClient.js';
import { sortOrdersForDemo, DEFAULT_ORDER_PRIORITY_WEIGHTS } from '../../utils/orderHelpers.js';

/** Companion 演示订单 — @引用订单 */
export function useCompanionOrders(userId) {
  const [orders, setOrders] = useState([]);
  const [activeOrderId, setActiveOrderId] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    companionFetch(`/api/v2/companion/orders/${encodeURIComponent(userId)}`)
      .then(r => r.json())
      .then(data => {
        if (cancelled) return;
        const list = sortOrdersForDemo(data.orders || [], DEFAULT_ORDER_PRIORITY_WEIGHTS);
        setOrders(list);
        // 陪伴场景不默认选中订单 — 仅用户通过 @ 浮层主动引用
        setActiveOrderId(prev => (prev && list.some(o => o.order_id === prev) ? prev : null));
      })
      .catch(() => {
        if (!cancelled) {
          setOrders([]);
          setActiveOrderId(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [userId]);

  const activeOrder = useMemo(
    () => orders.find(o => o.order_id === activeOrderId) || null,
    [orders, activeOrderId],
  );

  const selectOrder = useCallback((orderId) => {
    setActiveOrderId(orderId);
  }, []);

  return { orders, activeOrder, activeOrderId, selectOrder, loading };
}
