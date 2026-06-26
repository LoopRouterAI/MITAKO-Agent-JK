import React from 'react';
import { FlaskConical, ChevronDown, RefreshCcw } from 'lucide-react';
import t from '../../i18n/index.js';

export default function AppHeader({ showTestConsole, setShowTestConsole, onRunTest, onReset }) {
  return (
    <header className="glass-panel relative z-40 mb-4 md:mb-5 p-4 md:p-5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="px-4 py-2 rounded-xl bg-[var(--mitako-lime)] shadow-[var(--shadow-lime)]">
          <span className="text-lg font-black italic tracking-tight text-[var(--mitako-ink)]">
            Mitako
            <span className="text-[10px] not-italic font-bold px-2 py-0.5 rounded-full bg-[var(--mitako-orange)] text-white ml-1.5 align-middle">
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
        <span className="text-[10px] font-bold px-2 py-1 rounded-md bg-[var(--mitako-lime)]/30 text-slate-800 border border-[var(--mitako-lime-deep)]/30">
          {t('app.version')}
        </span>
      </div>

      <div className="relative self-start sm:self-auto">
        <button
          type="button"
          onClick={() => setShowTestConsole(v => !v)}
          aria-label={t('test.consoleAria')}
          aria-expanded={showTestConsole}
          aria-haspopup="menu"
          className="touch-target text-sm font-semibold text-slate-600 hover:text-[var(--mitako-purple)] bg-white/80 hover:bg-[#7B61FF]/5 px-4 py-2 rounded-xl border border-slate-200/80 transition-[color,background-color,border-color] flex items-center gap-2 focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/30"
        >
          <FlaskConical className="w-4 h-4 text-[var(--mitako-purple)]" aria-hidden="true" />
          {t('test.console')}
          <ChevronDown className={`w-4 h-4 transition-transform ${showTestConsole ? 'rotate-180' : ''}`} aria-hidden="true" />
        </button>
        {showTestConsole && (
          <div role="menu" aria-label={t('test.consoleExpanded')} className="absolute right-0 mt-2 min-w-[220px] glass-panel p-3 z-50 flex flex-col gap-1 shadow-lg animate-fade-up">
            {[0, 1, 2].map(i => (
              <button
                key={i}
                type="button"
                role="menuitem"
                onClick={() => { onRunTest(i); setShowTestConsole(false); }}
                className="text-left text-xs font-semibold text-slate-600 hover:text-[var(--mitako-purple)] hover:bg-[#7B61FF]/5 p-2.5 rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/30"
              >
                {t(`test.scenario${i + 1}`)}
              </button>
            ))}
            <div className="border-t border-slate-100 pt-2 mt-1">
              <button
                type="button"
                onClick={() => { onReset(); setShowTestConsole(false); }}
                className="w-full flex items-center justify-center gap-1.5 text-xs font-bold text-rose-500 hover:bg-rose-50 p-2 rounded-lg"
              >
                <RefreshCcw className="w-3.5 h-3.5" />
                {t('test.reset')}
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
