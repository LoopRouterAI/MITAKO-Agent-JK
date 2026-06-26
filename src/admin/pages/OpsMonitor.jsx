import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Server, Radio, Cloud, Database } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

/** 010 7×24 运维监控大屏 */
export default function OpsMonitor() {
  const [snap, setSnap] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await authFetch('/api/v1/ops/snapshot');
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

  const pill = (ok) => (
    ok
      ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
      : 'bg-rose-100 text-rose-800 border-rose-200'
  );

  const cards = [
    { icon: Activity, label: t('ops.status'), value: snap.status, tone: snap.status === 'healthy' ? 'text-emerald-600' : 'text-amber-600' },
    { icon: Server, label: t('ops.uptime'), value: `${Math.floor(snap.uptime_seconds / 3600)}h ${Math.floor((snap.uptime_seconds % 3600) / 60)}m`, tone: 'text-slate-800' },
    { icon: Radio, label: t('ops.wsConnections'), value: snap.ws_connections, tone: 'text-purple-600' },
    { icon: Database, label: t('ops.slaAlerts'), value: snap.sla_alerts, tone: 'text-rose-600' },
  ];

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Cloud className="w-5 h-5 text-[var(--mitako-purple)]" />
          {t('admin.navOps')}
        </h1>
        <span className="text-xs text-slate-500">{t('ops.autoRefresh')}</span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map(({ icon: Icon, label, value, tone }) => (
          <div key={label} className="rounded-2xl border border-slate-200 bg-white p-4">
            <Icon className={`w-5 h-5 mb-2 ${tone}`} />
            <p className={`text-2xl font-extrabold ${tone}`}>{value}</p>
            <p className="text-xs font-semibold text-slate-600 mt-1">{label}</p>
          </div>
        ))}
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="rounded-2xl border bg-white p-4 space-y-2">
          <h2 className="font-bold text-sm">{t('ops.queueTitle')}</h2>
          <p className="text-sm">{t('admin.kpiQueuing')}: <strong>{snap.handoff_queuing}</strong></p>
          <p className="text-sm">{t('admin.kpiConnected')}: <strong>{snap.handoff_connected}</strong></p>
          <p className="text-sm">{t('admin.kpiEscalated')}: <strong>{snap.handoff_escalated}</strong></p>
          <p className="text-xs text-slate-500">SLA worker: {snap.sla_worker_mode} · IM: {snap.handoff_backend}</p>
        </div>
        <div className="rounded-2xl border bg-white p-4 space-y-3">
          <h2 className="font-bold text-sm">{t('ops.integrations')}</h2>
          <div className={`inline-flex px-2 py-1 rounded-lg border text-xs font-bold ${pill(snap.redis?.ok)}`}>Redis · {snap.redis?.mode}</div>
          <div className={`inline-flex px-2 py-1 rounded-lg border text-xs font-bold ml-2 ${pill(snap.celery?.ok)}`}>Celery · {snap.celery?.mode} ({snap.celery?.workers ?? 0})</div>
          <div className={`inline-flex px-2 py-1 rounded-lg border text-xs font-bold ml-2 ${pill(snap.chatwoot?.ok)}`}>Chatwoot · {snap.chatwoot?.mode}</div>
          <p className="text-xs text-slate-500">{t('ops.authFlag')}: {snap.auth_required ? 'ON' : 'OFF'}</p>
        </div>
      </div>
    </div>
  );
}
