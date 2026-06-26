import React, { useEffect, useState } from 'react';
import { AlertTriangle, Map, Sparkles, X } from 'lucide-react';
import CompanionOverlayPortal from './CompanionOverlayPortal.jsx';
import t from '../i18n/index.js';

const PRESETS = [
  { key: 'genshin', label: '原神 · 提瓦特', tone: 'from-cyan-400 to-violet-500' },
  { key: 'sanguo', label: '三国 · 乱世', tone: 'from-amber-500 to-rose-600' },
  { key: 'hp', label: '霍格沃茨', tone: 'from-emerald-400 to-indigo-600' },
  { key: 'cyber', label: '赛博朋克 2077', tone: 'from-fuchsia-500 to-cyan-400' },
];

/** 进入冒险模式 — 世界观选择 + 记忆隔离警告（Portal 居中，不随手机框漂移） */
export default function CompanionAdventureEnterModal({ open, onClose, onConfirm, busy, initialWorld = '' }) {
  const [world, setWorld] = useState('原神 · 提瓦特大陆');

  React.useEffect(() => {
    if (open && initialWorld) setWorld(initialWorld);
  }, [open, initialWorld]);

  const submit = (e) => {
    e.preventDefault();
    const w = world.trim();
    if (!w || busy) return;
    onConfirm?.(w);
  };

  return (
    <CompanionOverlayPortal open={open} onClose={busy ? undefined : onClose} variant="center">
      <div className="rounded-2xl bg-white border border-violet-100 shadow-2xl overflow-hidden animate-fade-up max-h-[min(90dvh,640px)] overflow-y-auto">
        <div className="px-4 py-3 bg-gradient-to-r from-violet-600 via-fuchsia-500 to-orange-400 flex items-center justify-between sticky top-0 z-10">
          <div className="flex items-center gap-2 text-white">
            <Map className="w-5 h-5" />
            <p className="text-sm font-bold">{t('companion.adventureEnterTitle')}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label={t('order.pickerClose')}
            className="touch-target w-8 h-8 rounded-full bg-white/20 flex items-center justify-center"
          >
            <X className="w-4 h-4 text-white" />
          </button>
        </div>

        <form onSubmit={submit} className="p-4 space-y-4">
          <div className="rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50/80 p-3 flex gap-2.5">
            <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="text-xs text-amber-950 leading-relaxed">
              <p className="font-bold mb-1">{t('companion.adventureMemoryWarningTitle')}</p>
              <p>{t('companion.adventureMemoryWarningBody')}</p>
            </div>
          </div>

          <div>
            <label className="text-xs font-bold text-slate-600 mb-2 block">{t('companion.adventureWorldLabel')}</label>
            <input
              value={world}
              onChange={e => setWorld(e.target.value)}
              placeholder={t('companion.adventureWorldPlaceholder')}
              className="w-full rounded-xl border border-violet-100 bg-violet-50/50 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            {PRESETS.map(p => (
              <button
                key={p.key}
                type="button"
                onClick={() => setWorld(p.label)}
                className={`text-[11px] font-semibold px-3 py-1.5 rounded-full text-white bg-gradient-to-r ${p.tone} shadow-sm hover:opacity-90`}
              >
                {p.label}
              </button>
            ))}
          </div>

          <p className="text-[10px] text-slate-400 leading-relaxed">{t('companion.adventureSafetyNote')}</p>

          <button
            type="submit"
            disabled={busy || !world.trim()}
            className="w-full min-h-[48px] rounded-xl bg-gradient-to-r from-violet-600 via-fuchsia-500 to-rose-500 text-white text-sm font-bold flex items-center justify-center gap-2 disabled:opacity-50 shadow-lg"
          >
            <Sparkles className="w-4 h-4" />
            {busy ? t('companion.adventureStarting') : t('companion.adventureStartBtn')}
          </button>
        </form>
      </div>
    </CompanionOverlayPortal>
  );
}
