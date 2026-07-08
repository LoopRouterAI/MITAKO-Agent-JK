import React, { useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Send, Headphones, Plus, Package, Image, Camera, MapPin, ShoppingBag, X } from 'lucide-react';
import t from '../../i18n/index.js';

const DEMO_PRODUCTS = [
  {
    productId: 'SKU-HQ-SCHOOL-BADGE-SET',
    sku: 'HQ-SCHOOL-BADGE-SET',
    name: '排球少年登校系列吧唧套装',
    meta: '最近浏览：今天 14:20',
    status: '现货少量，部分规格为预售',
    ask: '想确认规格、库存和预计发货时间',
  },
  {
    productId: 'SKU-MITAKO-DOLL-90',
    sku: 'MITAKO-DOLL-90',
    name: '角色徽章 病患款 90mm',
    meta: '最近浏览：昨天 21:08',
    status: '同款存在 75mm / 90mm 规格',
    ask: '想核对 90mm 规格是否还有库存',
  },
  {
    productId: 'SKU-BLIND-BOX-SP-01',
    sku: 'BLIND-BOX-SP-01',
    name: '限定盲抽系列补款商品',
    meta: '最近浏览：本周一 09:35',
    status: '补款期内，发货批次待同步',
    ask: '想了解补款后什么时候发货',
  },
  {
    productId: 'SKU-BL-LOTTERY-20',
    sku: 'BL-LOTTERY-20',
    name: '蓝色监狱大赏盲盒 20 抽连包',
    meta: '收藏商品：昨天 19:48',
    status: '活动已开奖，可查中奖规则',
    ask: '想确认中奖率、公示规则和复核入口',
  },
  {
    productId: 'SKU-CONAN-BADGE-75',
    sku: 'CONAN-BADGE-75',
    name: '名侦探柯南 角色徽章 75mm',
    meta: '最近浏览：今天 10:12',
    status: '现货，预计 72 小时内出库',
    ask: '想确认是否能尽快发货',
  },
  {
    productId: 'SKU-HQ-POSTCARD-12',
    sku: 'HQ-POSTCARD-12',
    name: '排球少年横断幕明信片 12 枚套装',
    meta: '加购商品：今天 12:05',
    status: '仓库现货，纸品需防折包装',
    ask: '想确认包装和发货时效',
  },
  {
    productId: 'SKU-GENSHIN-XIAO-FIGURE',
    sku: 'GENSHIN-XIAO-FIGURE',
    name: '原神 魈 1/7 比例手办',
    meta: '历史购买：售后处理中',
    status: '高客单价，售后需凭证审核',
    ask: '想了解破损售后需要哪些材料',
  },
  {
    productId: 'SKU-GENSHIN-ZHONGLI-PRE',
    sku: 'GENSHIN-ZHONGLI-PRE',
    name: '原神 钟离 1/7 手办预售定金',
    meta: '最近浏览：本周三 18:22',
    status: '预售排期，预计 8 月到货',
    ask: '想确认预售是否可取消或转尾款',
  },
  {
    productId: 'SKU-HSR-ACRYLIC-STAND',
    sku: 'HSR-ACRYLIC-STAND',
    name: '崩坏：星穹铁道 亚克力立牌',
    meta: '浏览记录：上周五 22:30',
    status: '多规格，需确认角色与尺寸',
    ask: '想核对角色、尺寸和库存',
  },
  {
    productId: 'SKU-HQ-MYSTERY-PACK',
    sku: 'HQ-MYSTERY-PACK',
    name: '排球少年随机徽章 30 抽连包',
    meta: '热门咨询：未成年人退款场景',
    status: '随机/盲抽规则需购买前确认',
    ask: '想了解随机规则和退款边界',
  },
  {
    productId: 'SKU-JJK-CARD-BINDER',
    sku: 'JJK-CARD-BINDER',
    name: '咒术回战收藏卡册套装',
    meta: '最近浏览：昨天 08:16',
    status: '预售转现货中',
    ask: '想确认什么时候能发出',
  },
];

