import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  ClipboardList,
  DatabaseZap,
  Link2,
  MessageCircleWarning,
  Network,
  Radar,
  RefreshCcw,
  ShieldCheck,
  Trash2,
  Workflow,
} from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

const ICONS = {
  network: Network,
  radar: Radar,
  book: BookOpenCheck,
  warning: MessageCircleWarning,
  shield: ShieldCheck,
  workflow: Workflow,
  chart: BarChart3,
  link: Link2,
  list: ClipboardList,
  alert: AlertTriangle,
};

const list = (key) => {
  const value = t(key);
  return Array.isArray(value) ? value : [];
};

const initialGroupForm = {
  group_id: 'wx_xt_bluelock_001',
  group_name: '蓝锁凪玲补货 01 群',
  user_id: 'external_demo_009',
  content: '蓝色监狱凪诚士郎吧唧还有补货吗？想蹲小程序提醒。',
};
const initialProductForm = {
  event_type: 'restock',
  item_id: 'SKU-BLUELOCK-NAGI-BADGE-75',
  ip_name: '蓝色监狱',
  character_name: '凪诚士郎',
  category: '吧唧',
  stock: '320',
  risk_flag: '',
};

function IconTile({ icon }) {
  const Icon = ICONS[icon] || ClipboardList;
  return (
    <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[8px] bg-[var(--mitako-lime-soft)] text-[var(--mitako-ink)]">
      <Icon className="h-5 w-5" aria-hidden="true" />
    </span>
  );
}

function SectionLabel({ eyebrow, title, desc }) {
  return (
    <div className="max-w-3xl">
      <p className="text-xs font-black uppercase tracking-[0.14em] text-[var(--mitako-olive)]">{eyebrow}</p>
      <h1 className="mt-2 text-2xl font-black tracking-tight text-slate-950 sm:text-3xl">{title}</h1>
      {desc && <p className="mt-2 text-sm leading-6 text-slate-600">{desc}</p>}
    </div>
  );
}

function Field({ label, value, onChange, placeholder = '', type = 'text' }) {
  return (
    <label className="grid gap-1.5 text-xs font-black text-slate-700">
      {label}
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="min-h-[40px] rounded-[8px] border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)]"
      />
    </label>
  );
}

