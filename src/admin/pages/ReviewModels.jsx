import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, History, Play, RotateCcw, Save, X } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

function messageOf(data, fallback) {
  return data?.detail || data?.error || t(fallback);
}

function formatTime(value) {
  if (!value) return t('admin.modelBuiltIn');
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export default function ReviewModels() {
  const [state, setState] = useState(null);
  const [versions, setVersions] = useState([]);
  const [defaultModel, setDefaultModel] = useState('');
  const [enabledModels, setEnabledModels] = useState([]);
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [smoke, setSmoke] = useState({});
  const [rollback, setRollback] = useState(null);
  const [rollbackReason, setRollbackReason] = useState('');
  const dialogRef = useRef(null);
  const modelLabel = key => state?.models?.find(model => model.key === key)?.label || t('admin.modelUnavailable');

  const load = useCallback(async () => {
    try {
      const response = await authFetch('/api/v1/admin/review-models');
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(messageOf(data, 'admin.modelLoadFailed'));
      setState(data.state);
      setVersions(data.versions || []);
      setDefaultModel(data.state.default_model);
      setEnabledModels(data.state.enabled_models || []);
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.modelLoadFailed'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (rollback && dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal();
  }, [rollback]);

  const toggleModel = key => {
    if (key === defaultModel && enabledModels.includes(key)) {
      setMessage(t('admin.modelDefaultCannotDisable'));
      return;
    }
    setEnabledModels(current => current.includes(key) ? current.filter(item => item !== key) : [...current, key]);
    setMessage('');
  };

  const publish = async () => {
    if (reason.trim().length < 10) {
      setMessage(t('admin.modelReasonRequired'));
      return;
    }
    setBusy(true);
    try {
      const response = await authFetch('/api/v1/admin/review-models/versions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          default_model: defaultModel,
          enabled_models: enabledModels,
          reason,
          expected_active_version: state?.version || 0,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(messageOf(data, 'admin.modelSaveFailed'));
      setReason('');
      setMessage(t('admin.modelSaved'));
      await load();
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.modelSaveFailed'));
    } finally {
      setBusy(false);
    }
  };

  const runSmoke = async key => {
    setSmoke(current => ({ ...current, [key]: { busy: true } }));
    try {
      const response = await authFetch(`/api/v1/admin/review-models/${encodeURIComponent(key)}/smoke`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(messageOf(data, 'admin.modelSmokeFailed'));
      setSmoke(current => ({ ...current, [key]: data }));
    } catch (error) {
      console.error(error);
      setSmoke(current => ({ ...current, [key]: { ok: false, error: error.message || t('admin.modelSmokeFailed') } }));
    }
  };

  const closeRollback = () => {
    dialogRef.current?.close();
    setRollback(null);
    setRollbackReason('');
  };

  const confirmRollback = async () => {
    if (!rollback || rollbackReason.trim().length < 10) {
      setMessage(t('admin.modelReasonRequired'));
      return;
    }
    setBusy(true);
    try {
      const response = await authFetch('/api/v1/admin/review-models/rollback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_version: rollback.version,
          reason: rollbackReason,
          expected_active_version: state?.version || 0,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(messageOf(data, 'admin.modelRollbackFailed'));
      closeRollback();
      setMessage(t('admin.modelRolledBack'));
      await load();
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.modelRollbackFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <header className="border-b border-slate-200 pb-4">
        <h1 className="text-xl font-black text-slate-950">{t('admin.modelGovernanceTitle')}</h1>
        <p className="mt-1 text-sm text-slate-500">{t('admin.modelGovernanceSubtitle')}</p>
        <p className="mt-2 text-xs text-slate-500">{t('admin.modelCatalogRoadmap')}</p>
      </header>

      {message && <div role="status" className="rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-700">{message}</div>}

      <section aria-labelledby="model-list-title">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="model-list-title" className="text-base font-black text-slate-950">{t('admin.modelAvailable')}</h2>
          <span className="text-xs text-slate-500">{t('admin.modelActiveVersion', 'zh-CN', { version: state?.version || 0 })}</span>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {(state?.models || []).map(model => {
            const result = smoke[model.key];
            return (
              <article key={model.key} className={`rounded-[8px] border bg-white p-4 ${defaultModel === model.key ? 'border-[var(--mitako-lime-deep)]' : 'border-slate-200'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-sm font-black text-slate-950">{model.label}</h3>
                    <p className="mt-1 text-sm leading-6 text-slate-600">{model.description}</p>
                  </div>
                  <label className="flex min-h-[44px] min-w-[44px] shrink-0 cursor-pointer items-center justify-center rounded-[8px] hover:bg-slate-50">
                    <span className="sr-only">{t('admin.modelEnabledLabel', 'zh-CN', { model: model.label })}</span>
                    <input
                      type="checkbox"
                      checked={enabledModels.includes(model.key)}
                      onChange={() => toggleModel(model.key)}
                      aria-label={t('admin.modelEnabledLabel', 'zh-CN', { model: model.label })}
                      className="h-5 w-5 accent-[var(--mitako-lime-deep)]"
                    />
                  </label>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                  <span>{t('admin.modelInputPrice', 'zh-CN', { price: model.input_price })}</span>
                  <span>{t('admin.modelOutputPrice', 'zh-CN', { price: model.output_price })}</span>
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <label className="inline-flex min-h-[44px] items-center gap-2 rounded-[8px] border border-slate-200 px-3 text-sm font-bold">
                    <input type="radio" name="default-review-model" checked={defaultModel === model.key} disabled={!enabledModels.includes(model.key)} onChange={() => setDefaultModel(model.key)} />
                    {t('admin.modelSetDefault')}
                  </label>
                  <button type="button" onClick={() => runSmoke(model.key)} disabled={result?.busy} className="inline-flex min-h-[44px] items-center gap-2 rounded-[8px] border border-slate-200 px-3 text-sm font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                    <Play className="h-4 w-4" /> {result?.busy ? t('admin.modelSmoking') : t('admin.modelSmoke')}
                  </button>
                </div>
                {result && !result.busy && (
                  <p className={`mt-3 text-xs font-bold ${result.ok ? 'text-emerald-700' : 'text-rose-700'}`}>
                    {result.ok
                      ? t('admin.modelSmokePassed', 'zh-CN', { latency: result.latency_seconds })
                      : result.error}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="model-publish-title" className="border-t border-slate-200 pt-5">
        <h2 id="model-publish-title" className="text-base font-black text-slate-950">{t('admin.modelPublishTitle')}</h2>
        <label className="mt-3 block">
          <span className="mb-2 block text-xs font-black text-slate-700">{t('admin.modelReason')}</span>
          <textarea value={reason} onChange={event => setReason(event.target.value)} minLength={10} maxLength={500} rows={3} className="w-full resize-y rounded-[8px] border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-[var(--mitako-lime-deep)]" placeholder={t('admin.modelReasonPlaceholder')} />
        </label>
        <button type="button" onClick={publish} disabled={busy || !state} className="mt-3 inline-flex min-h-[44px] items-center gap-2 rounded-[8px] bg-[var(--mitako-lime)] px-4 text-sm font-black text-slate-950 disabled:opacity-50">
          <Save className="h-4 w-4" /> {busy ? t('admin.modelSaving') : t('admin.modelPublish')}
        </button>
      </section>

      <section aria-labelledby="model-history-title" className="border-t border-slate-200 pt-5">
        <h2 id="model-history-title" className="flex items-center gap-2 text-base font-black text-slate-950"><History className="h-4 w-4" /> {t('admin.modelHistory')}</h2>
        {versions.length === 0 ? <p className="mt-3 text-sm text-slate-500">{t('admin.modelHistoryEmpty')}</p> : (
          <div className="mt-3 divide-y divide-slate-200 border-y border-slate-200">
            {versions.map(version => (
              <div key={version.id} className="flex flex-wrap items-start justify-between gap-3 py-4">
                <div>
                  <p className="text-sm font-black text-slate-950">v{version.version} · {modelLabel(version.default_model)}</p>
                  <p className="mt-1 text-sm text-slate-600">{version.reason}</p>
                  <p className="mt-1 text-xs text-slate-500">{version.actor} · {formatTime(version.created_at)}</p>
                </div>
                {version.version !== state?.version && (
                  <button type="button" onClick={() => setRollback(version)} className="inline-flex min-h-[44px] items-center gap-2 rounded-[8px] border border-slate-200 px-3 text-sm font-bold text-slate-700">
                    <RotateCcw className="h-4 w-4" /> {t('admin.modelRollback')}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {rollback && (
        <dialog ref={dialogRef} onCancel={event => { event.preventDefault(); closeRollback(); }} className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-[8px] bg-white p-0 shadow-2xl backdrop:bg-slate-950/40" aria-labelledby="model-rollback-title">
          <div className="p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 id="model-rollback-title" className="text-base font-black text-slate-950">{t('admin.modelRollbackTitle', 'zh-CN', { version: rollback.version })}</h2>
              <button type="button" onClick={closeRollback} aria-label={t('admin.modelCancel')} className="min-h-[44px] min-w-[44px] rounded-[8px] p-2 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" /></button>
            </div>
            <p className="mt-3 text-sm text-slate-600">{rollback.reason}</p>
            <label className="mt-4 block">
              <span className="mb-2 block text-xs font-black text-slate-700">{t('admin.modelRollbackReason')}</span>
              <textarea value={rollbackReason} onChange={event => setRollbackReason(event.target.value)} minLength={10} maxLength={500} rows={4} className="w-full resize-y rounded-[8px] border border-slate-200 px-3 py-2.5 text-sm" />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={closeRollback} className="min-h-[44px] rounded-[8px] border border-slate-200 px-3 text-sm font-bold">{t('admin.modelCancel')}</button>
              <button type="button" onClick={confirmRollback} disabled={busy} className="inline-flex min-h-[44px] items-center gap-2 rounded-[8px] bg-slate-950 px-3 text-sm font-bold text-white disabled:opacity-50"><CheckCircle2 className="h-4 w-4" /> {t('admin.modelConfirmRollback')}</button>
            </div>
          </div>
        </dialog>
      )}
    </div>
  );
}
