import React, { useState } from 'react';
import { defineComponent, createLibrary } from '@openuidev/react-lang';
import { z } from 'zod/v4';
import { Check, Heart, Package, Search, Sparkles } from 'lucide-react';
import t from '../../i18n/index.js';
import { OrderProgressCard } from './openUILibrary.jsx';

const productSchema = z.object({
  product_id: z.string(),
  name: z.string(),
  price: z.number(),
  stock: z.string(),
});

/** 盯单交互卡 — Agent 检测到盯单诉求后推送，用户在卡片内确认订单号 */
export const CompanionWatchFormCard = defineComponent({
  name: 'CompanionWatchFormCard',
  props: z.object({
    order_id: z.string().optional(),
    hint: z.string().optional(),
    prefilled: z.boolean().optional(),
    onSubmit: z.any().optional(),
  }),
  component: ({ props }) => {
    const { hint, prefilled, onSubmit } = props;
    const [orderId, setOrderId] = useState(props.order_id || '');
    const [busy, setBusy] = useState(false);
    const [done, setDone] = useState(false);

    const submit = async () => {
      const oid = orderId.trim();
      if (!oid || busy) return;
      setBusy(true);
      try {
        await onSubmit?.({ order_id: oid });
        setDone(true);
      } finally {
        setBusy(false);
      }
    };

    if (done) {
      return (
        <div className="w-full max-w-[340px] rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-4 animate-fade-up">
          <div className="flex items-center gap-2 text-emerald-700">
            <Check className="w-5 h-5" />
            <span className="text-sm font-bold">{t('companionCards.watchDone')}</span>
          </div>
          <p className="text-xs text-slate-500 mt-2 font-mono">#{orderId.trim().toUpperCase()}</p>
        </div>
      );
    }

    return (
      <div className="w-full max-w-[340px] rounded-2xl border border-rose-200/80 bg-gradient-to-br from-rose-50/90 to-white p-4 animate-fade-up shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-9 h-9 rounded-xl bg-rose-100 flex items-center justify-center">
            <Package className="w-4 h-4 text-rose-600" />
          </div>
          <div>
            <p className="text-sm font-bold text-slate-800">{t('companionCards.watchTitle')}</p>
            <p className="text-[11px] text-slate-500">{hint || t('companionCards.watchHint')}</p>
          </div>
        </div>
        <input
          value={orderId}
          onChange={e => setOrderId(e.target.value.toUpperCase())}
          placeholder={t('companion.watchOrderPlaceholder')}
          className="w-full rounded-xl border border-rose-100 bg-white px-3 py-2.5 text-sm font-mono mb-3 focus:outline-none focus:ring-2 focus:ring-rose-200"
        />
        {prefilled && (
          <p className="text-[10px] text-rose-500 mb-2">{t('companionCards.watchPrefilled')}</p>
        )}
        <button
          type="button"
          disabled={busy || !orderId.trim()}
          onClick={submit}
          className="w-full min-h-[44px] rounded-xl bg-gradient-to-r from-rose-400 to-fuchsia-500 text-white text-sm font-bold disabled:opacity-50"
        >
          {busy ? t('companionCards.working') : t('companion.watchAdd')}
        </button>
      </div>
    );
  },
});

