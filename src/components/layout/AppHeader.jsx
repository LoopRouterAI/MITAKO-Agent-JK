import React from 'react';
import t from '../../i18n/index.js';

export default function AppHeader() {
  return (
    <header className="relative z-40 mb-4 flex flex-col gap-4 rounded-[8px] border-2 border-[var(--mitako-ink)] bg-white p-4 shadow-[6px_6px_0_rgba(17,20,17,.92)] sm:flex-row sm:items-center sm:justify-between md:mb-5 md:p-5">
      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        <div className="shrink-0 rounded-[8px] border-2 border-[var(--mitako-ink)] bg-[var(--mitako-lime)] px-3 py-2 shadow-[var(--shadow-lime)] sm:px-4">
          <span className="inline-flex items-center whitespace-nowrap text-lg font-black italic text-[var(--mitako-ink)]">
            Mitako
            <span className="ml-1.5 inline-flex whitespace-nowrap rounded-full border border-[var(--mitako-ink)] bg-white px-1.5 py-0.5 text-[10px] font-bold not-italic text-[var(--mitako-ink)] sm:px-2">
              {t('app.brandTag')}
            </span>
          </span>
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-bold text-slate-800 md:text-base">{t('app.title')}</h1>
          {t('app.subtitle') && (
            <p className="text-[11px] text-slate-500 mt-0.5 hidden sm:block">{t('app.subtitle')}</p>
          )}
        </div>
        <span className="shrink-0 whitespace-nowrap rounded-md border border-[var(--mitako-ink)] bg-[var(--mitako-lime)] px-2 py-1 text-[10px] font-bold text-[var(--mitako-ink)]">
          {t('app.version')}
        </span>
      </div>

      <div className="hidden sm:block text-[11px] font-bold text-[var(--mitako-muted)]">
        {t('agent.online')}
      </div>
    </header>
  );
}
