import React from 'react';
import t from '../../i18n/index.js';

export default function AppHeader() {
  return (
    <header className="relative z-40 mb-4 flex flex-col gap-4 rounded-[8px] border-2 border-[var(--mitako-ink)] bg-white p-4 shadow-[6px_6px_0_rgba(17,20,17,.92)] sm:flex-row sm:items-center sm:justify-between md:mb-5 md:p-5">
      <div className="flex items-center gap-3">
        <div className="px-4 py-2 rounded-[8px] bg-[var(--mitako-lime)] border-2 border-[var(--mitako-ink)] shadow-[var(--shadow-lime)]">
          <span className="text-lg font-black italic tracking-tight text-[var(--mitako-ink)]">
            Mitako
            <span className="text-[10px] not-italic font-bold px-2 py-0.5 rounded-full bg-white text-[var(--mitako-ink)] border border-[var(--mitako-ink)] ml-1.5 align-middle">
              {t('app.brandTag')}
            </span>
          </span>
        </div>
        <div>
          <h1 className="text-sm md:text-base font-bold text-slate-800 tracking-tight">{t('app.title')}</h1>
          {t('app.subtitle') && (
            <p className="text-[11px] text-slate-500 mt-0.5 hidden sm:block">{t('app.subtitle')}</p>
          )}
        </div>
        <span className="text-[10px] font-bold px-2 py-1 rounded-md bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border border-[var(--mitako-ink)]">
          {t('app.version')}
        </span>
      </div>

      <div className="hidden sm:block text-[11px] font-bold text-[var(--mitako-muted)]">
        {t('agent.online')}
      </div>
    </header>
  );
}
