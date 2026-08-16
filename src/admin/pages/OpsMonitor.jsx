import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Server, Radio, Cloud, Database } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';
import { sanitizePublicText } from '../../utils/publicText.js';

/** 010 7×24 运维监控大屏 */
export default function OpsMonitor() {
  const [snap, setSnap] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setError('');
      const r = await authFetch('/api/v1/ops/snapshot');
      const data = await r.json();
      if (data.ok) setSnap(data.snapshot);
      else setError(data.message || data.error || '运维监控数据加载失败');
    } catch (e) {
      console.error(e);
      setError('运维监控数据加载失败，请检查网络或重新登录后再试');
    }
  }, []);

  useEffect(() => {
    load();
    const tmr = setInterval(load, 5000);
    return () => clearInterval(tmr);
  }, [load]);

  if (!snap) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-slate-400">{t('admin.loading')}</p>
        {error && (
          <div className="rounded-[8px] border border-red-200 bg-red-50 px-3 py-2 text-sm font-bold text-red-700">
            {error}
            <button type="button" onClick={load} className="ml-3 rounded-[8px] border border-red-200 bg-white px-2 py-1 text-xs">重试</button>
          </div>
        )}
      </div>
    );
  }

  const pill = (ok) => (
    ok
      ? 'bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-[var(--mitako-ink)]'
      : 'bg-white text-[var(--mitako-ink)] border-[var(--mitako-ink)]'
  );

  const healthLabel = (status) => ({
    healthy: '正常',
    degraded: '需关注',
    down: '不可用',
  }[status] || sanitizePublicText(status || '未知'));

  const cards = [
    { icon: Activity, label: t('ops.status'), value: healthLabel(snap.status), tone: 'text-[var(--mitako-ink)]' },
    { icon: Server, label: t('ops.uptime'), value: `${Math.floor(snap.uptime_seconds / 86400)} 天 ${Math.floor((snap.uptime_seconds % 86400) / 3600)} 小时`, tone: 'text-[var(--mitako-ink)]' },
    { icon: Radio, label: '在线服务', value: snap.ws_connections, tone: 'text-[var(--mitako-ink)]' },
    { icon: Database, label: '待处理风险', value: snap.sla_alerts, tone: 'text-[var(--mitako-ink)]' },
    { icon: Activity, label: '视觉审核成功率', value: snap.model_calls?.success_rate == null ? '待接入' : `${Math.round(snap.model_calls.success_rate * 100)}%`, tone: 'text-[var(--mitako-ink)]' },
    { icon: Radio, label: '结构化返回率', value: snap.model_calls?.structured_success_rate == null ? '待接入' : `${Math.round(snap.model_calls.structured_success_rate * 100)}%`, tone: 'text-[var(--mitako-ink)]' },
    { icon: Server, label: '公开报告安全', value: snap.public_report_safety?.ok ? '正常' : '需关注', tone: 'text-[var(--mitako-ink)]' },
  ];
  const serviceLabel = (ok) => (ok ? '正常' : '待配置');
  const fmtDuration = (seconds = 0) => {
    const min = Math.floor((Number(seconds) || 0) / 60);
    if (min < 1) return '1 分钟内';
    if (min < 60) return `${min} 分钟`;
    return `${Math.floor(min / 60)} 小时 ${min % 60} 分钟`;
  };

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Cloud className="w-5 h-5 text-[var(--mitako-ink)]" />
            {t('admin.navOps')}
          </h1>
          <p className="mt-1 text-sm text-slate-500">参考 LLM 健康面板的核心思路，只展示 POC 最需要的可用性、延迟、等待和告警。</p>
        </div>
        <span className="text-xs text-slate-500">{t('ops.autoRefresh')}</span>
      </div>
      {error && <div className="rounded-[8px] border border-red-200 bg-red-50 px-3 py-2 text-sm font-bold text-red-700">{error}</div>}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map(({ icon: Icon, label, value, tone }) => (
          <div key={label} className="metric-card rounded-[8px] bg-white p-4">
            <Icon className={`w-5 h-5 mb-2 ${tone}`} />
            <p className={`text-2xl font-extrabold leading-tight ${tone}`}>{value}</p>
            <p className="text-xs font-semibold text-slate-600 mt-1">{label}</p>
          </div>
        ))}
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div className="tool-panel rounded-[8px] bg-white p-4 space-y-2">
          <h2 className="font-bold text-sm">{t('ops.queueTitle')}</h2>
          <p className="text-sm">{t('admin.kpiQueuing')}: <strong>{snap.handoff_queuing}</strong></p>
          <p className="text-sm">{t('admin.kpiConnected')}: <strong>{snap.handoff_connected}</strong></p>
          <p className="text-sm">{t('admin.kpiEscalated')}: <strong>{snap.handoff_escalated}</strong></p>
          <p className="text-sm">最长等待: <strong>{fmtDuration(snap.service_timeliness?.longest_wait_seconds)}</strong></p>
          <p className="text-xs text-slate-500">服务时效：{snap.service_timeliness?.status || '正常'} · 信息同步：{snap.message_sync?.status || '正常'}</p>
        </div>
        <div className="tool-panel rounded-[8px] bg-white p-4 space-y-3">
          <h2 className="font-bold text-sm">服务能力状态</h2>
          <div className={`inline-flex px-2 py-1 rounded-[8px] border text-xs font-bold ${pill(snap.cache_service?.ok)}`}>资料读取 · {serviceLabel(snap.cache_service?.ok)}</div>
          <div className={`inline-flex px-2 py-1 rounded-[8px] border text-xs font-bold ml-2 ${pill(snap.task_service?.ok)}`}>任务协同 · {serviceLabel(snap.task_service?.ok)}</div>
          <div className={`inline-flex px-2 py-1 rounded-[8px] border text-xs font-bold ml-2 ${pill(snap.message_sync?.ok)}`}>信息同步 · {snap.message_sync?.status || serviceLabel(snap.message_sync?.ok)}</div>
          {snap.message_sync_latency_ms != null && <p className="text-xs text-slate-500">信息同步延迟：{snap.message_sync_latency_ms} ms</p>}
          <p className="text-xs text-slate-500">服务访问：{snap.auth_required ? '稳定' : '待确认'}</p>
        </div>
        <div className="tool-panel rounded-[8px] bg-white p-4 space-y-2">
          <h2 className="font-bold text-sm">视觉审核健康</h2>
          <p className="text-sm">近次审核样本: <strong>{snap.visual_review?.total_reviews || 0}</strong></p>
          <p className="text-sm">平均耗时: <strong>{snap.model_calls?.avg_latency_seconds == null ? '待接入' : `${snap.model_calls.avg_latency_seconds}s`}</strong></p>
          <p className="text-sm">重试率: <strong>{snap.model_calls?.retry_rate == null ? '待接入' : `${Math.round(snap.model_calls.retry_rate * 100)}%`}</strong></p>
          <p className="text-xs text-slate-500">
            公开报告扫描 {snap.public_report_safety?.checked_files || 0} 份，风险 {snap.public_report_safety?.unsafe_files || 0} 份。
          </p>
          {(snap.public_report_safety?.risks || []).length > 0 && (
            <details className="rounded-[8px] border border-amber-300 bg-amber-50 p-2 text-xs">
              <summary className="cursor-pointer font-bold text-amber-900">查看风险明细与处理建议</summary>
              <ul className="mt-2 space-y-2">
                {snap.public_report_safety.risks.map((risk) => (
                  <li key={risk.file} className="rounded-[8px] border border-amber-200 bg-white p-2">
                    <p className="font-mono font-bold text-slate-800 break-all">{sanitizePublicText(risk.file)}</p>
                    <p className="mt-1 text-slate-600">{(risk.categories || []).map(sanitizePublicText).join('、')}</p>
                    <p className="mt-1 font-semibold text-amber-800">{sanitizePublicText(risk.action)}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}
