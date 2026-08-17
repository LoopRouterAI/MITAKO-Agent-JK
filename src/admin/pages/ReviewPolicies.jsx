import React, { useCallback, useEffect, useRef, useState } from 'react';
import { History, RotateCcw, Save, ShieldCheck, X } from 'lucide-react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

const inputClass = 'w-full rounded-[8px] border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-[var(--mitako-lime)] focus:ring-2 focus:ring-[var(--mitako-lime-soft)]';
const DEFAULTS = {
  review_intensity: 'strong', native_sampling_fps: 1, max_frames: 24, api_frame_limit: 24,
  probe_seconds: 12, opening_role_preflight: false, one_fps_frame_fallback: false,
  video_max_source_mb: 100, video_max_long_edge: 2560, video_max_fps: 24,
  video_max_bitrate_mbps: 6, video_min_short_edge: 1080, image_resize_trigger_edge: 3840,
  image_max_long_edge: 2560, image_lossy_quality: 90, preferred_video_codec: 'vp9_webm',
};
const INTENSITY_PRESETS = {
  standard: { max_frames: 12, api_frame_limit: 12, probe_seconds: 10 },
  strong: { max_frames: 24, api_frame_limit: 24, probe_seconds: 12 },
  forensic: { max_frames: 48, api_frame_limit: 24, probe_seconds: 20, opening_role_preflight: true },
};

function errorText(data) { return data?.detail || data?.error || t('admin.policySaveFailed'); }
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : t('admin.policyBuiltIn'); }

