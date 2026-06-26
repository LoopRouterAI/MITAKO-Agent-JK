import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';

/**
 * 冒险/菜单浮层 — 优先 Portal 到手机框容器内（absolute），避免浮在整页外
 */
export default function CompanionOverlayPortal({
  open,
  onClose,
  variant = 'center',
  containerId = 'companion-phone-root',
  children,
}) {
  useEffect(() => {
    if (!open) return undefined;
    const root = document.getElementById(containerId);
    const prev = root ? root.style.overflow : document.body.style.overflow;
    if (root) root.style.overflow = 'hidden';
    else document.body.style.overflow = 'hidden';
    return () => {
      if (root) root.style.overflow = prev || '';
      else document.body.style.overflow = prev;
    };
  }, [open, containerId]);

  if (!open || typeof document === 'undefined') return null;

  const host = document.getElementById(containerId) || document.body;
  const inPhone = host.id === containerId;

  const backdrop = (
    <div
      className={
        inPhone
          ? 'absolute inset-0 z-[100] flex bg-black/40 backdrop-blur-[2px] rounded-[inherit]'
          : 'fixed inset-0 z-[200] flex bg-black/45 backdrop-blur-[3px]'
      }
      style={inPhone ? undefined : { paddingBottom: 'env(safe-area-inset-bottom)' }}
      onClick={onClose}
      role="presentation"
    >
      <div
        className={
          variant === 'sheet'
            ? 'mt-auto w-full'
            : `m-auto w-full ${inPhone ? 'px-3' : 'max-w-md px-4'}`
        }
        onClick={e => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );

  return createPortal(backdrop, host);
}
