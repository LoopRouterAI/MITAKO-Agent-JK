import { useState, useEffect, useCallback, useMemo } from 'react';
import { sortOrdersForDemo, DEFAULT_ORDER_PRIORITY_WEIGHTS } from '../utils/orderHelpers.js';

/** 拉取用户订单与会员画像 */
export function useUserOrders(userId, orderPriorityWeights = DEFAULT_ORDER_PRIORITY_WEIGHTS) {
  const [orders, setOrders] = useState([]);
  const [userProfile, setUserProfile] = useState(null);
  const [activeOrderId, setActiveOrderId] = useState(null);
  const [loading, setLoading] = useState(true);

  const weightsKey = useMemo(() => JSON.stringify(orderPriorityWeights), [orderPriorityWeights]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const weightsQuery = encodeURIComponent(weightsKey);
    Promise.all([
      fetch(`/api/v1/orders/${userId}?sort=priority&weights=${weightsQuery}`).then(r => r.json()),
      fetch(`/api/v1/users/${userId}`).then(r => r.json()),
    ])
      .then(([orderRes, userRes]) => {
        if (cancelled) return;
        const list = sortOrdersForDemo(orderRes.orders || [], orderPriorityWeights);
        setOrders(list);
        setUserProfile(userRes.user || null);
        setActiveOrderId(prev => {
          if (prev && list.some(o => o.order_id === prev)) return prev;
          const flagged = list.find(o => o.tags?.includes('needs_attention'));
          return flagged?.order_id || list[0]?.order_id || null;
        });
      })
      .catch(() => {
        if (!cancelled) {
          setOrders([]);
          setUserProfile(null);
          setActiveOrderId(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [userId, weightsKey, orderPriorityWeights]);

  const activeOrder = orders.find(o => o.order_id === activeOrderId) || null;

  const selectOrder = useCallback((orderId) => {
    setActiveOrderId(orderId);
  }, []);

  return {
    orders,
    userProfile,
    activeOrder,
    activeOrderId,
    selectOrder,
    loading,
  };
}
