import React, { useCallback, useEffect, useRef, useState } from 'react';
import { History, RotateCcw, Save, ShieldCheck, X } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

const inputClass = 'w-full rounded-[8px] border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-[var(--mitako-lime)] focus:ring-2 focus:ring-[var(--mitako-lime-soft)]';

function readableError(data, fallbackKey) {
  return data?.detail || data?.error || t(fallbackKey);
}

function formatTime(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export default function BusinessRules() {
  const [rules, setRules] = useState([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [versions, setVersions] = useState([]);
  const [versionsKey, setVersionsKey] = useState('');
  const [mode, setMode] = useState('supplement');
  const [content, setContent] = useState('');
  const [reason, setReason] = useState('');
  const [rollback, setRollback] = useState(null);
  const [rollbackReason, setRollbackReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const versionsRequest = useRef(0);
  const dialogRef = useRef(null);
  const rollbackTrigger = useRef(null);

  const selected = rules.find(item => item.key === selectedKey) || null;
  const active = selected?.active_version;
  const dirty = mode !== (active?.mode || 'supplement') || content !== (active?.content || '') || Boolean(reason.trim());

  const loadRules = useCallback(async (preferredKey = '') => {
    try {
      const response = await authFetch('/api/v1/admin/business-rules');
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(readableError(data, 'admin.rulesLoadFailed'));
      const items = data.rules || [];
      setRules(items);
      setSelectedKey(current => preferredKey || current || items[0]?.key || '');
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.rulesLoadFailed'));
    }
  }, []);

  const loadVersions = useCallback(async key => {
    if (!key) return;
    const requestId = ++versionsRequest.current;
    try {
      const response = await authFetch(`/api/v1/admin/business-rules/${encodeURIComponent(key)}/versions`);
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(readableError(data, 'admin.rulesLoadFailed'));
      if (requestId !== versionsRequest.current) return;
      setVersionsKey(key);
      setVersions(data.versions || []);
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.rulesLoadFailed'));
    }
  }, []);

  useEffect(() => { loadRules(); }, [loadRules]);
  useEffect(() => { loadVersions(selectedKey); }, [loadVersions, selectedKey]);
  useEffect(() => {
    const active = selected?.active_version;
    setMode(active?.mode || 'supplement');
    setContent(active?.content || '');
    setReason('');
    setRollback(null);
    setRollbackReason('');
    setMessage('');
  }, [selectedKey]);

  useEffect(() => {
    const protectUnsaved = event => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', protectUnsaved);
    return () => window.removeEventListener('beforeunload', protectUnsaved);
  }, [dirty]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!rollback || !dialog || dialog.open) return;
    dialog.showModal();
    dialog.focus();
  }, [rollback]);

  const selectRule = key => {
    if (key === selectedKey) return;
    if (dirty && !window.confirm(t('admin.rulesUnsavedConfirm'))) return;
    versionsRequest.current += 1;
    setVersions([]);
    setVersionsKey('');
    setSelectedKey(key);
  };

  const closeRollback = () => {
    dialogRef.current?.close();
    setRollback(null);
    setRollbackReason('');
    requestAnimationFrame(() => rollbackTrigger.current?.focus());
  };

  const publish = async () => {
    if (content.trim().length < 10 || reason.trim().length < 10) {
      setMessage(t('admin.rulesValidation'));
      return;
    }
    if (mode === 'replace' && !window.confirm(t('admin.rulesReplaceConfirm'))) return;
    setBusy(true);
    try {
      const response = await authFetch(`/api/v1/admin/business-rules/${encodeURIComponent(selectedKey)}/versions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode,
          content,
          reason,
          expected_active_version: active?.version || 0,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(readableError(data, 'admin.rulesSaveFailed'));
      setMessage(t('admin.rulesPublished', 'zh-CN', { version: data.version.version }));
      setMode(data.version.mode);
      setContent(data.version.content);
      setReason('');
      await Promise.all([loadRules(selectedKey), loadVersions(selectedKey)]);
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.rulesSaveFailed'));
    } finally {
      setBusy(false);
    }
  };

  const confirmRollback = async () => {
    if (!rollback || rollback.prompt_key !== selectedKey || rollbackReason.trim().length < 10) {
      setMessage(t('admin.rulesReasonRequired'));
      return;
    }
    setBusy(true);
    try {
      const response = await authFetch(`/api/v1/admin/business-rules/${encodeURIComponent(rollback.prompt_key)}/rollback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_version: rollback.version,
          reason: rollbackReason,
          expected_active_version: active?.version || 0,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(readableError(data, 'admin.rulesRollbackFailed'));
      setMessage(t('admin.rulesRolledBack', 'zh-CN', { version: data.version.version }));
      setMode(data.version.mode);
      setContent(data.version.content);
      closeRollback();
      await Promise.all([loadRules(selectedKey), loadVersions(selectedKey)]);
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.rulesRollbackFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-6 space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-black text-slate-950">{t('admin.rulesTitle')}</h1>
          <p className="mt-1 text-sm text-slate-500">{t('admin.rulesSubtitle')}</p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-[8px] border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs font-bold text-emerald-800">
          <ShieldCheck className="h-4 w-4" /> {t('admin.rulesImmutable')}
        </span>
      </header>

      {message && <div role="status" className="rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-700">{message}</div>}

      <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
        <nav aria-label={t('admin.rulesCatalog')} className="border-r-0 lg:border-r border-slate-200 lg:pr-4">
          <p className="mb-2 text-xs font-black uppercase text-slate-500">{t('admin.rulesCatalog')}</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-2">
            {rules.map(item => (
              <button
                key={item.key}
                type="button"
                onClick={() => selectRule(item.key)}
                aria-current={selectedKey === item.key ? 'page' : undefined}
                className={`min-h-[64px] rounded-[8px] border px-3 py-2 text-left transition ${selectedKey === item.key ? 'border-[var(--mitako-lime)] bg-[var(--mitako-lime-soft)]' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
              >
                <span className="block text-sm font-black text-slate-900">{item.name}</span>
                <span className="mt-1 block text-xs text-slate-500">{item.category} · {item.active_version ? `v${item.active_version.version}` : t('admin.rulesBuiltIn')}</span>
              </button>
            ))}
          </div>
        </nav>

        {selected && (
          <div className="min-w-0 space-y-6">
            <section aria-labelledby="rules-editor-title" className="space-y-4">
              <div>
                <h2 id="rules-editor-title" className="text-base font-black text-slate-950">{selected.name}</h2>
                <p className="mt-1 text-sm text-slate-500">{selected.description}</p>
              </div>

              <div>
                <span className="mb-2 block text-xs font-black text-slate-700">{t('admin.rulesMode')}</span>
                <div className="inline-flex rounded-[8px] border border-slate-200 bg-slate-50 p-1" role="group" aria-label={t('admin.rulesMode')}>
                  {['supplement', 'replace'].map(value => (
                    <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)} className={`rounded-[6px] px-3 py-2 text-xs font-bold transition ${mode === value ? 'bg-white text-slate-950 shadow-sm' : 'text-slate-500'}`}>
                      {t(`admin.rulesMode${value === 'supplement' ? 'Supplement' : 'Replace'}`)}
                    </button>
                  ))}
                </div>
              </div>

              <label className="block">
                <span className="mb-2 block text-xs font-black text-slate-700">{t('admin.rulesContent')}</span>
                <textarea value={content} onChange={event => setContent(event.target.value)} rows={12} maxLength={6000} placeholder={selected.format_hint} className={`${inputClass} resize-y font-mono leading-6`} />
                <span className="mt-1 block text-right text-[11px] text-slate-400">{content.trim().length}/6000</span>
              </label>

              <label className="block">
                <span className="mb-2 block text-xs font-black text-slate-700">{t('admin.rulesReason')}</span>
                <textarea value={reason} onChange={event => setReason(event.target.value)} rows={3} maxLength={500} placeholder={t('admin.rulesReasonPlaceholder')} className={`${inputClass} resize-y`} />
                <span className="mt-1 block text-right text-[11px] text-slate-400">{reason.trim().length}/500</span>
              </label>

              <button type="button" disabled={busy || !selectedKey} onClick={publish} className="inline-flex min-h-[40px] items-center gap-2 rounded-[8px] bg-[var(--mitako-lime)] px-4 text-sm font-black text-slate-950 transition hover:brightness-95 disabled:opacity-50">
                <Save className="h-4 w-4" /> {busy ? t('admin.rulesSaving') : t('admin.rulesPublish')}
              </button>
            </section>

            <section aria-labelledby="rules-history-title" className="border-t border-slate-200 pt-5">
              <h2 id="rules-history-title" className="flex items-center gap-2 text-base font-black text-slate-950"><History className="h-4 w-4" /> {t('admin.rulesHistory')}</h2>
              {versionsKey !== selectedKey || versions.length === 0 ? (
                <p className="mt-3 text-sm text-slate-500">{t('admin.rulesHistoryEmpty')}</p>
              ) : (
                <div className="mt-3 space-y-3">
                  {versions.map(version => (
                    <article key={version.id} className="rounded-[8px] border border-slate-200 bg-white p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-black text-slate-900">v{version.version} · {t(`admin.rulesMode${version.mode === 'supplement' ? 'Supplement' : 'Replace'}`)}</p>
                          <p className="mt-1 text-xs text-slate-500">{version.actor} · {formatTime(version.created_at)}</p>
                        </div>
                        {version.is_active ? (
                          <span className="rounded-[8px] bg-emerald-50 px-2 py-1 text-xs font-bold text-emerald-700">{t('admin.rulesActive')}</span>
                        ) : (
                          <button type="button" disabled={busy} onClick={event => { rollbackTrigger.current = event.currentTarget; setRollback({ ...version, prompt_key: selectedKey }); setRollbackReason(''); }} className="inline-flex min-h-[44px] items-center gap-1.5 rounded-[8px] border border-slate-200 px-3 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                            <RotateCcw className="h-3.5 w-3.5" /> {t('admin.rulesRollback')}
                          </button>
                        )}
                      </div>
                      <p className="mt-3 text-sm text-slate-700"><span className="font-bold">{t('admin.rulesReasonLabel')}</span>{version.reason}</p>
                      <details className="mt-2 text-sm text-slate-700">
                        <summary className="cursor-pointer font-bold">{t('admin.rulesVersionContent')}</summary>
                        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-[8px] bg-slate-50 p-3 font-sans text-xs leading-5">{version.content}</pre>
                      </details>
                      {version.source_version && <p className="mt-1 text-xs text-slate-500">{t('admin.rulesSourceVersion', 'zh-CN', { version: version.source_version })}</p>}
                    </article>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </div>

      {rollback && (
        <dialog ref={dialogRef} tabIndex={-1} onCancel={event => { event.preventDefault(); closeRollback(); }} className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-[8px] bg-white p-0 shadow-2xl backdrop:bg-slate-950/40" aria-labelledby="rollback-title">
          <div className="p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 id="rollback-title" className="text-base font-black text-slate-950">{t('admin.rulesRollbackTitle', 'zh-CN', { version: rollback.version })}</h2>
              <button type="button" aria-label={t('admin.rulesCancel')} onClick={closeRollback} className="min-h-[44px] min-w-[44px] rounded-[8px] p-2 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" /></button>
            </div>
            <div className="mt-4 rounded-[8px] border border-slate-200 bg-slate-50 p-3">
              <p className="text-xs font-black text-slate-700">{t('admin.rulesVersionContent')}</p>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words font-sans text-xs leading-5 text-slate-700">{rollback.content}</pre>
            </div>
            <label className="mt-4 block">
              <span className="mb-2 block text-xs font-black text-slate-700">{t('admin.rulesRollbackReason')}</span>
              <textarea value={rollbackReason} onChange={event => setRollbackReason(event.target.value)} rows={4} maxLength={500} className={`${inputClass} resize-y`} />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={closeRollback} className="min-h-[44px] rounded-[8px] border border-slate-200 px-3 text-sm font-bold text-slate-700">{t('admin.rulesCancel')}</button>
              <button type="button" disabled={busy} onClick={confirmRollback} className="inline-flex min-h-[44px] items-center gap-2 rounded-[8px] bg-slate-950 px-3 text-sm font-bold text-white disabled:opacity-50"><RotateCcw className="h-4 w-4" /> {t('admin.rulesConfirmRollback')}</button>
            </div>
          </div>
        </dialog>
      )}
    </div>
  );
}
