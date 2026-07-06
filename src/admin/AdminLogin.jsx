import React, { useEffect, useState } from 'react';
import { Lock, LogIn, Shield, KeyRound } from 'lucide-react';
import t from '../i18n/index.js';
import { login, setAuthSession } from '../lib/authClient.js';

const SSO_TENANT_KEY = 'mitako_sso_tenant_v1';

export default function AdminLogin({ onSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [tenantId, setTenantId] = useState('mitako');
  const [tenants, setTenants] = useState([]);
  const [ssoLocal, setSsoLocal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/v1/auth/tenants')
      .then(r => r.json())
      .then(d => { if (d.ok) setTenants(d.tenants || []); })
      .catch(console.error);
    fetch('/api/v1/auth/status')
      .then(r => r.json())
      .then(d => { if (d.ok) setSsoLocal(Boolean(d.sso_local_enabled)); })
      .catch(console.error);
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const user = await login(username.trim(), password, tenantId);
      onSuccess?.(user);
    } catch {
      setError(t('admin.loginFailed'));
    } finally {
      setLoading(false);
    }
  };

  const ssoLogin = async () => {
    setLoading(true);
    setError('');
    try {
      const ar = await fetch(`/api/v1/auth/sso/${tenantId}/authorize`);
      const auth = await ar.json();
      if (!auth.ok) throw new Error(auth.error || 'sso_failed');
      if (auth.mode === 'local' && auth.local_enabled) {
        const cr = await fetch(auth.local_callback_url);
        const data = await cr.json();
        if (!data.ok) throw new Error(data.error || 'sso_local_failed');
        setAuthSession(data.token, data.user);
        onSuccess?.(data.user);
        return;
      }
      try {
        sessionStorage.setItem(SSO_TENANT_KEY, tenantId);
      } catch {
        /* ignore */
      }
      window.location.href = auth.authorize_url;
    } catch {
      setError(t('admin.loginFailed'));
    } finally {
      setLoading(false);
    }
  };

  const currentTenant = tenants.find(x => x.tenant_id === tenantId);

  return (
    <div className="mitako-ppt-scope min-h-[100dvh] flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-md rounded-[8px] border-2 border-[var(--mitako-ink)] bg-white shadow-[8px_8px_0_rgba(17,20,17,.92)] p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-2 border-[var(--mitako-ink)] flex items-center justify-center">
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-slate-900">{t('admin.loginTitle')}</h1>
            <p className="text-xs text-slate-500">{t('admin.loginSubtitle')}</p>
          </div>
        </div>
        <label className="block text-xs font-bold text-slate-600 mb-1">{t('admin.tenantLabel')}</label>
        <select value={tenantId} onChange={e => setTenantId(e.target.value)} className="w-full rounded-[8px] border-2 border-[var(--mitako-ink)] px-4 py-3 mb-4 text-sm focus:ring-2 focus:ring-[var(--mitako-lime)]/50 outline-none">
          {(tenants.length ? tenants : [{ tenant_id: 'mitako', name: 'MITAKO' }]).map(tn => (
            <option key={tn.tenant_id} value={tn.tenant_id}>{tn.name || tn.tenant_id}</option>
          ))}
        </select>
        <label className="block text-xs font-bold text-slate-600 mb-1">{t('admin.username')}</label>
        <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full rounded-[8px] border-2 border-[var(--mitako-ink)] px-4 py-3 mb-4 text-sm focus:ring-2 focus:ring-[var(--mitako-lime)]/50 outline-none" autoComplete="username" />
        <label className="block text-xs font-bold text-slate-600 mb-1">{t('admin.password')}</label>
        <div className="relative mb-4">
          <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full rounded-[8px] border-2 border-[var(--mitako-ink)] pl-10 pr-4 py-3 text-sm focus:ring-2 focus:ring-[var(--mitako-lime)]/50 outline-none" autoComplete="current-password" />
        </div>
        {error && <p className="text-sm text-rose-600 mb-3">{error}</p>}
        <button type="submit" disabled={loading} className="w-full flex items-center justify-center gap-2 rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-2 border-[var(--mitako-ink)] shadow-[4px_4px_0_rgba(17,20,17,.92)] font-black py-3 hover:-translate-y-0.5 disabled:opacity-60">
          <LogIn className="w-4 h-4" />{loading ? t('admin.loggingIn') : t('admin.loginBtn')}
        </button>
        {currentTenant?.sso_enabled && (
          <button type="button" disabled={loading} onClick={ssoLogin} className="w-full mt-3 flex items-center justify-center gap-2 rounded-[8px] border border-slate-300 font-bold py-3 text-sm hover:bg-slate-50">
            <KeyRound className="w-4 h-4" />{ssoLocal ? t('admin.ssoLocalLogin') : t('admin.ssoLogin')}
          </button>
        )}
        <p className="mt-4 text-[11px] text-slate-400 text-center">{t('admin.loginHint')}</p>
      </form>
    </div>
  );
}
