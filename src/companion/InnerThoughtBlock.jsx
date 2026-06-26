import React, { useState } from 'react';
import { ChevronDown, Sparkles } from 'lucide-react';
import t from '../i18n/index.js';

/** 伙伴内心独白 — 默认折叠，点击展开 */
export default function InnerThoughtBlock({ inner }) {
  const [open, setOpen] = useState(false);
  if (!inner?.full && !inner?.summary) return null;

  const summary = inner.summary || inner.full?.slice(0, 24) || t('companion.adventureInnerDefault');

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full text-left flex items-center gap-2 rounded-xl border border-fuchsia-200/80 bg-gradient-to-r from-fuchsia-50/90 to-violet-50/80 px-3 py-2.5 touch-target active:scale-[0.99] transition-transform"
        aria-expanded={open}
      >
        <span className="flex-shrink-0 w-7 h-7 rounded-full bg-fuchsia-100 flex items-center justify-center">
          <Sparkles className="w-3.5 h-3.5 text-fuchsia-600" />
        </span>
        <span className="flex-1 min-w-0 text-[11px] font-semibold text-fuchsia-900 truncate">
          {open ? t('companion.adventureInnerCollapse') : t('companion.adventureInnerExpand', 'zh-CN', { summary })}
        </span>
        <ChevronDown className={`w-4 h-4 text-fuchsia-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="mt-1.5 rounded-xl border border-fuchsia-100 bg-white/90 px-3 py-2.5 text-[12px] leading-relaxed text-fuchsia-950 italic animate-fade-up">
          {inner.full || inner.summary}
        </div>
      )}
    </div>
  );
}