/** 商品查价/心愿单交互卡 — 可搜索、点选、加入心愿单 */
export const CompanionProductPickerCard = defineComponent({
  name: 'CompanionProductPickerCard',
  props: z.object({
    query: z.string().optional(),
    products: z.array(productSchema).optional(),
    needs_input: z.boolean().optional(),
    wishlist_mode: z.boolean().optional(),
    onSearch: z.any().optional(),
    onAddWishlist: z.any().optional(),
  }),
  component: ({ props }) => {
    const { wishlist_mode, onSearch, onAddWishlist } = props;
    const [query, setQuery] = useState(props.query || '');
    const [products, setProducts] = useState(props.products || []);
    const [busy, setBusy] = useState(false);
    const [addedId, setAddedId] = useState('');

    const search = async () => {
      const q = query.trim();
      if (!q || busy) return;
      setBusy(true);
      try {
        const hits = await onSearch?.({ query: q });
        setProducts(Array.isArray(hits) ? hits : []);
      } finally {
        setBusy(false);
      }
    };

    const addWish = async (p) => {
      if (busy) return;
      setBusy(true);
      try {
        await onAddWishlist?.({ product_id: p.product_id, note: p.name });
        setAddedId(p.product_id);
      } finally {
        setBusy(false);
      }
    };

    return (
      <div className="w-full max-w-[360px] rounded-2xl border border-fuchsia-200/70 bg-gradient-to-br from-fuchsia-50/80 to-white p-4 animate-fade-up shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-9 h-9 rounded-xl bg-fuchsia-100 flex items-center justify-center">
            {wishlist_mode ? <Heart className="w-4 h-4 text-fuchsia-600" /> : <Search className="w-4 h-4 text-fuchsia-600" />}
          </div>
          <div>
            <p className="text-sm font-bold text-slate-800">
              {wishlist_mode ? t('companionCards.wishlistTitle') : t('companionCards.searchTitle')}
            </p>
            <p className="text-[11px] text-slate-500">{t('companionCards.searchSubtitle')}</p>
          </div>
        </div>
        <div className="flex gap-2 mb-3">
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={t('companion.searchPlaceholder')}
            className="flex-1 rounded-xl border border-fuchsia-100 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-fuchsia-200"
            onKeyDown={e => e.key === 'Enter' && search()}
          />
          <button
            type="button"
            disabled={busy}
            onClick={search}
            className="rounded-xl bg-[var(--mitako-lime)] text-slate-900 px-3 text-xs font-bold"
          >
            {t('companion.searchBtn')}
          </button>
        </div>
        <ul className="space-y-2 max-h-48 overflow-auto">
          {products.length === 0 && (
            <li className="text-xs text-slate-400 text-center py-4">{t('companionCards.searchEmpty')}</li>
          )}
          {products.map(p => (
            <li key={p.product_id} className="rounded-xl bg-white border border-rose-50 p-2.5 flex justify-between gap-2 items-center">
              <div className="min-w-0">
                <p className="text-xs font-bold text-slate-800 truncate">{p.name}</p>
                <p className="text-[10px] text-slate-500">¥{p.price} · {p.stock}</p>
              </div>
              <button
                type="button"
                disabled={busy || addedId === p.product_id}
                onClick={() => addWish(p)}
                className="shrink-0 rounded-lg bg-rose-100 text-rose-700 px-2 py-1 text-[10px] font-bold"
              >
                {addedId === p.product_id ? t('companionCards.added') : t('companion.wishlistAdd')}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  },
});

/** MITAKO 分享卡 — 伙伴分享的 SKU / 文章 */
export const CompanionShareCard = defineComponent({
  name: 'CompanionShareCard',
  props: z.object({
    type: z.string(),
    product_id: z.string().optional(),
    name: z.string().optional(),
    title: z.string().optional(),
    price: z.number().optional(),
    stock: z.string().optional(),
    summary: z.string().optional(),
    cover: z.string().optional(),
    image: z.string().optional(),
    tag: z.string().optional(),
    app_path: z.string().optional(),
  }),
  component: ({ props }) => {
    const isSku = props.type === 'sku';
    const img = props.image || props.cover;
    const headline = isSku ? props.name : props.title;
    const sub = isSku ? `¥${props.price ?? '—'} · ${props.stock || ''}` : props.summary;

    return (
      <a
        href={props.app_path || '#'}
        target="_blank"
        rel="noopener noreferrer"
        className="block w-full max-w-[340px] rounded-2xl border border-orange-200/80 bg-gradient-to-br from-orange-50/90 to-white overflow-hidden animate-fade-up shadow-sm hover:shadow-md transition-shadow"
      >
        {img && (
          <img src={img} alt="" className="w-full h-36 object-cover" loading="lazy" />
        )}
        <div className="p-3">
          <p className="text-[10px] font-bold text-orange-600 mb-1">
            {isSku ? t('companionCards.shareSkuBadge') : (props.tag || t('companionCards.shareArticleBadge'))}
          </p>
          <p className="text-sm font-bold text-slate-800 line-clamp-2">{headline}</p>
          {sub && <p className="text-xs text-slate-500 mt-1 line-clamp-2">{sub}</p>}
          <p className="text-[10px] text-orange-500 mt-2 font-semibold">{t('companionCards.shareOpenInApp')}</p>
        </div>
      </a>
    );
  },
});

/** Tool 执行结果卡 — 服务端 Tool 完成后反馈 */
export const CompanionToolResultCard = defineComponent({
  name: 'CompanionToolResultCard',
  props: z.object({
    kind: z.string(),
    success: z.boolean(),
    title: z.string(),
    detail: z.string().optional(),
  }),
  component: ({ props }) => {
    const { success, title, detail } = props;
    return (
      <div className={`w-full max-w-[320px] rounded-2xl border p-4 animate-fade-up ${
        success ? 'border-emerald-200 bg-emerald-50/80' : 'border-rose-200 bg-rose-50/80'
      }`}>
        <div className="flex items-center gap-2">
          {success ? <Sparkles className="w-4 h-4 text-emerald-600" /> : <Package className="w-4 h-4 text-rose-600" />}
          <span className="text-sm font-bold text-slate-800">{title}</span>
        </div>
        {detail && <p className="text-xs text-slate-600 mt-2">{detail}</p>}
      </div>
    );
  },
});

export const companionOpenUILibrary = createLibrary({
  components: [CompanionWatchFormCard, CompanionProductPickerCard, CompanionShareCard, CompanionToolResultCard, OrderProgressCard],
});

export const COMPANION_CARD_RENDERERS = {
  companion_watch_form: CompanionWatchFormCard,
  companion_product_picker: CompanionProductPickerCard,
  companion_share: CompanionShareCard,
  companion_tool_result: CompanionToolResultCard,
  order_progress: OrderProgressCard,
};
