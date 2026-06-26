import React, { useState } from 'react';
import { Eraser, RefreshCw, ScrollText, X } from 'lucide-react';
import CompanionOverlayPortal from './CompanionOverlayPortal.jsx';
import t from '../i18n/index.js';

/** Talkie 式冒险对话管理 — 分档清除，避免旧 markup 污染 LLM 上下文 */
export default function CompanionAdventureContextModal({
  open,
  onClose,
  onReset,
  busy,
  messageCount = 0,
}) {
  const [confirmMode, setConfirmMode] = useState(null);

  const close = () => {
    if (busy) return;
    setConfirmMode(null);
    onClose?.();
  };

  const runReset = async (mode) => {
    if (busy) return;
    try {
      await onReset?.(mode);
      setConfirmMode(null);
      onClose?.();
    } catch (e) {
      console.error(e);
    }
  };

  const tiers = [
    {
      mode: 'messages',
      icon: Eraser,
      tone: 'from-violet-500 to-fuchsia-500',
      titleKey: 'adventureResetMessagesTitle',
      bodyKey: 'adventureResetMessagesBody',
    },
    {
      mode: 'chapter',
      icon: ScrollText,
      tone: 'from-amber-500 to-orange-500',
      titleKey: 'adventureResetChapterTitle',
      bodyKey: 'adventureResetChapterBody',
    },
  ];

  return (
    <CompanionOverlayPortal open={open} onClose={busy ? undefined : close} variant="center">
      <div className="rounded-2xl bg-white border border-violet-100 shadow-2xl overflow-hidden animate-fade-up max-w-md w-full mx-3">
        <div className="px-4 py-3 bg-gradient-to-r from-violet-600 via-fuchsia-500 to-amber-400 flex items-center justify-between">
          <div className="flex items-center gap-2 text-white">
            <RefreshCw className="w-5 h-5" />
            <p className="text-sm font-bold">{t('companion.adventureContextTitle')}</p>
          </div>
          <button
            type="button"
            onClick={close}
            disabled={busy}
            aria-label={t('order.pickerClose')}
            className="touch-target w-8 h-8 rounded-full bg-white/20 flex items-center justify-center"
          >
            <X className="w-4 h-4 text-white" />
          </button>
        </div>

        <div className="p-4 space-y-3">
          <p className="text-xs text-slate-600 leading-relaxed">
            {t('companion.adventureContextIntro', 'zh-CN', { count: messageCount })}
          </p>

          {tiers.map(({ mode, icon: Icon, tone, titleKey, bodyKey }) => (
            <button
              key={mode}
              type="button"
              disabled={busy}
              onClick={() => setConfirmMode(mode)}
              className={`w-full text-left rounded-xl border p-3 transition-all touch-target ${
                confirmMode === mode
                  ? 'border-violet-400 bg-violet-50/80 ring-2 ring-violet-200'
                  : 'border-slate-100 bg-slate-50/50 hover:border-violet-200 hover:bg-violet-50/40'
              }`}
            >
              <div className="flex gap-3">
                <span className={`w-10 h-10 rounded-xl bg-gradient-to-br ${tone} flex items-center justify-center shrink-0 shadow-sm`}>
                  <Icon className="w-5 h-5 text-white" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-bold text-slate-800">{t(`companion.${titleKey}`)}</p>
                  <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">{t(`companion.${bodyKey}`)}</p>
                </div>
              </div>
            </button>
          ))}

          {confirmMode && (
            <div className="rounded-xl border border-rose-100 bg-rose-50/60 p-3 space-y-2">
              <p className="text-xs text-rose-900 font-semibold">{t('companion.adventureResetConfirm')}</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => runReset(confirmMode)}
                  className="flex-1 touch-target py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-rose-500 to-fuchsia-500 shadow-sm disabled:opacity-50"
                >
                  {busy ? t('companion.adventureResetBusy') : t('companion.adventureResetConfirmBtn')}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmMode(null)}
                  className="px-4 touch-target py-2 rounded-xl text-xs font-semibold text-slate-600 bg-white border border-slate-200"
                >
                  {t('companion.adventureResetCancel')}
                </button>
              </div>
            </div>
          )}

          <p className="text-[10px] text-violet-600/80 text-center leading-relaxed pt-1">
            {t('companion.adventureContextFootnote')}
          </p>
        </div>
      </div>
    </CompanionOverlayPortal>
  );
}
