import React, { useCallback, useEffect, useState } from 'react';
import { Check, X } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

/** 008 补偿审批队列 */
export default function Approvals() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ session_id: '', user_id: '', amount: 50, reason: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authFetch('/api/v1/admin/approvals?status=pending');
      const data = await r.json();
      if (data.ok) setRows(data.approvals || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const decide = async (id, decision) => {
    try {
      await authFetch(`/api/v1/admin/approvals/${id}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      });
      load();
    } catch (e) {
      console.error(e);
    }
  };

  const create = async (e) => {
    e.preventDefault();
    try {
      const r = await authFetch('/api/v1/admin/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const data = await r.json();
      if (data.ok) {
        setForm({ session_id: '', user_id: '', amount: 50, reason: '' });
        load();
      }
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <h1 className="text-xl font-bold">{t('admin.navApprovals')}</h1>
      <form onSubmit={create} className="rounded-2xl border border-slate-200 bg-white p-4 grid gap-3 md:grid-cols-2">
        <input className="rounded-xl border px-3 py-2 text-sm" placeholder={t('admin.approvalSession')} value={form.session_id} onChange={e => setForm(f => ({ ...f, session_id: e.target.value }))} />
        <input className="rounded-xl border px-3 py-2 text-sm" placeholder={t('admin.approvalUser')} value={form.user_id} onChange={e => setForm(f => ({ ...f, user_id: e.target.value }))} />
        <input type="number" className="rounded-xl border px-3 py-2 text-sm" placeholder={t('admin.approvalAmount')} value={form.amount} onChange={e => setForm(f => ({ ...f, amount: Number(e.target.value) }))} />
        <input className="rounded-xl border px-3 py-2 text-sm md:col-span-2" placeholder={t('admin.approvalReason')} value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))} />
        <button type="submit" className="md:col-span-2 rounded-xl bg-[var(--mitako-purple)] text-white py-2.5 font-bold text-sm">{t('admin.approvalSubmit')}</button>
      </form>
      {loading ? <p className="text-sm text-slate-400">{t('admin.loading')}</p> : (
        <ul className="space-y-3">
          {rows.length === 0 && <li className="text-sm text-slate-500">{t('admin.approvalEmpty')}</li>}
          {rows.map(row => (
            <li key={row.id} className="rounded-2xl border border-slate-200 bg-white p-4 flex flex-wrap items-center gap-3 justify-between">
              <div>
                <p className="font-bold text-sm">¥{row.amount} · L{row.approval_level}</p>
                <p className="text-xs text-slate-500 mt-1">{row.reason || '—'} · {row.session_id || row.user_id}</p>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => decide(row.id, 'approved')} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-bold"><Check className="w-3.5 h-3.5" />{t('admin.approve')}</button>
                <button type="button" onClick={() => decide(row.id, 'rejected')} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-rose-600 text-white text-xs font-bold"><X className="w-3.5 h-3.5" />{t('admin.reject')}</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
