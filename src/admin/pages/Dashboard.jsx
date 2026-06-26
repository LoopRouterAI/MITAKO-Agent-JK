import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Clock, Users, AlertTriangle } from 'lucide-react';
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

  const cards = [
    { icon: Users, label: t('admin.kpiQueuing'), value: snap.queuing, tone: 'text-amber-600 bg-amber-50' },
    { icon: Activity, label: t('admin.kpiConnected'), value: snap.connected, tone: 'text-emerald-600 bg-emerald-50' },
    { icon: AlertTriangle, label: t('admin.kpiEscalated'), value: snap.escalated, tone: 'text-rose-600 bg-rose-50' },
    { icon: Clock, label: t('admin.kpiSlaAlerts'), value: (snap.sla_alerts || []).length, tone: 'text-purple-600 bg-purple-50' },
  ];

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-bold">{t('admin.navDashboard')}</h1>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map(({ icon: Icon, label, value, tone }) => (
          <div key={label} className={`rounded-2xl border border-slate-200 p-4 ${tone.split(' ').slice(1).join(' ')}`}>
            <Icon className={`w-5 h-5 mb-2 ${tone.split(' ')[0]}`} />
            <p className="text-2xl font-extrabold">{value}</p>
            <p className="text-xs font-semibold text-slate-600 mt-1">{label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
