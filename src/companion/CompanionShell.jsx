import React from 'react';
import { Heart, Sparkles, ArrowRight, ExternalLink } from 'lucide-react';
import t from '../i18n/index.js';

/** Companion 专属 Agent — 独立入口占位（Phase A 脚手架） */
export default function CompanionShell() {
  const links = [
    { href: '/', label: t('companion.linkCs'), desc: t('companion.linkCsDesc'), tone: 'purple' },
    { href: '/desk', label: t('companion.linkDesk'), desc: t('companion.linkDeskDesc'), tone: 'teal' },
    { href: '/companion-desk', label: t('companion.linkCompanionDesk'), desc: t('companion.linkCompanionDeskDesc'), tone: 'rose' },
  ];

  return (
    <div className="min-h-[100dvh] bg-gradient-to-br from-[#1a1033] via-[#2d1b69] to-[#0f172a] text-white flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-md text-center">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-[#FF8B38]/30 to-[#7B61FF]/40 border border-white/10 mb-5">
          <Heart className="w-8 h-8 text-[#FFB4C8]" />
        </div>
        <p className="text-xs font-bold tracking-[0.2em] text-[#C8FF1A]/80 uppercase mb-2">{t('companion.badge')}</p>
        <h1 className="text-2xl font-extrabold mb-2">{t('companion.title')}</h1>
        <p className="text-sm text-white/70 leading-relaxed mb-8">{t('companion.subtitle')}</p>

        <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-md p-5 text-left mb-6">
          <div className="flex items-center gap-2 text-[#C8FF1A] mb-3">
            <Sparkles className="w-4 h-4" />
            <span className="text-xs font-bold">{t('companion.phaseNote')}</span>
          </div>
          <p className="text-sm text-white/80 leading-relaxed">{t('companion.phaseBody')}</p>
        </div>

        <div className="space-y-2 text-left">
          <p className="text-[11px] font-bold text-white/40 uppercase tracking-wider px-1">{t('companion.urlMapTitle')}</p>
          {links.map(link => (
            <a
              key={link.href}
              href={link.href}
              target={link.href.startsWith('/') ? '_self' : '_blank'}
              rel="noopener noreferrer"
              className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 px-4 py-3 transition-colors group"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold font-mono text-[#C8FF1A]">{link.href}</p>
                <p className="text-xs text-white/60 mt-0.5">{link.desc}</p>
              </div>
              <ExternalLink className="w-4 h-4 text-white/40 group-hover:text-white/80 flex-shrink-0" />
            </a>
          ))}
        </div>

        <p className="mt-8 text-xs text-white/40 flex items-center justify-center gap-1">
          <ArrowRight className="w-3 h-3" />
          {t('companion.currentUrl')}
          <code className="font-mono text-[#C8FF1A]/90">/companion</code>
        </p>
      </div>
    </div>
  );
}
