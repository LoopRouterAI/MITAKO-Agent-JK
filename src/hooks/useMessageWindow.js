import { useState, useMemo, useCallback, useEffect, useRef } from 'react';

/** 滑动窗口：默认只渲染最近 N 条，上滑触顶加载更早消息 */
const DEFAULT_PAGE_SIZE = 18;

export function useMessageWindow(messages, scrollRef, pageSize = DEFAULT_PAGE_SIZE) {
  const [visibleCount, setVisibleCount] = useState(pageSize);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const prevLenRef = useRef(messages.length);

  // 重置对话时恢复窗口
  useEffect(() => {
    if (messages.length === 0 && prevLenRef.current > 0) {
      setVisibleCount(pageSize);
    }
    prevLenRef.current = messages.length;
  }, [messages.length, pageSize]);

  const hasOlder = messages.length > visibleCount;

  const visibleMessages = useMemo(() => {
    if (messages.length <= visibleCount) return messages;
    return messages.slice(-visibleCount);
  }, [messages, visibleCount]);

  const loadOlder = useCallback(() => {
    if (!hasOlder || loadingOlder) return;
    const el = scrollRef?.current;
    if (!el) return;

    setLoadingOlder(true);
    const prevHeight = el.scrollHeight;
    const prevTop = el.scrollTop;

    setVisibleCount(c => Math.min(messages.length, c + pageSize));

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const node = scrollRef?.current;
        if (node) {
          node.scrollTop = prevTop + (node.scrollHeight - prevHeight);
        }
        setLoadingOlder(false);
      });
    });
  }, [hasOlder, loadingOlder, messages.length, pageSize, scrollRef]);

  useEffect(() => {
    const el = scrollRef?.current;
    if (!el) return undefined;

    const onScroll = () => {
      if (el.scrollTop <= 72 && hasOlder && !loadingOlder) {
        loadOlder();
      }
    };

    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [hasOlder, loadOlder, loadingOlder, scrollRef]);

  return {
    visibleMessages,
    hasOlder,
    loadingOlder,
    hiddenCount: Math.max(0, messages.length - visibleCount),
    loadOlder,
  };
}
