import React, { useCallback, useEffect, useState } from 'react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

export default function ObserverQC() {
  const [items, setItems] = useState([]);

  const load = useCallback(async () => {
    const r = await authFetch('/api/v1/admin/qc/observer?flagged_only=1');
    const data = await r.json();
    if (data.ok) setItems(data.audits || []);
  }, []);

  useEffect(() => { load(); }, [load]);
  const businessNo = (sessionId) => {
    const suffix = String(sessionId || '').replace(/[^a-zA-Z0-9]/g, '').slice(-6).toUpperCase();
    return suffix ? `会话 ${suffix}` : '待复核会话';
  };

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <div>
        <h1 className="text-xl font-bold">{t('admin.navQc')}</h1>
        <p className="mt-1 text-sm text-slate-500">复盘 AI 旁听和人工服务中的高风险表述，沉淀 SOP 调整样本。</p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {[
          ['待复盘', items.filter(it => it.reviewer_status === 'pending').length],
          ['需跟进', items.filter(it => it.reviewer_status === 'needs_followup').length],
          ['已通过', items.filter(it => it.reviewer_status === 'passed').length],
        ].map(([label, value]) => (
          <div key={label} className="metric-card rounded-[8px] bg-white p-3">
            <p className="text-xl font-black">{value}</p>
            <p className="text-xs text-slate-500">{label}</p>
          </div>
        ))}
      </div>
      {items.length === 0 && <p className="rounded-[8px] bg-white p-6 text-center text-sm text-slate-500">{t('admin.qcEmpty')}；正式接入后这里会展示需复盘的服务话术、政策风险和 SOP 样本。</p>}
      {items.map(it => (
        <div key={it.id} className="tool-panel rounded-[8px] bg-white p-4">
          <p className="text-xs font-bold text-slate-500">{businessNo(it.session_id)}</p>
          <p className="text-sm mt-2">{it.content}</p>
          <p className="text-xs text-[var(--mitako-ink)] font-bold mt-1">风险词：{it.policy_hits?.join(' · ') || '未命中'}</p>
          <p className="text-xs text-slate-500 mt-1">状态：{it.reviewer_status === 'passed' ? '已通过' : it.reviewer_status === 'needs_followup' ? '需跟进' : '待复盘'}</p>
        </div>
      ))}
    </div>
  );
}
