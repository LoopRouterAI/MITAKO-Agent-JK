import React, { useEffect, useMemo, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { loadingLineForPhase, resolveAdventureLoadingTheme } from './adventureLoadingThemes.js';
import t from '../i18n/index.js';

/** 冒险开篇全屏 Loading — 世界观定制动画与文案 */
export default function AdventureLoadingOverlay({ open, world, phase = 'rift', progress = 0 }) {
  const theme = useMemo(() => resolveAdventureLoadingTheme(world), [world]);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!open) return undefined;
    const id = setInterval(() => setTick(v => v + 1), 2400);
    return () => clearInterval(id);
  }, [open]);

  if (!open) return null;

  const line = loadingLineForPhase(theme, phase, tick);
  const pct = Math.min(100, Math.max(0, progress || 0));

  return (
    <div className="absolute inset-0 z-[90] flex flex-col items-center justify-center overflow-hidden rounded-[inherit]">
      <div className={`absolute inset-0 bg-gradient-to-br ${theme.gradient} opacity-95`} />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.25),transparent_50%)]" />
      <div className="absolute inset-0 animate-pulse bg-[radial-gradient(circle_at_70%_80%,rgba(0,0,0,0.15),transparent_45%)]" />

      {/* 粒子 */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
        {[...Array(12)].map((_, i) => (
          <span
            key={i}
            className={`absolute w-1 h-1 rounded-full ${theme.orb} opacity-70 animate-ping`}
            style={{
              left: `${8 + (i * 7) % 88}%`,
              top: `${12 + (i * 11) % 76}%`,
              animationDelay: `${i * 0.35}s`,
              animationDuration: `${2 + (i % 3)}s`,
            }}
          />
        ))}
      </div>

      <div className="relative z-10 flex flex-col items-center px-6 text-center max-w-[92%]">
        <div className={`relative w-24 h-24 mb-6 rounded-full border-2 ${theme.ring} flex items-center justify-center`}>
          <div className={`absolute inset-2 rounded-full bg-white/10 backdrop-blur-sm animate-spin`} style={{ animationDuration: '3s' }} />
          <Sparkles className="w-10 h-10 text-white drop-shadow-lg animate-pulse" />
        </div>

        <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-white/80 mb-2">
          {t('companion.adventureLoadingBadge')}
        </p>
        <h2 className="text-lg font-black text-white drop-shadow-md mb-1 line-clamp-2">
          {world || t('companion.adventureLoadingWorldFallback')}
        </h2>
        <p className="text-sm text-white/95 font-medium min-h-[3rem] leading-relaxed transition-opacity duration-500">
          {line}
        </p>

        <div className="w-full max-w-xs mt-6">
          <div className="h-1.5 rounded-full bg-white/20 overflow-hidden">
            <div
              className="h-full rounded-full bg-white/90 transition-all duration-700 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[10px] text-white/70 mt-2 font-semibold">{pct}%</p>
        </div>
      </div>
    </div>
  );
}
