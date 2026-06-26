import React from 'react';
import { BookOpen, LogOut, Map, RefreshCw, Share2, X } from 'lucide-react';
import CompanionOverlayPortal from './CompanionOverlayPortal.jsx';
import t from '../i18n/index.js';

/** 微信式 + 菜单 — Portal 底栏，与手机框同宽对齐 */
export default function CompanionActionSheet({
  open,
  onClose,
  adventureActive,
  onEnterAdventure,
  onExitAdventure,
  onOpenShareDemo,
  onOpenContextModal,
}) {
  return (
    <CompanionOverlayPortal open={open} onClose={onClose} variant="sheet">
      <div className="rounded-t-2xl bg-white border-t border-rose-100 shadow-2xl animate-fade-up pb-[env(safe-area-inset-bottom)]">
        <div className="flex items-center justify-between px-4 py-3 border-b border-rose-50">
          <p className="text-sm font-bold text-slate-800">{t('companion.actionSheetTitle')}</p>
          <button type="button" onClick={onClose} className="touch-target w-9 h-9 rounded-full bg-slate-100 flex items-center justify-center">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>
        <div className="grid grid-cols-4 gap-3 p-4">
          {!adventureActive ? (
            <button
              type="button"
              onClick={() => { onClose(); onEnterAdventure?.(); }}
              className="flex flex-col items-center gap-2 touch-target"
            >
              <span className="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center shadow-md">
                <Map className="w-6 h-6 text-white" />
              </span>
              <span className="text-[11px] font-semibold text-slate-700 text-center leading-tight">{t('companion.actionEnterAdventure')}</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => { onClose(); onExitAdventure?.(); }}
              className="flex flex-col items-center gap-2 touch-target"
            >
              <span className="w-14 h-14 rounded-2xl bg-gradient-to-br from-slate-500 to-slate-700 flex items-center justify-center shadow-md">
                <LogOut className="w-6 h-6 text-white" />
              </span>
              <span className="text-[11px] font-semibold text-slate-700 text-center leading-tight">{t('companion.actionExitAdventure')}</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => { onClose(); onOpenShareDemo?.(); }}
            className="flex flex-col items-center gap-2 touch-target"
          >
            <span className="w-14 h-14 rounded-2xl bg-gradient-to-br from-orange-400 to-rose-500 flex items-center justify-center shadow-md">
              <Share2 className="w-6 h-6 text-white" />
            </span>
            <span className="text-[11px] font-semibold text-slate-700 text-center leading-tight">{t('companion.actionShareDemo')}</span>
          </button>
          {adventureActive ? (
            <button
              type="button"
              onClick={() => { onClose(); onOpenContextModal?.(); }}
              className="flex flex-col items-center gap-2 touch-target"
            >
              <span className="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-400 to-amber-400 flex items-center justify-center shadow-md">
                <RefreshCw className="w-6 h-6 text-white" />
              </span>
              <span className="text-[11px] font-semibold text-slate-700 text-center leading-tight">{t('companion.adventureContextTitle')}</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="flex flex-col items-center gap-2 touch-target opacity-60"
            >
              <span className="w-14 h-14 rounded-2xl bg-gradient-to-br from-rose-100 to-amber-50 border border-rose-100 flex items-center justify-center">
                <BookOpen className="w-6 h-6 text-rose-400" />
              </span>
              <span className="text-[11px] font-semibold text-slate-500 text-center leading-tight">{t('companion.actionMoreSoon')}</span>
            </button>
          )}
        </div>
        {adventureActive && (
          <p className="px-4 pb-4 text-[11px] text-violet-600 text-center">{t('companion.adventureExitHint')}</p>
        )}
      </div>
    </CompanionOverlayPortal>
  );
}
