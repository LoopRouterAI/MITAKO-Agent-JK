import React from 'react';
import OrderPickerOverlay from '../components/chat/OrderPickerOverlay.jsx';

/** Companion 订单选择浮层 */
export default function CompanionOrderPicker({ open, onClose, orders, activeOrderId, onSelect }) {
  return (
    <OrderPickerOverlay
      open={open}
      onClose={onClose}
      orders={orders}
      activeOrderId={activeOrderId}
      onSelect={(order) => onSelect(order.order_id)}
      memberLabel=""
    />
  );
}
