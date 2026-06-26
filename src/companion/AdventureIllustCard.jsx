import React from 'react';
import { ImageIcon, Loader2 } from 'lucide-react';
import t from '../i18n/index.js';

/** 冒险配图卡 — Loading / 成功 / 失败 */
export default function AdventureIllustCard({ illust }) {
  if (!illust || illust.status === 'none') return null;

  const isPortrait = illust.aspect === '3:4' || (illust.size && illust.size.startsWith('1760'));
  const aspectClass = isPortrait ? 'aspect-[3/4] max-w-[72%] mx-auto' : 'aspect-video w-full';

  if (illust.status === 'ready' && illust.url) {
    return (
      <figure className={`mt-2.5 ${aspectClass} rounded-xl overflow-hidden border border-violet-200/80 shadow-md bg-slate-100`}>
        <a href={illust.url} target="_blank" rel="noopener noreferrer" className="block w-full h-full">
          <img
            src={illust.url}
            alt={t('companion.adventureIllustAlt')}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        </a>
      </figure>
    );
  }

  if (illust.status === 'failed') {
    return (
      <div className="mt-2.5 rounded-xl border border-dashed border-slate-200 bg-slate-50/80 px-3 py-2 text-[11px] text-slate-500 flex items-center gap-2">
        <ImageIcon className="w-4 h-4 shrink-0" />
        {t('companion.adventureIllustFailed')}
      </div>
    );
  }

  return (
    <div className={`mt-2.5 ${aspectClass} rounded-xl overflow-hidden border border-violet-100 bg-gradient-to-br from-violet-50 via-fuchsia-50/50 to-amber-50/30 flex flex-col items-center justify-center gap-2`}>
      <Loader2 className="w-6 h-6 text-violet-500 animate-spin" />
      <p className="text-[11px] font-medium text-violet-600 animate-pulse">{t('companion.adventureIllustLoading')}</p>
    </div>
  );
}
