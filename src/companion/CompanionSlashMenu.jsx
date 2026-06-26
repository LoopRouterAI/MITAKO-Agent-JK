import React, { useMemo } from 'react';
import { GALGAME_SLASH_MAP } from './adventureMentions.js';
import t from '../i18n/index.js';

/** 输入 / 时弹出的指令候选菜单 */
export default function CompanionSlashMenu({
  input,
  adventureActive,
  hasOrders,
  onPick,
}) {
  const commands = useMemo(() => {
    const galLabels = {
      '/观察': t('companion.slashLook'),
      '/调查': t('companion.slashInspect'),
      '/威胁': t('companion.slashThreaten'),
      '/沉默': t('companion.slashSilent'),
      '/逃跑': t('companion.slashFlee'),
      '/等待': t('companion.slashWait'),
    };
    const galHints = {
      '/观察': t('companion.slashLookHint'),
      '/调查': t('companion.slashInspectHint'),
      '/威胁': t('companion.slashThreatenHint'),
      '/沉默': t('companion.slashSilentHint'),
      '/逃跑': t('companion.slashFleeHint'),
      '/等待': t('companion.slashWaitHint'),
    };
    const galCmds = Object.keys(GALGAME_SLASH_MAP).map(cmd => ({
      id: cmd,
      cmd,
      label: galLabels[cmd] || cmd,
      hint: galHints[cmd] || '',
      show: adventureActive,
    }));

    const all = [
      {
        id: 'enter',
        cmd: '/冒险 ',
        label: t('companion.slashEnterAdventure'),
        hint: t('companion.slashEnterHint'),
        show: !adventureActive,
      },
      {
        id: 'exit',
        cmd: '/退出冒险',
        label: t('companion.slashExitAdventure'),
        hint: t('companion.slashExitHint'),
        show: adventureActive,
      },
      ...galCmds,
      {
        id: 'help',
        cmd: '/help',
        label: t('companion.slashHelp'),
        hint: t('companion.slashHelpHint'),
        show: true,
      },
      {
        id: 'order',
        cmd: '/订单 ',
        label: t('companion.slashOrder'),
        hint: t('companion.slashOrderHint'),
        show: hasOrders && !adventureActive,
      },
    ];
    const needle = (input || '').trim().toLowerCase();
    return all.filter(c => c.show && c.cmd.toLowerCase().startsWith(needle));
  }, [input, adventureActive, hasOrders]);

  if (!input?.startsWith('/') || commands.length === 0) return null;

  return (
    <div className="px-3 pb-2 border-b border-rose-100/80 bg-white/95">
      <p className="text-[10px] font-bold text-slate-400 mb-1.5">{t('companion.slashMenuTitle')}</p>
      <div className="flex flex-col gap-1 max-h-40 overflow-y-auto touch-scroll">
        {commands.map(c => (
          <button
            key={c.id}
            type="button"
            onClick={() => onPick?.(c.cmd)}
            className="w-full text-left rounded-xl px-3 py-2.5 hover:bg-violet-50 active:bg-violet-100 border border-transparent hover:border-violet-100 transition-colors touch-target"
          >
            <span className="text-[12px] font-bold text-violet-700 font-mono">{c.cmd.trim()}</span>
            <span className="block text-[11px] text-slate-600 mt-0.5">{c.label}</span>
            <span className="block text-[10px] text-slate-400">{c.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
