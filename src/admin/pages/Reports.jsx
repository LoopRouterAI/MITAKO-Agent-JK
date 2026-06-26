import React, { useCallback, useEffect, useState } from 'react';
import { BarChart3, Download } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch, getAuthToken } from '../../lib/authClient.js';

/** 008 运营报表 */
export default function Reports() {
  const [summary, setSummary] = useState(null);
  const [days, setDays] = useState(7);

  const load = useCallback(async () => {
    try {
      const r = await authFetch(`/api/v1/admin/reports/summary?days=${days}`);
      const data = await r.json();
      if (data.ok) setSummary(data.summary);
    } catch (e) {
      console.error(e);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const exportCsv = () => {
    const token = getAuthToken();
    const url = `/api/v1/admin/reports/export.csv?days=${days}`;
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(r => r.text())
      .then(text => {
        const blob = new Blob([text], { type: 'text/csv;charset=utf-8' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `mitako_report_${days}d.csv`;
        a.click();
      })
      .catch(console.error);
  };

  if (!summary) return <p className="p-6 text-sm text-slate-400">{t('admin.loading')}</p>;

  const statusEntries = Object.entries(summary.status_breakdown || {});
  const eventEntries = Object.entries(summary.transfer_by_type || {});

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold flex items-center gap-2"><BarChart3 className="w-5 h-5" />{t('admin.navReports')}</h1>
        <div className="flex items-center gap-2">
          <select value={days} onChange={e => setDays(Number(e.target.value))} className="rounded-xl border px-3 py-2 text-sm">
            <option value={7}>7 {t('admin.reportDays')}</option>
            <option value={14}>14 {t('admin.reportDays')}</option>
            <option value={30}>30 {t('admin.reportDays')}</option>
          </select>
          <button type="button" onClick={exportCsv} className="inline-flex items-center gap-1 rounded-xl border px-3 py-2 text-sm font-semibold hover:bg-slate-50">
            <Download className="w-4 h-4" /> CSV
          </button>
        </div>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-2xl border p-4 bg-white"><p className="text-2xl font-extrabold">{summary.total_sessions}</p><p className="text-xs text-slate-500">{t('admin.reportSessions')}</p></div>
        <div className="rounded-2xl border p-4 bg-white"><p className="text-2xl font-extrabold">{summary.transfer_events}</p><p className="text-xs text-slate-500">{t('admin.reportTransfers')}</p></div>
        <div className="rounded-2xl border p-4 bg-white"><p className="text-2xl font-extrabold">{summary.pending_approvals}</p><p className="text-xs text-slate-500">{t('admin.reportPendingApproval')}</p></div>
        <div className="rounded-2xl border p-4 bg-white"><p className="text-2xl font-extrabold">{summary.period_days}d</p><p className="text-xs text-slate-500">{t('admin.reportPeriod')}</p></div>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="rounded-2xl border bg-white p-4">
          <h2 className="font-bold text-sm mb-3">{t('admin.reportStatusBreakdown')}</h2>
          <ul className="space-y-2 text-sm">{statusEntries.map(([k, v]) => <li key={k} className="flex justify-between"><span>{k}</span><span className="font-mono">{v}</span></li>)}</ul>
        </div>
        <div className="rounded-2xl border bg-white p-4">
          <h2 className="font-bold text-sm mb-3">{t('admin.reportEventBreakdown')}</h2>
          <ul className="space-y-2 text-sm">{eventEntries.map(([k, v]) => <li key={k} className="flex justify-between"><span>{k}</span><span className="font-mono">{v}</span></li>)}</ul>
        </div>
      </div>
    </div>
  );
}