export default function ReviewPolicies() {
  const [policy, setPolicy] = useState(DEFAULTS);
  const [state, setState] = useState(null);
  const [versions, setVersions] = useState([]);
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [rollback, setRollback] = useState(null);
  const [rollbackReason, setRollbackReason] = useState('');
  const dialogRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const response = await authFetch('/api/v1/admin/review-policies');
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(errorText(data));
      setState(data.policy);
      setPolicy({ ...DEFAULTS, ...data.policy });
      setVersions(data.versions || []);
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.policyLoadFailed'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (rollback && dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal(); }, [rollback]);

  const setValue = (key, value) => setPolicy(current => ({ ...current, [key]: value }));
  const changeIntensity = value => setPolicy(current => ({ ...current, review_intensity: value, ...INTENSITY_PRESETS[value] }));
  const numberField = (key, label, min, max, step = 1) => (
    <label className="block">
      <span className="mb-1 block text-xs font-black text-slate-700">{label}</span>
      <input type="number" min={min} max={max} step={step} value={policy[key]} onChange={event => setValue(key, Number(event.target.value))} className={inputClass} />
    </label>
  );

  const publish = async () => {
    if (reason.trim().length < 6) { setMessage(t('admin.policyReasonRequired')); return; }
    setBusy(true);
    try {
      const response = await authFetch('/api/v1/admin/review-policies/versions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policy, reason, expected_active_version: state?.version || 0 }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(errorText(data));
      setMessage(t('admin.policyPublished'));
      setReason('');
      await load();
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.policySaveFailed'));
    } finally { setBusy(false); }
  };

  const closeRollback = () => { dialogRef.current?.close(); setRollback(null); setRollbackReason(''); };
  const confirmRollback = async () => {
    if (!rollback || rollbackReason.trim().length < 6) { setMessage(t('admin.policyReasonRequired')); return; }
    setBusy(true);
    try {
      const response = await authFetch('/api/v1/admin/review-policies/rollback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_version: rollback.version, reason: rollbackReason, expected_active_version: state?.version || 0 }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(errorText(data));
      closeRollback();
      setMessage(t('admin.policyRolledBack'));
      await load();
    } catch (error) {
      console.error(error);
      setMessage(error.message || t('admin.policySaveFailed'));
    } finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <header className="border-b border-slate-200 pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-black text-slate-950">{t('admin.policyTitle')}</h1>
            <p className="mt-1 text-sm text-slate-500">{t('admin.policySubtitle')}</p>
          </div>
          <span className="inline-flex min-h-[36px] items-center gap-1.5 rounded-[8px] border border-emerald-200 bg-emerald-50 px-3 text-xs font-bold text-emerald-800"><ShieldCheck className="h-4 w-4" />{t('admin.policySafeBoundary')}</span>
        </div>
      </header>
      {message && <div role="status" className="rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-700">{message}</div>}

      <section className="space-y-4" aria-labelledby="policy-review-title">
        <div><h2 id="policy-review-title" className="text-base font-black text-slate-950">{t('admin.policyReviewSection')}</h2><p className="mt-1 text-sm text-slate-500">{t('admin.policyReviewHint')}</p></div>
        <div className="grid gap-4 rounded-[8px] border border-slate-200 bg-white p-4 md:grid-cols-4">
          <label className="block md:col-span-2"><span className="mb-1 block text-xs font-black text-slate-700">{t('admin.policyIntensity')}</span><select value={policy.review_intensity} onChange={event => changeIntensity(event.target.value)} className={inputClass}><option value="standard">{t('admin.policyIntensityStandard')}</option><option value="strong">{t('admin.policyIntensityStrong')}</option><option value="forensic">{t('admin.policyIntensityForensic')}</option></select><span className="mt-1 block text-xs text-slate-500">{t('admin.policyIntensityHint')}</span></label>
          {numberField('native_sampling_fps', t('admin.policySamplingFps'), 0.5, 2, 0.5)}
          {numberField('max_frames', t('admin.policyMaxFrames'), 1, 1800)}
          {numberField('api_frame_limit', t('admin.policyApiFrameLimit'), 1, 24)}
          {numberField('probe_seconds', t('admin.policyProbeSeconds'), 5, 60)}
          <label className="flex min-h-[44px] items-center gap-2 rounded-[8px] border border-slate-200 px-3 text-sm font-bold"><input type="checkbox" checked={policy.opening_role_preflight} onChange={event => setValue('opening_role_preflight', event.target.checked)} className="h-5 w-5 accent-[var(--mitako-lime-deep)]" />{t('admin.policyOpeningPreflight')}</label>
          <label className="flex min-h-[44px] items-center gap-2 rounded-[8px] border border-slate-200 px-3 text-sm font-bold"><input type="checkbox" checked={policy.one_fps_frame_fallback} onChange={event => setValue('one_fps_frame_fallback', event.target.checked)} className="h-5 w-5 accent-[var(--mitako-lime-deep)]" />{t('admin.policyFrameFallback')}</label>
        </div>
      </section>

      <section className="space-y-4" aria-labelledby="policy-media-title">
        <div><h2 id="policy-media-title" className="text-base font-black text-slate-950">{t('admin.policyMediaSection')}</h2><p className="mt-1 text-sm text-slate-500">{t('admin.policyMediaHint')}</p></div>
        <div className="grid gap-4 rounded-[8px] border border-slate-200 bg-white p-4 md:grid-cols-4">
          {numberField('video_max_source_mb', t('admin.policyVideoSize'), 50, 500)}
          {numberField('video_max_long_edge', t('admin.policyVideoLongEdge'), 1080, 2560)}
          {numberField('video_max_fps', t('admin.policyVideoFps'), 12, 60)}
          {numberField('video_max_bitrate_mbps', t('admin.policyVideoBitrate'), 1, 20, 0.5)}
          {numberField('video_min_short_edge', t('admin.policyVideoShortEdge'), 720, 1080)}
          {numberField('image_resize_trigger_edge', t('admin.policyImageTrigger'), 2560, 8000)}
          {numberField('image_max_long_edge', t('admin.policyImageLongEdge'), 1080, 2560)}
          {numberField('image_lossy_quality', t('admin.policyImageQuality'), 80, 100)}
          <label className="block md:col-span-2"><span className="mb-1 block text-xs font-black text-slate-700">{t('admin.policyCodec')}</span><select value={policy.preferred_video_codec} onChange={event => setValue('preferred_video_codec', event.target.value)} className={inputClass}><option value="vp9_webm">VP9 WebM</option><option value="hevc_mp4">HEVC MP4</option></select></label>
        </div>
      </section>

      <section className="border-t border-slate-200 pt-5"><label className="block"><span className="mb-2 block text-xs font-black text-slate-700">{t('admin.policyReason')}</span><textarea value={reason} onChange={event => setReason(event.target.value)} minLength={6} maxLength={500} rows={3} className={`${inputClass} resize-y`} placeholder={t('admin.policyReasonPlaceholder')} /></label><button type="button" onClick={publish} disabled={busy || !state} className="mt-3 inline-flex min-h-[44px] items-center gap-2 rounded-[8px] bg-[var(--mitako-lime)] px-4 text-sm font-black text-slate-950 disabled:opacity-50"><Save className="h-4 w-4" />{busy ? t('admin.policySaving') : t('admin.policyPublish')}</button></section>

      <section className="border-t border-slate-200 pt-5"><h2 className="flex items-center gap-2 text-base font-black text-slate-950"><History className="h-4 w-4" />{t('admin.policyHistory')}</h2><div className="mt-3 divide-y divide-slate-200 border-y border-slate-200">{versions.length ? versions.map(version => <div key={version.id} className="flex flex-wrap items-start justify-between gap-3 py-4"><div><p className="text-sm font-black text-slate-950">v{version.version} · {version.review_intensity}</p><p className="mt-1 text-sm text-slate-600">{version.reason}</p><p className="mt-1 text-xs text-slate-500">{version.actor} · {formatTime(version.created_at)}</p></div>{version.version !== state?.version && <button type="button" onClick={() => setRollback(version)} className="inline-flex min-h-[44px] items-center gap-2 rounded-[8px] border border-slate-200 px-3 text-sm font-bold text-slate-700"><RotateCcw className="h-4 w-4" />{t('admin.policyRollback')}</button>}</div>) : <p className="py-4 text-sm text-slate-500">{t('admin.policyHistoryEmpty')}</p>}</div></section>

      {rollback && <dialog ref={dialogRef} onCancel={event => { event.preventDefault(); closeRollback(); }} className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-[8px] bg-white p-0 shadow-2xl backdrop:bg-slate-950/40"><div className="p-5"><div className="flex items-center justify-between gap-3"><h2 className="text-base font-black text-slate-950">{t('admin.policyRollbackTitle', 'zh-CN', { version: rollback.version })}</h2><button type="button" aria-label={t('admin.policyCancel')} onClick={closeRollback} className="min-h-[44px] min-w-[44px] rounded-[8px] p-2 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" /></button></div><label className="mt-4 block"><span className="mb-2 block text-xs font-black text-slate-700">{t('admin.policyRollbackReason')}</span><textarea value={rollbackReason} onChange={event => setRollbackReason(event.target.value)} minLength={6} maxLength={500} rows={4} className={`${inputClass} resize-y`} /></label><div className="mt-4 flex justify-end gap-2"><button type="button" onClick={closeRollback} className="min-h-[44px] rounded-[8px] border border-slate-200 px-3 text-sm font-bold">{t('admin.policyCancel')}</button><button type="button" onClick={confirmRollback} disabled={busy} className="inline-flex min-h-[44px] items-center gap-2 rounded-[8px] bg-slate-950 px-3 text-sm font-bold text-white"><RotateCcw className="h-4 w-4" />{t('admin.policyConfirmRollback')}</button></div></div></dialog>}
    </div>
  );
}