const DEMO_ADDRESSES = [
  {
    addressId: 'addr_sz_001',
    label: '深圳南山 科技园',
    maskedDetail: '广东省深圳市南山区 科技园片区',
    phoneTail: '2389',
    tag: '默认',
  },
  {
    addressId: 'addr_sh_002',
    label: '上海闵行 家庭地址',
    maskedDetail: '上海市闵行区 虹桥商务区',
    phoneTail: '9162',
    tag: '备用',
  },
];

const sheetMotion = {
  initial: { opacity: 0, y: 34, scale: 0.985 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: 22, scale: 0.985 },
  transition: { type: 'spring', stiffness: 420, damping: 34, mass: 0.8 },
};

function ToolPickerSheet({ open, title, desc, type, items, onClose, onSelect }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute inset-x-0 bottom-full z-50 px-3 pb-2"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.section
            {...sheetMotion}
            className="overflow-hidden rounded-t-[8px] border border-slate-200 bg-white shadow-[0_-18px_42px_rgba(127,164,49,.18)]"
            role="dialog"
            aria-modal="false"
            aria-label={title}
          >
            <div className="flex items-start justify-between gap-3 border-b border-slate-200 bg-[var(--mitako-lime-soft)] px-4 py-3">
              <div className="min-w-0">
                <p className="text-sm font-black text-[var(--mitako-ink)]">{title}</p>
                <p className="mt-0.5 text-[11px] font-semibold leading-snug text-slate-600">{desc}</p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="touch-target flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[8px] border border-slate-200 bg-white text-[var(--mitako-ink)] hover:bg-[var(--mitako-lime)]"
                aria-label={t('input.closePicker')}
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <div className="relative">
              <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-5 bg-gradient-to-b from-white via-white/90 to-transparent backdrop-blur-[1px]" aria-hidden="true" />
              <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-6 bg-gradient-to-t from-white via-white/90 to-transparent backdrop-blur-[1px]" aria-hidden="true" />
              <div className="max-h-[44dvh] space-y-2 overflow-y-auto overscroll-contain p-3 console-scroll [scrollbar-gutter:stable]">
                {items.map(item => (
                  <button
                    key={item.productId || item.addressId}
                    type="button"
                    onClick={() => onSelect(item)}
                    className="w-full rounded-[8px] border border-slate-200 bg-white p-3 text-left shadow-[0_8px_20px_rgba(16,19,31,.05)] transition-[background-color,transform] hover:-translate-y-0.5 hover:bg-[var(--mitako-lime-soft)] active:translate-y-0"
                  >
                    {type === 'product' ? (
                      <div className="flex gap-3">
                        <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-[8px] border border-slate-200 bg-[var(--mitako-lime)]">
                          <ShoppingBag className="h-5 w-5 text-[var(--mitako-ink)]" aria-hidden="true" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-black leading-snug text-slate-900">{item.name}</p>
                          <p className="mt-1 font-mono text-[10px] font-semibold text-slate-500">{item.sku}</p>
                          <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] font-bold">
                            <span className="rounded-[8px] border border-slate-200 bg-white px-2 py-0.5 text-slate-600">{item.meta}</span>
                            <span className="rounded-[8px] border border-[var(--mitako-ink)] bg-[var(--mitako-lime)] px-2 py-0.5 text-[var(--mitako-ink)]">{item.status}</span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="flex gap-3">
                        <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-[8px] border border-slate-200 bg-[var(--mitako-lime)]">
                          <MapPin className="h-5 w-5 text-[var(--mitako-ink)]" aria-hidden="true" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-black text-slate-900">{item.label}</p>
                            <span className="rounded-[8px] border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-black text-slate-600">{item.tag}</span>
                          </div>
                          <p className="mt-1 text-xs font-semibold leading-snug text-slate-600">{item.maskedDetail}</p>
                          <p className="mt-1 font-mono text-[10px] font-semibold text-slate-500">手机号尾号 {item.phoneTail}</p>
                        </div>
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default function ChatInput({
  inputVal,
  setInputVal,
  handoffState,
  isAwaitingStream,
  onSend,
  onBackToAi,
  onReferenceOrder,
  hasOrder,
}) {
  const [toolsOpen, setToolsOpen] = useState(false);
  const [activeSheet, setActiveSheet] = useState(null);
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const photoInputRef = useRef(null);
  const cameraInputRef = useRef(null);

  const submit = () => {
    if ((!inputVal.trim() && pendingAttachments.length === 0) || isAwaitingStream) return;
    onSend(inputVal, { attachmentFiles: pendingAttachments });
    setInputVal('');
    setPendingAttachments([]);
    setToolsOpen(false);
    setActiveSheet(null);
  };

  const handleImagePick = (event, prefix) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setPendingAttachments([file]);
    setInputVal(inputVal.trim() ? inputVal : `${prefix}我想咨询这张图相关的问题：`);
    event.target.value = '';
    setToolsOpen(false);
    setActiveSheet(null);
  };

  const sendProduct = (product) => {
    if (isAwaitingStream) return;
    const message = `我想咨询这件商品：${product.name}。SKU：${product.sku}。${product.meta}。当前展示状态：${product.status}。${product.ask}。`;
    onSend(message);
    setInputVal('');
    setToolsOpen(false);
    setActiveSheet(null);
  };

  const sendAddress = (address) => {
    if (isAwaitingStream) return;
    const message = `我想核对这个收货地址是否会影响配送：${address.maskedDetail}，手机号尾号 ${address.phoneTail}。请帮我确认清关、派送或地址修改是否有影响。`;
    onSend(message);
    setInputVal('');
    setToolsOpen(false);
    setActiveSheet(null);
  };

  const openProducts = () => {
    setActiveSheet('product');
    setToolsOpen(false);
  };

  const openAddresses = () => {
    if (DEMO_ADDRESSES.length === 1) {
      sendAddress(DEMO_ADDRESSES[0]);
      return;
    }
    setActiveSheet('address');
    setToolsOpen(false);
  };

  const toolButtonClass = 'flex min-h-[58px] flex-col items-center justify-center gap-1 rounded-lg border border-slate-200 bg-white text-[10px] font-black text-slate-950 transition active:scale-[0.98] hover:bg-[var(--mitako-lime-soft)] focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)]';

  const isConnected = handoffState === 'connected';
  const isQueuing = handoffState === 'queuing';
  const placeholder = isConnected
    ? t('input.placeholderTransferred')
    : isQueuing
    ? t('input.placeholderQueuing')
    : t('input.placeholder');

  return (
    <div className="relative flex flex-shrink-0 flex-col gap-2 border-t border-slate-200 bg-[var(--surface-muted)] p-3 md:p-4">
      {(isConnected || isQueuing) && (
        <div className={`flex flex-col gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-black ${
          isConnected ? 'bg-[var(--mitako-lime)] text-slate-950' : 'bg-white text-slate-950'
        }`} data-testid="handoff-status-banner">
          <div className="flex items-center gap-2">
            <Headphones className={`w-4 h-4 flex-shrink-0 ${isQueuing ? 'animate-pulse text-amber-600' : ''}`} />
            <span className="text-pretty">{isConnected ? t('transfer.banner') : t('transfer.bannerQueuing')}</span>
          </div>
          {isConnected && (
            <button
              type="button"
              onClick={onBackToAi}
              className="self-start rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-black text-slate-950 hover:bg-slate-50"
            >
              {t('transfer.backToAi')}
            </button>
          )}
        </div>
      )}

      <input ref={photoInputRef} type="file" accept="image/*" className="hidden" onChange={e => handleImagePick(e, t('input.photoTemplate'))} />
      <input ref={cameraInputRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={e => handleImagePick(e, t('input.cameraTemplate'))} />

      {pendingAttachments.length > 0 && (
        <div className="flex items-center justify-between gap-2 rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700">
          <span className="min-w-0 truncate">{t('input.attachmentReady')}：{pendingAttachments[0].name}</span>
          <button
            type="button"
            onClick={() => setPendingAttachments([])}
            className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[8px] border border-slate-200 text-slate-500 hover:bg-slate-50"
            aria-label={t('input.removeAttachment')}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      )}

      <div className="flex items-stretch gap-2 flex-nowrap min-w-0">
        <input
          type="text"
          name="chat_message"
          autoComplete="off"
          spellCheck={false}
          aria-label={placeholder}
          value={inputVal}
          onChange={e => setInputVal(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit(); }}
          placeholder={placeholder}
          disabled={isAwaitingStream}
          className="min-h-[44px] min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-[15px] text-slate-800 outline-none transition-colors placeholder-slate-400 disabled:opacity-60 touch-manipulation focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)]"
        />
        <button
          type="button"
          data-testid="chat-tool-toggle"
          onClick={() => setToolsOpen(v => !v)}
          disabled={isAwaitingStream}
          aria-label={t('input.openTools')}
          aria-expanded={toolsOpen}
          className={`touch-target flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-lg border border-slate-200 text-slate-950 transition-colors disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)] ${
            toolsOpen ? 'bg-[var(--mitako-lime)]' : 'bg-white hover:bg-[var(--mitako-lime)]'
          }`}
        >
          <Plus className={`w-5 h-5 transition-transform duration-200 ${toolsOpen ? 'rotate-45' : ''}`} aria-hidden="true" />
        </button>
        {(inputVal.trim() || pendingAttachments.length > 0) && (
          <button
            type="button"
            onClick={submit}
            disabled={isAwaitingStream}
            aria-label={t('input.send')}
            className="touch-target flex h-11 min-w-[44px] flex-shrink-0 items-center justify-center gap-1 rounded-lg border border-slate-200 bg-[var(--mitako-lime)] px-3 text-sm font-black text-slate-950 shadow-[0_10px_24px_rgba(127,164,49,.14)] transition-[transform,background-color] active:translate-x-[1px] active:translate-y-[1px] active:shadow-none disabled:bg-slate-200 disabled:text-slate-400 focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)]"
          >
            <span className="hidden @[360px]/chat:inline">{t('input.send')}</span>
            <Send className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {toolsOpen && !isAwaitingStream && (
          <motion.div
            initial={{ height: 0, opacity: 0, y: 8 }}
            animate={{ height: 'auto', opacity: 1, y: 0 }}
            exit={{ height: 0, opacity: 0, y: 8 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className={`grid ${hasOrder ? 'grid-cols-5' : 'grid-cols-4'} gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-[0_10px_24px_rgba(127,164,49,.12)]`}>
          <button type="button" data-testid="chat-tool-browse" onClick={openProducts} className={`${toolButtonClass} bg-[var(--mitako-lime-soft)]`}>
            <ShoppingBag className="h-4 w-4" aria-hidden="true" />
            {t('input.toolBrowse')}
          </button>
          {hasOrder && (
            <button type="button" data-testid="chat-tool-order" onClick={() => { onReferenceOrder?.(); setToolsOpen(false); }} className={toolButtonClass}>
              <Package className="h-4 w-4" aria-hidden="true" />
              {t('input.toolOrder')}
            </button>
          )}
          <button type="button" data-testid="chat-tool-photo" onClick={() => photoInputRef.current?.click()} className={toolButtonClass}>
            <Image className="h-4 w-4" aria-hidden="true" />
            {t('input.toolPhoto')}
          </button>
          <button type="button" data-testid="chat-tool-camera" onClick={() => cameraInputRef.current?.click()} className={toolButtonClass}>
            <Camera className="h-4 w-4" aria-hidden="true" />
            {t('input.toolCamera')}
          </button>
          <button type="button" data-testid="chat-tool-address" onClick={openAddresses} className={toolButtonClass}>
            <MapPin className="h-4 w-4" aria-hidden="true" />
            {t('input.toolAddress')}
          </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <ToolPickerSheet
        open={activeSheet === 'product'}
        type="product"
        title={t('input.productPickerTitle')}
        desc={t('input.productPickerDesc')}
        items={DEMO_PRODUCTS}
        onClose={() => setActiveSheet(null)}
        onSelect={sendProduct}
      />
      <ToolPickerSheet
        open={activeSheet === 'address'}
        type="address"
        title={t('input.addressPickerTitle')}
        desc={t('input.addressPickerDesc')}
        items={DEMO_ADDRESSES}
        onClose={() => setActiveSheet(null)}
        onSelect={sendAddress}
      />
    </div>
  );
}
