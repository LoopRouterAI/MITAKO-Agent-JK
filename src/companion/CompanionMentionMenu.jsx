import React, { useMemo } from 'react';
import {
  collectMentionCandidates,
  insertMention,
  mentionFilterFromInput,
  shouldShowMentionMenu,
} from './adventureMentions.js';
import t from '../i18n/index.js';

/** 冒险模式 @ 圈人候选 — 伙伴 / 主人 / 场景 NPC */
export default function CompanionMentionMenu({
  input,
  setInput,
  adventureActive,
  persona,
  adventureMessages,
}) {
  const filter = mentionFilterFromInput(input);
  const open = shouldShowMentionMenu(input, adventureActive);

  const candidates = useMemo(() => {
    if (!open) return [];
    const all = collectMentionCandidates(persona, adventureMessages);
    if (!filter) return all;
    return all.filter(n => n.toLowerCase().includes(filter));
  }, [open, filter, persona, adventureMessages]);

  if (!open || candidates.length === 0) return null;

  return (
    <div className="px-3 pb-2 border-b border-violet-100/80 bg-violet-50/40">
      <p className="text-[10px] font-bold text-violet-600 mb-1.5">{t('companion.mentionMenuTitle')}</p>
      <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto touch-scroll">
        {candidates.map(name => (
          <button
            key={name}
            type="button"
            onClick={() => setInput(insertMention(input, name))}
            className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-white border border-violet-200 text-violet-800 hover:bg-violet-100 touch-target"
          >
            @{name}
          </button>
        ))}
      </div>
    </div>
  );
}
