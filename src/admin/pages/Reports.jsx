import React, { useCallback, useEffect, useState } from 'react';
import { BarChart3, Download } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch, getAuthToken } from '../../lib/authClient.js';
import { sanitizePublicText } from '../../utils/publicText.js';

const inputClass = 'rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:bg-[var(--mitako-lime-soft)]';
const cardClass = 'tool-panel rounded-[8px] bg-white p-4';

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
  const pct = (value = 0) => `${Math.round((Number(value) || 0) * 100)}%`;
  const fmtDuration = (seconds = 0) => {
    const min = Math.floor((Number(seconds) || 0) / 60);
    if (min < 1) return '1 分钟内';
    if (min < 60) return `${min} 分钟`;
    return `${Math.floor(min / 60)} 小时 ${min % 60} 分钟`;
  };
  const statusLabel = (status) => ({
    queuing: '排队中',
    connected: '已接入',
    escalated: '待升级处理',
    transferring: '转交中',
    closed: '已关闭',
  }[status] || sanitizePublicText(status));
  const eventLabel = (type) => ({
    accept: 'VIP客服接单',
    escalate: '升级处理',
    transfer: '同事转交',
    colleague: '同事转交',
    sla_timeout: '超时转交',
  }[type] || sanitizePublicText(type));
  const metricCards = [
    [summary.total_sessions, '服务单总量'],
    [summary.human_sessions, 'VIP客服介入量'],
    [pct(summary.handoff_rate), '转VIP客服率'],
    [pct(summary.close_rate), '结案率'],
    [summary.business_events, '业务动作记录'],
    [fmtDuration(summary.queue?.longest_wait_seconds), '当前最长等待'],
    [summary.pending_approvals, t('admin.reportPendingApproval')],
    [`${summary.period_days} 天`, t('admin.reportPeriod')],
  ];

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2"><BarChart3 className="w-5 h-5" />{t('admin.navReports')}</h1>
          <p className="mt-1 text-sm text-slate-500">给客服 Leader 看的北极星指标：处理量、VIP客服介入、结案、等待和业务动作。</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={days} onChange={e => setDays(Number(e.target.value))} className={inputClass}>
            <option value={7}>7 {t('admin.reportDays')}</option>
            <option value={14}>14 {t('admin.reportDays')}</option>
            <option value={30}>30 {t('admin.reportDays')}</option>
          </select>
          <button type="button" onClick={exportCsv} className="inline-flex items-center gap-1 rounded-[8px] bg-[var(--mitako-lime)] px-3 py-2 text-sm font-bold">
            <Download className="w-4 h-4" /> 导出报表
          </button>
        </div>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {metricCards.map(([value, label], index) => (
          <div key={label} className={`${cardClass} ${index === 0 ? 'bg-[var(--mitako-lime-soft)]' : ''}`}>
            <p className="text-2xl font-extrabold leading-tight">{value}</p>
            <p className="text-xs text-slate-500">{label}</p>
          </div>
        ))}
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div className={cardClass}>
          <h2 className="font-bold text-sm mb-2">队列压力</h2>
          <p className="text-sm text-slate-600">排队 {summary.queue?.queuing || 0} 人，转交中 {summary.queue?.transferring || 0} 人，平均等待 {fmtDuration(summary.queue?.avg_wait_seconds)}。</p>
        </div>
        <div className={cardClass}>
          <h2 className="font-bold text-sm mb-2">VIP客服效率</h2>
          <p className="text-sm text-slate-600">近 {summary.period_days} 天VIP客服介入 {summary.human_sessions || 0} 单，Agent 自动处理或未转VIP客服 {summary.agent_sessions || 0} 单。</p>
        </div>
        <div className={cardClass}>
          <h2 className="font-bold text-sm mb-2">审批状态</h2>
          <p className="text-sm text-slate-600">补偿申请 {summary.approval_requests || 0} 条，审批完成 {summary.approval_done || 0} 条，通过率 {pct(summary.approval_pass_rate)}。</p>
        </div>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <div className={cardClass}>
          <h2 className="font-bold text-sm mb-3">{t('admin.reportStatusBreakdown')}</h2>
          <ul className="space-y-2 text-sm">{statusEntries.map(([k, v]) => <li key={k} className="flex justify-between"><span>{statusLabel(k)}</span><span className="font-mono">{v}</span></li>)}</ul>
        </div>
        <div className={cardClass}>
          <h2 className="font-bold text-sm mb-3">{t('admin.reportEventBreakdown')}</h2>
          <ul className="space-y-2 text-sm">{eventEntries.map(([k, v]) => <li key={k} className="flex justify-between"><span>{eventLabel(k)}</span><span className="font-mono">{v}</span></li>)}</ul>
        </div>
      </div>
    </div>
  );
}
