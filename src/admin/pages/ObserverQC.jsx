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

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">{t('admin.navQc')}</h1>
      {items.length === 0 && <p className="text-sm text-slate-500">{t('admin.qcEmpty')}</p>}
      {items.map(it => (
        <div key={it.id} className="rounded-xl border border-rose-100 bg-rose-50/50 p-4">
          <p className="text-xs font-mono text-slate-500">{it.session_id}</p>
          <p className="text-sm mt-2">{it.content}</p>
          <p className="text-xs text-rose-600 mt-1">{it.policy_hits?.join(' · ')}</p>
        </div>
      ))}
    </div>
  );
}