function JsonResult({ data }) {
  if (!data) return null;
  return (
    <pre className="max-h-72 overflow-auto rounded-[8px] bg-slate-950 p-3 text-xs leading-5 text-lime-100 console-scroll">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function EmptyState({ text }) {
  return <p className="rounded-[8px] border border-dashed border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-500">{text}</p>;
}

function statusTone(value) {
  if (value === 'local_contract_ready') return 'border-lime-200 bg-[var(--mitako-lime-soft)] text-slate-950';
  if (value === 'contract_pending') return 'border-amber-200 bg-amber-50 text-amber-800';
  return 'border-slate-200 bg-slate-100 text-slate-600';
}

function statusText(value) {
  const key = `privateDomain.statusLabels.${value}`;
  const label = t(key);
  return label === key ? value : label;
}

function eventSummary(event) {
  if (!event) return '';
  const payload = event.payload || {};
  if (payload.content) return payload.content;
  if (payload.item_id) return `${payload.item_id} · ${payload.ip_name || ''} · ${payload.category || ''}`;
  return event.event_type || '';
}

export default function PrivateDomainAgent() {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [groupForm, setGroupForm] = useState(initialGroupForm);
  const [productForm, setProductForm] = useState(initialProductForm);
  const [lastResult, setLastResult] = useState(null);
  const [error, setError] = useState('');
  const valueCards = list('privateDomain.valueCards');
  const modules = list('privateDomain.mvpModules');
  const phases = list('privateDomain.phases');
  const integrationFields = list('privateDomain.integrationFields');
  const accessPlans = list('privateDomain.accessPlans');
  const boundaries = list('privateDomain.boundaries');
  const demoScript = dashboard?.demo_script || [];
  const contracts = dashboard?.integration_contracts || [];
  const labels = {
    groupId: t('privateDomain.forms.groupId'),
    groupIdPlaceholder: t('privateDomain.forms.groupIdPlaceholder'),
    groupName: t('privateDomain.forms.groupName'),
    groupNamePlaceholder: t('privateDomain.forms.groupNamePlaceholder'),
    userId: t('privateDomain.forms.userId'),
    userIdPlaceholder: t('privateDomain.forms.userIdPlaceholder'),
    message: t('privateDomain.forms.message'),
    messagePlaceholder: t('privateDomain.forms.messagePlaceholder'),
    eventType: t('privateDomain.forms.eventType'),
    eventTypePlaceholder: t('privateDomain.forms.eventTypePlaceholder'),
    itemId: t('privateDomain.forms.itemId'),
    itemIdPlaceholder: t('privateDomain.forms.itemIdPlaceholder'),
    ipName: t('privateDomain.forms.ipName'),
    ipPlaceholder: t('privateDomain.forms.ipPlaceholder'),
    characterName: t('privateDomain.forms.characterName'),
    characterPlaceholder: t('privateDomain.forms.characterPlaceholder'),
    category: t('privateDomain.forms.category'),
    categoryPlaceholder: t('privateDomain.forms.categoryPlaceholder'),
    stock: t('privateDomain.forms.stock'),
    riskFlag: t('privateDomain.forms.riskFlag'),
    riskFlagPlaceholder: t('privateDomain.forms.riskFlagPlaceholder'),
  };

  const loadDashboard = useCallback(async () => {
    try {
      const r = await authFetch('/api/v1/private-domain/dashboard');
      const data = await r.json();
      if (data.ok) setDashboard(data);
      else setError(data.error || data.detail || t('privateDomain.loadFailed'));
    } catch (e) {
      console.error(e);
      setError(t('privateDomain.loadFailed'));
    }
  }, []);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  const postJson = async (url, payload = {}) => {
    setLoading(true);
    setError('');
    try {
      const r = await authFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await r.json();
      setLastResult(data);
      if (!data.ok) setError(data.detail || data.error || t('privateDomain.submitFailed'));
      await loadDashboard();
    } catch (e) {
      console.error(e);
      setError(t('privateDomain.submitFailed'));
    } finally {
      setLoading(false);
    }
  };

  const submitGroupMessage = () => {
    postJson('/api/v1/private-domain/group-message', {
      ...groupForm,
      group_id: groupForm.group_id.trim(),
      group_name: groupForm.group_name.trim(),
      user_id: groupForm.user_id.trim(),
      content: groupForm.content.trim(),
    });
  };

  const submitProductEvent = () => {
    postJson('/api/v1/private-domain/product-event', {
      ...productForm,
      event_id: `PD-EVT-${Date.now()}`,
      stock: Number(productForm.stock || 0),
    });
  };

  const loadDemoData = () => postJson('/api/v1/private-domain/demo/load');
  const clearDemoData = () => postJson('/api/v1/private-domain/demo/clear');

  return (
    <div className="min-h-full bg-[#f7faf0] p-4 sm:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="overflow-hidden rounded-[8px] border border-slate-200 bg-white">
          <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[1.15fr_.85fr]">
            <SectionLabel
              eyebrow={t('privateDomain.eyebrow')}
              title={t('privateDomain.title')}
              desc={t('privateDomain.subtitle')}
            />
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
              {valueCards.map(item => (
                <div key={item.title} className="rounded-[8px] border border-slate-200 bg-slate-50 p-4">
                  <p className="text-[11px] font-black text-slate-500">{item.label}</p>
                  <p className="mt-1 text-sm font-black text-slate-950">{item.title}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-600">{item.body}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="border-t border-slate-200 bg-[var(--mitako-lime-soft)] px-5 py-3 text-xs font-bold text-slate-700 sm:px-7">
            {t('privateDomain.pocBoundary')}
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[.9fr_1.1fr]">
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-black text-slate-950">{t('privateDomain.liveTitle')}</h2>
                <p className="mt-1 text-xs font-bold text-slate-500">{t(dashboard?.demo_ready ? 'privateDomain.demoReady' : 'privateDomain.demoEmpty')}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={loading}
                  onClick={loadDemoData}
                  className="inline-flex min-h-[36px] items-center gap-1.5 rounded-[8px] bg-[var(--mitako-lime)] px-3 text-xs font-black text-slate-950 transition hover:-translate-y-0.5 disabled:opacity-60"
                >
                  <DatabaseZap className="h-4 w-4" aria-hidden="true" />
                  {t('privateDomain.loadDemo')}
                </button>
                <button
                  type="button"
                  disabled={loading}
                  onClick={clearDemoData}
                  className="inline-flex min-h-[36px] items-center gap-1.5 rounded-[8px] border border-rose-200 bg-rose-50 px-3 text-xs font-black text-rose-800 transition hover:-translate-y-0.5 disabled:opacity-60"
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  {t('privateDomain.clearDemo')}
                </button>
                <button
                  type="button"
                  onClick={loadDashboard}
                  className="inline-flex min-h-[36px] items-center gap-1.5 rounded-[8px] border border-slate-200 bg-white px-3 text-xs font-black text-slate-700 transition hover:bg-[var(--mitako-lime-soft)]"
                >
                  <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                  {t('privateDomain.refresh')}
                </button>
              </div>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-5">
              {[
                ['group_count', t('privateDomain.kpiGroups')],
                ['risky_group_count', t('privateDomain.kpiRiskGroups')],
                ['pending_task_count', t('privateDomain.kpiTasks')],
                ['review_task_count', t('privateDomain.kpiReviewTasks')],
                ['event_count', t('privateDomain.kpiEvents')],
              ].map(([key, label]) => (
                <div key={key} className="rounded-[8px] bg-slate-50 p-3">
                  <p className="text-xl font-black text-slate-950">{dashboard?.snapshot?.[key] ?? 0}</p>
                  <p className="mt-1 text-[11px] font-bold text-slate-500">{label}</p>
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-2">
              {Object.entries(dashboard?.interface_status || {}).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between gap-3 rounded-[8px] border border-slate-200 px-3 py-2 text-xs">
                  <span className="font-black text-slate-700">{key}</span>
                  <span className={`rounded-[8px] border px-2 py-1 font-black ${statusTone(value)}`}>{statusText(value)}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.lastResult')}</h2>
            {error && <p className="mt-3 rounded-[8px] bg-rose-50 p-3 text-xs font-bold text-rose-800">{error}</p>}
            <div className="mt-3">
              <JsonResult data={lastResult} />
              {!lastResult && <EmptyState text={t('privateDomain.noResult')} />}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[.75fr_1.25fr]">
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.demoScriptTitle')}</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">{t('privateDomain.demoScriptDesc')}</p>
            <div className="mt-4 grid gap-3">
              {demoScript.map(item => (
                <div key={item.step} className="rounded-[8px] border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-[8px] bg-slate-950 text-xs font-black text-white">{item.step}</span>
                    <p className="text-sm font-black text-slate-950">{item.title}</p>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{item.body}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <SectionLabel
                eyebrow={t('privateDomain.contractEyebrow')}
                title={t('privateDomain.contractTitle')}
                desc={t('privateDomain.contractDesc')}
              />
              <span className="inline-flex items-center gap-1.5 rounded-[8px] bg-[var(--mitako-lime-soft)] px-3 py-2 text-xs font-black text-slate-800">
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                {t('privateDomain.contractBadge')}
              </span>
            </div>
            <div className="mt-5 grid gap-3 lg:grid-cols-2">
              {contracts.map(contract => (
                <div key={contract.key} className="rounded-[8px] border border-slate-200 bg-slate-50 p-4 text-xs">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-black text-slate-950">{contract.name}</p>
                      <p className="mt-1 font-mono text-[11px] text-slate-500">{contract.method} · {contract.endpoint}</p>
                    </div>
                    <span className={`rounded-[8px] border px-2 py-1 font-black ${statusTone(contract.status)}`}>{statusText(contract.status)}</span>
                  </div>
                  <div className="mt-3 grid gap-2 text-slate-600">
                    <p><span className="font-black text-slate-800">{t('privateDomain.contractOwner')}</span>{contract.owner}</p>
                    <p><span className="font-black text-slate-800">{t('privateDomain.contractAuth')}</span>{contract.auth}</p>
                    <p className="leading-5"><span className="font-black text-slate-800">{t('privateDomain.contractFields')}</span>{(contract.fields || []).join(' / ')}</p>
                    <p className="leading-5 text-slate-500">{contract.note}</p>
                  </div>
                </div>
              ))}
              {!contracts.length && <EmptyState text={t('privateDomain.emptyContracts')} />}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.groupFormTitle')}</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">{t('privateDomain.groupFormDesc')}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Field label={labels.groupId} value={groupForm.group_id} onChange={v => setGroupForm(s => ({ ...s, group_id: v }))} placeholder={labels.groupIdPlaceholder} />
              <Field label={labels.groupName} value={groupForm.group_name} onChange={v => setGroupForm(s => ({ ...s, group_name: v }))} placeholder={labels.groupNamePlaceholder} />
              <Field label={labels.userId} value={groupForm.user_id} onChange={v => setGroupForm(s => ({ ...s, user_id: v }))} placeholder={labels.userIdPlaceholder} />
              <label className="grid gap-1.5 text-xs font-black text-slate-700 sm:col-span-2">
                {labels.message}
                <textarea
                  value={groupForm.content}
                  onChange={e => setGroupForm(s => ({ ...s, content: e.target.value }))}
                  placeholder={labels.messagePlaceholder}
                  className="min-h-[96px] rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)]"
                />
              </label>
            </div>
            <button type="button" disabled={loading} onClick={submitGroupMessage} className="mt-4 min-h-[40px] rounded-[8px] bg-[var(--mitako-lime)] px-4 text-sm font-black text-slate-950 disabled:opacity-60">
              {t('privateDomain.runGroupMessage')}
            </button>
          </div>

          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.productFormTitle')}</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">{t('privateDomain.productFormDesc')}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Field label={labels.eventType} value={productForm.event_type} onChange={v => setProductForm(s => ({ ...s, event_type: v }))} placeholder={labels.eventTypePlaceholder} />
              <Field label={labels.itemId} value={productForm.item_id} onChange={v => setProductForm(s => ({ ...s, item_id: v }))} placeholder={labels.itemIdPlaceholder} />
              <Field label={labels.ipName} value={productForm.ip_name} onChange={v => setProductForm(s => ({ ...s, ip_name: v }))} placeholder={labels.ipPlaceholder} />
              <Field label={labels.characterName} value={productForm.character_name} onChange={v => setProductForm(s => ({ ...s, character_name: v }))} placeholder={labels.characterPlaceholder} />
              <Field label={labels.category} value={productForm.category} onChange={v => setProductForm(s => ({ ...s, category: v }))} placeholder={labels.categoryPlaceholder} />
              <Field label={labels.stock} type="number" value={productForm.stock} onChange={v => setProductForm(s => ({ ...s, stock: v }))} />
              <Field label={labels.riskFlag} value={productForm.risk_flag} onChange={v => setProductForm(s => ({ ...s, risk_flag: v }))} placeholder={labels.riskFlagPlaceholder} />
            </div>
            <button type="button" disabled={loading} onClick={submitProductEvent} className="mt-4 min-h-[40px] rounded-[8px] bg-[var(--mitako-lime)] px-4 text-sm font-black text-slate-950 disabled:opacity-60">
              {t('privateDomain.runProductEvent')}
            </button>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-4">
          {modules.map(item => (
            <div key={item.title} className="rounded-[8px] border border-slate-200 bg-white p-4 transition hover:-translate-y-0.5 hover:shadow-[0_18px_36px_rgba(15,23,42,.08)]">
              <IconTile icon={item.icon} />
              <div className="mt-4 flex items-center justify-between gap-3">
                <h2 className="text-sm font-black text-slate-950">{item.title}</h2>
                <span className="rounded-[8px] bg-slate-100 px-2 py-1 text-[11px] font-black text-slate-600">{item.stage}</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-600">{item.body}</p>
            </div>
          ))}
        </section>

        <section className="grid gap-4 lg:grid-cols-[1fr_1fr]">
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <SectionLabel
              eyebrow={t('privateDomain.integrationEyebrow')}
              title={t('privateDomain.integrationTitle')}
              desc={t('privateDomain.integrationDesc')}
            />
            <div className="mt-5 grid gap-3">
              {integrationFields.map(item => (
                <div key={item.name} className="flex items-start gap-3 rounded-[8px] bg-slate-50 p-3">
                  <IconTile icon={item.icon} />
                  <div>
                    <p className="text-sm font-black text-slate-950">{item.name}</p>
                    <p className="mt-1 text-xs leading-5 text-slate-600">{item.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <SectionLabel
              eyebrow={t('privateDomain.accessEyebrow')}
              title={t('privateDomain.accessTitle')}
              desc={t('privateDomain.accessDesc')}
            />
            <div className="mt-5 grid gap-3">
              {accessPlans.map(item => (
                <div key={item.level} className="rounded-[8px] border border-slate-200 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-black text-slate-950">{item.level}</p>
                    <span className="rounded-[8px] bg-[var(--mitako-lime-soft)] px-2 py-1 text-[11px] font-black text-slate-700">{item.status}</span>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{item.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[.9fr_1.1fr]">
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.boundaryTitle')}</h2>
            <div className="mt-4 grid gap-2">
              {boundaries.map(item => (
                <div key={item} className="flex items-start gap-2 rounded-[8px] bg-rose-50 px-3 py-2 text-xs font-bold leading-5 text-rose-900">
                  <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.roadmapTitle')}</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {phases.map(item => (
                <div key={item.title} className="rounded-[8px] bg-slate-50 p-4">
                  <p className="text-[11px] font-black text-[var(--mitako-olive)]">{item.period}</p>
                  <p className="mt-2 text-sm font-black text-slate-950">{item.title}</p>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{item.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-3">
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.groupListTitle')}</h2>
            <div className="mt-3 grid gap-2">
              {(dashboard?.groups || []).map(group => (
                <div key={group.group_id} className="rounded-[8px] bg-slate-50 p-3 text-xs">
                  <p className="font-black text-slate-950">{group.group_name}</p>
                  <p className="mt-1 font-mono text-slate-500">{group.group_id}</p>
                  <p className="mt-2 font-bold text-slate-600">L{group.risk_level} · {group.status} · {t('privateDomain.healthScore')} {group.health_score}</p>
                </div>
              ))}
              {!(dashboard?.groups || []).length && <EmptyState text={t('privateDomain.emptyGroups')} />}
            </div>
          </div>
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.taskListTitle')}</h2>
            <div className="mt-3 grid gap-2">
              {(dashboard?.customer_service_tasks || []).map(task => (
                <div key={task.task_id} className="rounded-[8px] bg-slate-50 p-3 text-xs">
                  <p className="font-black text-slate-950">{task.task_id}</p>
                  <p className="mt-1 text-slate-600">L{task.risk_level} · {task.issue_type} · {task.priority}</p>
                  <p className="mt-2 leading-5 text-slate-500">{task.message_summary}</p>
                </div>
              ))}
              {!(dashboard?.customer_service_tasks || []).length && <EmptyState text={t('privateDomain.emptyTasks')} />}
            </div>
          </div>
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <h2 className="text-base font-black text-slate-950">{t('privateDomain.reviewTaskListTitle')}</h2>
            <div className="mt-3 grid gap-2">
              {(dashboard?.review_tasks || []).map(task => (
                <div key={task.task_id} className="rounded-[8px] bg-slate-50 p-3 text-xs">
                  <p className="font-black text-slate-950">{task.task_id}</p>
                  <p className="mt-1 text-slate-600">{task.scenario} · {task.status}</p>
                  <p className="mt-2 truncate font-mono text-slate-500">{task.file_name}</p>
                </div>
              ))}
              {!(dashboard?.review_tasks || []).length && <EmptyState text={t('privateDomain.emptyReviewTasks')} />}
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-base font-black text-slate-950">{t('privateDomain.candidateListTitle')}</h2>
              <span className="rounded-[8px] bg-slate-100 px-2 py-1 text-[11px] font-black text-slate-600">
                {(dashboard?.campaign_candidates || []).length}
              </span>
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">{t('privateDomain.candidateListDesc')}</p>
            <div className="mt-3 grid gap-2">
              {(dashboard?.campaign_candidates || []).map(candidate => (
                <div key={`${candidate.event_id}-${candidate.group_id}-${candidate.id}`} className="rounded-[8px] bg-slate-50 p-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-black text-slate-950">{candidate.group_id}</p>
                    <span className={`rounded-[8px] px-2 py-1 font-black ${candidate.decision === 'review' ? 'bg-[var(--mitako-lime-soft)] text-slate-950' : candidate.decision === 'blocked' ? 'bg-rose-50 text-rose-800' : 'bg-slate-200 text-slate-600'}`}>
                      {candidate.decision}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-slate-500">{candidate.event_id}</p>
                  <p className="mt-2 font-bold text-slate-600">{t('privateDomain.matchScore')} {candidate.match_score}</p>
                  <p className="mt-2 leading-5 text-slate-500">{candidate.reason}</p>
                </div>
              ))}
              {!(dashboard?.campaign_candidates || []).length && <EmptyState text={t('privateDomain.emptyCandidates')} />}
            </div>
          </div>

          <div className="rounded-[8px] border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-base font-black text-slate-950">{t('privateDomain.eventListTitle')}</h2>
              <span className="rounded-[8px] bg-slate-100 px-2 py-1 text-[11px] font-black text-slate-600">
                {(dashboard?.events || []).length}
              </span>
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">{t('privateDomain.eventListDesc')}</p>
            <div className="mt-3 grid gap-2">
              {(dashboard?.events || []).map(event => (
                <div key={event.id} className="rounded-[8px] bg-slate-50 p-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-black text-slate-950">{event.event_type}</p>
                    <span className="rounded-[8px] bg-white px-2 py-1 font-mono text-[11px] font-black text-slate-500">#{event.id}</span>
                  </div>
                  <p className="mt-1 font-mono text-slate-500">{event.group_id || t('privateDomain.noGroupId')}</p>
                  <p className="mt-2 leading-5 text-slate-600">{eventSummary(event)}</p>
                </div>
              ))}
              {!(dashboard?.events || []).length && <EmptyState text={t('privateDomain.emptyEvents')} />}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
