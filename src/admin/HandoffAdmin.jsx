import React, { useCallback, useEffect, useState } from 'react';
import { Settings, Save, RefreshCw, Shield, Clock, Route } from 'lucide-react';
import t from '../i18n/index.js';
import { authFetch } from '../lib/authClient.js';

/** 转人工路由管理 — /admin 路由子模块 */
export default function HandoffAdmin({ embedded = false }) {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/v1/handoff/routing');
      const data = await r.json();
      if (data.ok) setConfig(data.config);
    } catch (e) {
      console.error(e);
      setMessage(t('admin.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleRule = (id) => {
    setConfig(prev => ({
      ...prev,
      rules: (prev.rules || []).map(r => (r.id === id ? { ...r, enabled: !r.enabled } : r)),
    }));
  };

  const updateSla = (key, value) => {
    setConfig(prev => ({
      ...prev,
      sla: { ...(prev.sla || {}), [key]: value },
    }));
  };

  const save = async () => {
    if (!config) return;
    setSaving(true);
    setMessage('');
    try {
      const r = await authFetch('/api/v1/admin/handoff/routing', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const data = await r.json();
      if (data.ok) {
        setConfig(data.config);
        setMessage(t('admin.routingSaved'));
      } else {
        setMessage(data.error || t('admin.saveFailed'));
      }
    } catch (e) {
      console.error(e);
      setMessage(t('admin.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const inner = (
    <>
      {!embedded && (
      <header className="border-b border-slate-200 bg-white/90 backdrop-blur px-6 py-4 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[var(--mitako-purple)] text-white flex items-center justify-center">
            <Settings className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold">转人工路由管理</h1>
            <p className="text-xs text-slate-500">商业交付 · 外包一线默认接单 · 规则可开关</p>
          </div>
        </div>
        <div className="flex gap-2">
          <a href="/desk" target="_blank" rel="noopener noreferrer" className="text-xs font-semibold text-teal-700 hover:underline px-3 py-2">工作台 ↗</a>
          <button type="button" onClick={load} className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-lg border border-slate-200 bg-white">
            <RefreshCw className="w-3.5 h-3.5" /> 刷新
          </button>
          <button type="button" data-testid="admin-save-config" disabled={saving || !config} onClick={save} className="inline-flex items-center gap-1 text-xs font-bold px-4 py-2 rounded-lg bg-[var(--mitako-purple)] text-white disabled:opacity-50">
            <Save className="w-3.5 h-3.5" /> {saving ? '保存中…' : '保存配置'}
          </button>
        </div>
      </header>
      )}

      <div className={embedded ? 'p-6 space-y-6 max-w-3xl' : ''}>
      <main className={embedded ? '' : 'max-w-3xl mx-auto p-6 space-y-6'}>
        {embedded && (
          <div className="flex justify-end gap-2 mb-2">
            <button type="button" onClick={load} className="text-xs font-bold px-3 py-2 rounded-lg border">{t('desk.refresh')}</button>
            <button type="button" data-testid="admin-save-config" disabled={saving || !config} onClick={save} className="text-xs font-bold px-4 py-2 rounded-lg bg-[var(--mitako-purple)] text-white">
              {saving ? '…' : t('admin.routingSaved').slice(0, 2) + '保存'}
            </button>
          </div>
        )}
        {message && (
          <p className="text-sm font-semibold text-teal-700 bg-teal-50 border border-teal-100 rounded-xl px-4 py-3">{message}</p>
        )}

        {loading || !config ? (
          <p className="text-sm text-slate-400">加载配置…</p>
        ) : (
          <>
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <Route className="w-4 h-4 text-[var(--mitako-purple)]" />
                <h2 className="font-bold text-sm">默认接单层级</h2>
              </div>
              <p className="text-sm text-slate-600 mb-3">
                当前默认：<span className="font-mono font-bold text-teal-700">{config.default_required_tier || 'standard'}</span>
                （外包/一线专员）
              </p>
              <p className="text-xs text-slate-500">未命中任何启用规则时，所有会话由 standard 客服接单。</p>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-3">
              <div className="flex items-center gap-2 mb-1">
                <Shield className="w-4 h-4 text-amber-600" />
                <h2 className="font-bold text-sm">路由规则（可开关）</h2>
              </div>
              {(config.rules || []).map(rule => (
                <label key={rule.id} className="flex items-start gap-3 p-3 rounded-xl border border-slate-100 hover:bg-slate-50 cursor-pointer">
                  <input type="checkbox" checked={!!rule.enabled} onChange={() => toggleRule(rule.id)} className="mt-1" />
                  <div>
                    <p className="text-sm font-semibold">{rule.label || rule.id}</p>
                    <p className="text-xs text-slate-500 font-mono mt-0.5">
                      → {rule.required_tier} · {JSON.stringify(rule.condition)}
                    </p>
                  </div>
                </label>
              ))}
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <Clock className="w-4 h-4 text-rose-500" />
                <h2 className="font-bold text-sm">SLA 自动转交</h2>
              </div>
              <label className="flex items-center gap-2 text-sm mb-3">
                <input
                  type="checkbox"
                  checked={!!config.sla?.auto_transfer_enabled}
                  onChange={e => updateSla('auto_transfer_enabled', e.target.checked)}
                />
                启用超时自动转交下一位同事
              </label>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <label className="block">
                  <span className="text-xs text-slate-500">首响超时（秒）</span>
                  <input
                    type="number"
                    min={30}
                    value={config.sla?.first_response_seconds ?? 180}
                    onChange={e => updateSla('first_response_seconds', Number(e.target.value))}
                    className="w-full mt-1 rounded-lg border border-slate-200 px-3 py-2"
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-slate-500">回复超时（秒）</span>
                  <input
                    type="number"
                    min={60}
                    value={config.sla?.reply_timeout_seconds ?? 300}
                    onChange={e => updateSla('reply_timeout_seconds', Number(e.target.value))}
                    className="w-full mt-1 rounded-lg border border-slate-200 px-3 py-2"
                  />
                </label>
              </div>
            </section>
          </>
        )}
      </main>
      </div>
    </>
  );

  if (embedded) {
    return <div className="bg-gradient-to-br from-slate-50 to-white min-h-full">{inner}</div>;
  }

  return (
    <div className="min-h-[100dvh] bg-gradient-to-br from-slate-100 via-white to-[#7B61FF]/5 text-slate-800">
      {inner}
    </div>
  );
}
