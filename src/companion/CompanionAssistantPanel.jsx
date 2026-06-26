import React, { useState } from 'react';
import { Package, Heart, Search, ChevronDown, ChevronUp } from 'lucide-react';
import t from '../i18n/index.js';

/** Phase C：盯单 / 心愿单 / 查价面板 */
export default function CompanionAssistantPanel({ chat, variant = 'dark' }) {
  const light = variant === 'light';
  const shell = light ? 'border-t border-rose-100 bg-rose-50/40' : 'border-t border-white/10 bg-black/20';
  const btnText = light ? 'text-slate-600 hover:text-slate-900' : 'text-white/70 hover:text-white';
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState('watch');
  const [orderId, setOrderId] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const [products, setProducts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const run = async (fn) => {
    setBusy(true);
    setMsg('');
    try {
      await fn();
      setMsg(t('companion.assistantSaved'));
    } catch (e) {
      console.error(e);
      setMsg(t('companion.assistantFailed'));
    } finally {
      setBusy(false);
    }
  };

  const tabs = [
    { id: 'watch', icon: Package, label: t('companion.tabWatch') },
    { id: 'wishlist', icon: Heart, label: t('companion.tabWishlist') },
    { id: 'search', icon: Search, label: t('companion.tabSearch') },
  ];

  return (
    <div className={shell}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className={`w-full flex items-center justify-between px-4 py-2.5 text-xs font-semibold ${btnText}`}
      >
        <span>{t('companion.assistantTitle')}</span>
        {open ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3">
          <div className="flex gap-1 overflow-x-auto">
            {tabs.map(({ id, icon: Icon, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap ${
                  tab === id
                    ? light ? 'bg-rose-200 text-rose-900' : 'bg-[#7B61FF]/50 text-white'
                    : light ? 'bg-white text-slate-500 border border-rose-100' : 'bg-white/5 text-white/60'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />{label}
              </button>
            ))}
          </div>

          {tab === 'watch' && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <input
                  value={orderId}
                  onChange={e => setOrderId(e.target.value)}
                  placeholder={t('companion.watchOrderPlaceholder')}
                  className={`flex-1 rounded-xl px-3 py-2 text-sm ${light ? 'bg-white border border-rose-100' : 'bg-white/10 border border-white/15'}`}
                />
                <button
                  type="button"
                  disabled={busy || !orderId.trim()}
                  onClick={() => run(() => chat.addWatchOrder(orderId.trim()))}
                  className="rounded-xl bg-[#C8FF1A] text-slate-900 px-3 text-xs font-bold"
                >
                  {t('companion.watchAdd')}
                </button>
              </div>
              <ul className="space-y-1 max-h-24 overflow-auto text-xs text-white/60">
                {(chat.watchOrders || []).map(w => (
                  <li key={w.id} className="font-mono">{w.order_id}</li>
                ))}
                {!chat.watchOrders?.length && <li>{t('companion.watchEmpty')}</li>}
              </ul>
            </div>
          )}

          {tab === 'wishlist' && (
            <ul className="space-y-1 max-h-32 overflow-auto text-xs">
              {(chat.wishlist || []).map(w => (
                <li key={w.id} className="flex justify-between text-white/70">
                  <span>{w.product_id}</span>
                  <span className="text-white/40 truncate max-w-[50%]">{w.note}</span>
                </li>
              ))}
              {!chat.wishlist?.length && <li className="text-white/40">{t('companion.wishlistEmpty')}</li>}
            </ul>
          )}

          {tab === 'search' && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <input
                  value={searchQ}
                  onChange={e => setSearchQ(e.target.value)}
                  placeholder={t('companion.searchPlaceholder')}
                  className={`flex-1 rounded-xl px-3 py-2 text-sm ${light ? 'bg-white border border-rose-100' : 'bg-white/10 border border-white/15'}`}
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      setProducts(await chat.searchProducts(searchQ));
                    } finally {
                      setBusy(false);
                    }
                  }}
                  className="rounded-xl bg-white/10 px-3 text-xs font-bold"
                >
                  {t('companion.searchBtn')}
                </button>
              </div>
              <ul className="space-y-2 max-h-36 overflow-auto">
                {products.map(p => (
                  <li key={p.product_id} className="rounded-xl bg-white/5 p-2 flex justify-between items-center gap-2 text-xs">
                    <div>
                      <p className="font-semibold">{p.name}</p>
                      <p className="text-white/50">¥{p.price} · {p.stock}</p>
                    </div>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => run(() => chat.addWishlistItem(p.product_id, p.name))}
                      className="shrink-0 rounded-lg bg-[#FFB4C8]/30 px-2 py-1 font-bold text-[#FFB4C8]"
                    >
                      {t('companion.wishlistAdd')}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {msg && <p className="text-[11px] text-[#C8FF1A]">{msg}</p>}
        </div>
      )}
    </div>
  );
}
