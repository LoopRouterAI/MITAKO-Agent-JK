import React from 'react';
import { ExternalLink, Share2, X } from 'lucide-react';
import CompanionOverlayPortal from './CompanionOverlayPortal.jsx';
import t from '../i18n/index.js';

/** 演示：MITAKO App → Companion 分享卡片对接说明（非「分享目录」） */
export default function CompanionShareDemoModal({ open, onClose, onSimulateSku, onSimulateArticle }) {
  return (
    <CompanionOverlayPortal open={open} onClose={onClose} variant="center">
      <div className="rounded-2xl bg-white border border-orange-100 shadow-2xl overflow-hidden max-h-[min(88dvh,560px)] overflow-y-auto">
        <div className="px-4 py-3 bg-gradient-to-r from-orange-500 to-rose-500 flex items-center justify-between sticky top-0 z-10">
          <div className="flex items-center gap-2 text-white">
            <Share2 className="w-5 h-5" />
            <p className="text-sm font-bold">{t('companion.shareDemoTitle')}</p>
          </div>
          <button type="button" onClick={onClose} className="touch-target w-8 h-8 rounded-full bg-white/20 flex items-center justify-center">
            <X className="w-4 h-4 text-white" />
          </button>
        </div>

        <div className="p-4 space-y-4 text-sm text-slate-700 leading-relaxed">
          <p className="rounded-xl bg-amber-50 border border-amber-100 px-3 py-2.5 text-xs text-amber-950">
            {t('companion.shareDemoNotice')}
          </p>
          <p>{t('companion.shareDemoBody')}</p>
          <ul className="text-xs space-y-2 text-slate-600 list-disc pl-4">
            <li>{t('companion.shareDemoFlow1')}</li>
            <li>{t('companion.shareDemoFlow2')}</li>
            <li>{t('companion.shareDemoFlow3')}</li>
          </ul>

          <div className="grid gap-2 pt-1">
            <button
              type="button"
              onClick={() => { onSimulateSku?.(); onClose(); }}
              className="w-full rounded-xl border border-orange-200 bg-orange-50 px-4 py-3 text-left hover:bg-orange-100 touch-target"
            >
              <span className="text-xs font-bold text-orange-700">{t('companion.shareDemoSimSku')}</span>
              <span className="block text-[11px] text-slate-500 mt-1">{t('companion.shareDemoSimSkuHint')}</span>
            </button>
            <button
              type="button"
              onClick={() => { onSimulateArticle?.(); onClose(); }}
              className="w-full rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-left hover:bg-rose-100 touch-target"
            >
              <span className="text-xs font-bold text-rose-700">{t('companion.shareDemoSimArticle')}</span>
              <span className="block text-[11px] text-slate-500 mt-1">{t('companion.shareDemoSimArticleHint')}</span>
            </button>
          </div>

          <p className="text-[10px] text-slate-400 flex items-center gap-1">
            <ExternalLink className="w-3 h-3" />
            {t('companion.shareDemoDeepLink')}
          </p>
        </div>
      </div>
    </CompanionOverlayPortal>
  );
}
