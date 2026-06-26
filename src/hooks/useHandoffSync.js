/**
 * 转人工同步 — WebSocket 优先，指数退避重连，轮询兜底
 */
export function attachHandoffTransport({
  sessionId,
  enabled,
  onStatus,
  onMessages,
  pollFn,
  pollIntervalMs = 1500,
  handoffToken = '',
}) {
  if (!enabled || !sessionId) return () => {};

  let ws = null;
  let pollTimer = null;
  let closed = false;
  let reconnectAttempt = 0;
  let reconnectTimer = null;

  const startPoll = () => {
    if (pollTimer || closed) return;
    pollFn();
    pollTimer = setInterval(pollFn, pollIntervalMs);
  };

  const connect = () => {
    if (closed) return;
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    const tokenQs = handoffToken ? `?token=${encodeURIComponent(handoffToken)}` : '';
    const url = `${proto}://${host}/api/v1/handoff/ws/${encodeURIComponent(sessionId)}${tokenQs}`;
    try {
      ws = new WebSocket(url);
      ws.onopen = () => {
        reconnectAttempt = 0;
        pollFn();
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === 'ping') {
            ws.send('pong');
            return;
          }
          if (data.type === 'pong') return;
          if (data.type === 'status') onStatus?.(data);
          if (data.type === 'message' && data.message) onMessages?.([data.message]);
        } catch {
          /* malformed */
        }
      };
      ws.onerror = () => startPoll();
      ws.onclose = () => {
        ws = null;
        startPoll();
        if (closed) return;
        const delay = Math.min(30000, 1000 * 2 ** reconnectAttempt);
        reconnectAttempt += 1;
        reconnectTimer = setTimeout(connect, delay);
      };
    } catch {
      startPoll();
    }
  };

  connect();
  if (!ws) startPoll();

  return () => {
    closed = true;
    if (pollTimer) clearInterval(pollTimer);
    if (reconnectTimer) clearTimeout(reconnectTimer);
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
  };
}
