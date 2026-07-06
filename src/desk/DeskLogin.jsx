import React, { useState } from 'react';
import { Headphones, LogIn } from 'lucide-react';
import t from '../i18n/index.js';
import { login } from '../lib/authClient.js';

export default function DeskLogin({ onSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const user = await login(username.trim(), password);
      onSuccess?.(user);
    } catch {
      setError(t('desk.loginFailed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mitako-ppt-scope min-h-[100dvh] flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm rounded-[8px] bg-white border-2 border-[var(--mitako-ink)] shadow-[8px_8px_0_rgba(17,20,17,.92)] p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-[8px] bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-2 border-[var(--mitako-ink)] flex items-center justify-center">
            <Headphones className="w-6 h-6" />
          </div>
          <div>
            <h1 className="font-bold">{t('desk.loginTitle')}</h1>
            <p className="text-xs text-slate-500">{t('desk.loginSubtitle')}</p>
          </div>
        </div>
        <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full border-2 border-[var(--mitako-ink)] rounded-[8px] px-3 py-2 mb-3 text-sm focus:ring-2 focus:ring-[var(--mitako-lime)]/50 outline-none" />
        <input type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full border-2 border-[var(--mitako-ink)] rounded-[8px] px-3 py-2 mb-3 text-sm focus:ring-2 focus:ring-[var(--mitako-lime)]/50 outline-none" />
        {error && <p className="text-sm text-rose-600 mb-2">{error}</p>}
        <button type="submit" disabled={loading} className="w-full flex items-center justify-center gap-2 bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-2 border-[var(--mitako-ink)] shadow-[4px_4px_0_rgba(17,20,17,.92)] font-black py-3 rounded-[8px]">
          <LogIn className="w-4 h-4" /> {loading ? t('desk.loggingIn') : t('desk.loginBtn')}
        </button>
      </form>
    </div>
  );
}
