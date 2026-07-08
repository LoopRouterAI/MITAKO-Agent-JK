import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Clock, Users, AlertTriangle, TimerReset } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

export default function Dashboard() {
  const [snap, setSnap] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await authFetch('/api/v1/admin/queue/snapshot');
      const data = await r.json();
      if (data.ok) setSnap(data.snapshot);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    load();
    const tmr = setInterval(load, 5000);
    return () => clearInterval(tmr);
  }, [load]);

  if (!snap) return <p className="p-6 text-sm text-slate-400">{t('admin.loading')}</p>;

  const fmtDuration = (seconds = 0) => {
    const sec = Math.max(0, Number(seconds) || 0);
    const min = Math.floor(sec / 60);
    if (min < 1) return '1 分钟内';
    if (min < 60) return `${min} 分钟`;
    return `${Math.floor(min / 60)} 小时 ${min % 60} 分钟`;
  };
  const cards = [
    { icon: Users, label: t('admin.kpiQueuing'), value: snap.queuing },
    { icon: Activity, label: t('admin.kpiConnected'), value: snap.connected },
    { icon: AlertTriangle, label: t('admin.kpiEscalated'), value: snap.escalated },
    { icon: Clock, label: t('admin.kpiSlaAlerts'), value: (snap.sla_alerts || []).length },
    { icon: TimerReset, label: '最长等待', value: fmtDuration(snap.longest_wait_seconds) },
    { icon: Clock, label: '平均等待', value: fmtDuration(snap.avg_wait_seconds) },
  ];

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold">{t('admin.navDashboard')}</h1>
        <p className="mt-1 text-sm text-slate-500">先看排队压力、VIP客服处理压力和时效风险，判断今天是否需要临时加人或调整审核策略。</p>
      </div>
      <div className="grid grid-cols-2 xl:grid-cols-6 gap-4">
        {cards.map(({ icon: Icon, label, value }, index) => (
          <div key={label} className={`metric-card rounded-[8px] p-4 ${index === 0 ? 'bg-[var(--mitako-lime-soft)]' : 'bg-white'}`}>
            <Icon className="w-5 h-5 mb-2 text-[var(--mitako-ink)]" />
            <p className="text-2xl font-extrabold leading-tight">{value}</p>
            <p className="text-xs font-semibold text-slate-600 mt-1">{label}</p>
          </div>
        ))}
      </div>
      <div className="tool-panel rounded-[8px] bg-white p-4">
        <h2 className="text-sm font-black text-slate-950">当前处理建议</h2>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <p className="rounded-[8px] bg-slate-50 p-3 text-sm text-slate-700">排队超过 10 分钟时，建议主管临时打开高级客服接单或降低非紧急工单优先级。</p>
          <p className="rounded-[8px] bg-slate-50 p-3 text-sm text-slate-700">商品有伤、开箱视频、未成年人资料审核应优先由视觉审核工作台生成证据，再由VIP客服抽检。</p>
          <p className="rounded-[8px] bg-slate-50 p-3 text-sm text-slate-700">SLA 提醒出现时，应先处理已接入但未首响的会话，避免用户重复投诉。</p>
        </div>
      </div>
    </div>
  );
}
