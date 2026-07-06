import React, { useCallback, useEffect, useState } from 'react';
import { Check, X } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

const inputClass = 'w-full rounded-[8px] border border-slate-200 px-3 py-2 text-sm outline-none focus:bg-[var(--mitako-lime-soft)]';
const cardClass = 'tool-panel rounded-[8px] bg-white';
const shortCode = (value = '', prefix = '服务单') => {
  const text = String(value || '').trim();
  if (!text) return `${prefix} -`;
  const compact = text.replace(/[^a-zA-Z0-9]/g, '');
  return `${prefix} ${compact.slice(-6).toUpperCase() || '-'}`;
};

const CREATE_ROLES = new Set(['desk_agent']);
const DECIDE_ROLES = new Set(['super_admin', 'supervisor']);

export default function Approvals({ user = null }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ session_id: '', user_id: '', amount: 50, reason: '' });
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [decidingId, setDecidingId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authFetch('/api/v1/admin/approvals?status=pending');
      const data = await r.json();
      if (data.ok) setRows(data.approvals || []);
      else setError(data.message || data.error || data.detail || '审批列表加载失败');
    } catch (e) {
      console.error(e);
      setError('审批列表加载失败，请稍后再试');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const decide = async (id, decision) => {
    setError('');
    setNotice('');
    setDecidingId(id);
    try {
      const r = await authFetch(`/api/v1/admin/approvals/${id}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      });
      const data = await r.json();
      if (!data.ok) {
        setError(data.message || data.error || data.detail || '审批处理失败');
        return;
      }
      setNotice(decision === 'approved' ? '已批准该补偿申请' : '已拒绝该补偿申请');
      await load();
    } catch (e) {
      console.error(e);
      setError('审批处理失败，请检查网络后重试');
    } finally {
      setDecidingId(null);
    }
  };

  const create = async (e) => {
    e.preventDefault();
    setError('');
    setNotice('');
    setSubmitting(true);
    try {
      const r = await authFetch('/api/v1/admin/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const data = await r.json();
      if (data.ok) {
        setForm({ session_id: '', user_id: '', amount: 50, reason: '' });
        setNotice('补偿申请已提交，等待主管审批');
        await load();
      } else {
        setError(data.message || data.error || data.detail || '补偿申请提交失败');
      }
    } catch (err) {
      console.error(err);
      setError('补偿申请提交失败，请检查网络后重试');
    } finally {
      setSubmitting(false);
    }
  };

  const role = user?.role || '';
  const canCreate = CREATE_ROLES.has(role);
  const canDecide = DECIDE_ROLES.has(role);

  return (
    <div className="p-4 sm:p-6 space-y-6 max-w-5xl">
      <div>
        <h1 className="text-xl font-bold">{t('admin.navApprovals')}</h1>
        <p className="mt-1 text-sm text-slate-500">普通客服只发起申请；主管审批；额度和模板配置应由超级管理员在正式系统中维护。</p>
      </div>
      {notice && <div className="rounded-[8px] bg-[var(--mitako-lime-soft)] px-3 py-2 text-sm font-bold text-[var(--mitako-ink)]">{notice}</div>}
      {error && <div className="rounded-[8px] border border-red-200 bg-red-50 px-3 py-2 text-sm font-bold text-red-700">{error}</div>}
      {canCreate ? (
        <form onSubmit={create} className={`${cardClass} p-4 grid gap-3 md:grid-cols-2`}>
          <label className="text-xs font-bold text-slate-600">服务单号<input className={inputClass} placeholder={t('admin.approvalServiceRef')} value={form.session_id} onChange={e => setForm(f => ({ ...f, session_id: e.target.value }))} /></label>
          <label className="text-xs font-bold text-slate-600">客户编号<input className={inputClass} placeholder={t('admin.approvalCustomerRef')} value={form.user_id} onChange={e => setForm(f => ({ ...f, user_id: e.target.value }))} /></label>
          <label className="text-xs font-bold text-slate-600">申请金额<input type="number" className={inputClass} placeholder={t('admin.approvalAmount')} value={form.amount} onChange={e => setForm(f => ({ ...f, amount: Number(e.target.value) }))} /></label>
          <label className="text-xs font-bold text-slate-600">申请原因<input className={inputClass} placeholder={t('admin.approvalReason')} value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))} /></label>
          <button type="submit" disabled={submitting} className="md:col-span-2 rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] py-2.5 font-bold text-sm disabled:opacity-60">
            {submitting ? '提交中…' : t('admin.approvalSubmit')}
          </button>
        </form>
      ) : (
        <div className={`${cardClass} p-4 text-sm text-slate-600`}>当前账号仅可查看审批队列，补偿申请需由当前处理工单的一线客服发起。</div>
      )}
      {loading ? <p className="text-sm text-slate-400">{t('admin.loading')}</p> : (
        <ul className="space-y-3">
          {rows.length === 0 && <li className="text-sm text-slate-500">{t('admin.approvalEmpty')}</li>}
          {rows.map(row => (
            <li key={row.id} className={`${cardClass} p-4 flex flex-wrap items-center gap-3 justify-between`}>
              <div>
                <p className="font-bold text-sm">{t('admin.approvalSuggestedAmount', 'zh-CN', { amount: row.amount, level: row.approval_level })}</p>
                <p className="text-xs text-slate-500 mt-1">{row.reason || '未填写原因'} · {shortCode(row.session_id, '服务单')} · {shortCode(row.user_id, '客户')}</p>
              </div>
              {canDecide ? (
                <div className="flex gap-2">
                  <button type="button" disabled={decidingId === row.id} onClick={() => decide(row.id, 'approved')} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] text-xs font-bold disabled:opacity-60">
                    <Check className="w-3.5 h-3.5" />{t('admin.approve')}
                  </button>
                  <button type="button" disabled={decidingId === row.id} onClick={() => decide(row.id, 'rejected')} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-[8px] border border-slate-200 bg-white text-[var(--mitako-ink)] text-xs font-bold disabled:opacity-60">
                    <X className="w-3.5 h-3.5" />{t('admin.reject')}
                  </button>
                </div>
              ) : (
                <span className="rounded-[8px] bg-slate-100 px-3 py-1.5 text-xs font-bold text-slate-500">等待主管审批</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
