import React from 'react';

import { COMPANION_CARD_RENDERERS } from '../components/cards/companionOpenUILibrary.jsx';

import RichTextContent from '../components/shared/RichTextContent.jsx';

import { stripAdventureChoiceLines } from '../utils/formatText.js';

import InnerThoughtBlock from './InnerThoughtBlock.jsx';

import AdventureIllustCard from './AdventureIllustCard.jsx';

import t from '../i18n/index.js';



const WELCOME_BY_PERSONALITY = {

  gentle: 'welcomeGentle',

  genki: 'welcomeGenki',

  cool: 'welcomeCool',

  onee: 'welcomeOnee',

};



/** Companion 消息流 — 冒险流式打字机 + 富文本（选项仅在底部栏） */

export default function CompanionMessageList({

  messages,

  streaming,

  persona,

  cardCallbacks,

  scrollRef,

  adventureActive,

  onOpenContextModal,

}) {

  const welcomeKey = WELCOME_BY_PERSONALITY[persona?.personality] || 'welcomeGentle';

  const showWelcome = messages.length === 0 && !streaming && persona?.agent_name && !adventureActive;

  const hasStreamingBubble = messages.some(m => m.streaming);



  return (

    <main

      ref={scrollRef}

      className={`flex-1 min-h-0 overflow-y-auto overflow-x-hidden touch-scroll overscroll-y-contain touch-pan-y p-3 space-y-3 relative z-0 ${

        adventureActive

          ? 'bg-gradient-to-b from-indigo-50/40 via-violet-50/30 to-amber-50/20'

          : 'bg-gradient-to-b from-white to-rose-50/30'

      }`}

    >

      {adventureActive && (

        <div className="rounded-xl border border-violet-200/80 bg-gradient-to-r from-violet-100/80 via-fuchsia-50/80 to-amber-50/80 px-3 py-2 text-[11px] text-violet-900 leading-relaxed shadow-sm flex items-start justify-between gap-2">

          <div className="min-w-0">

            <span className="font-bold text-fuchsia-700">{t('companion.adventureBannerTitle')}</span>

            {' · '}

            {t('companion.adventureBannerBody')}

          </div>

          <button

            type="button"

            onClick={onOpenContextModal}

            className="shrink-0 text-[10px] font-bold px-2 py-1 rounded-full bg-white/80 border border-violet-200 text-violet-700 hover:bg-violet-50 touch-target"

          >

            {t('companion.adventureBannerManage')}

          </button>

        </div>

      )}

      {showWelcome && (

        <div className="max-w-[92%] mr-auto rounded-2xl px-4 py-3 text-sm leading-relaxed bg-white/90 border border-rose-100 shadow-sm">

          <p className="text-[11px] font-bold text-rose-400 mb-1">{persona.agent_name}</p>

          <p className="text-slate-700">

            {t(`companion.${welcomeKey}`, 'zh-CN', {

              title: persona.user_title || '主人',

              name: persona.agent_name,

            })}

          </p>

        </div>

      )}

      {messages.map(m => {

        if (m.role === 'user') {

          const text = typeof m.content === 'string' ? m.content : m.content?.text;

          const isAdv = m.mode === 'adventure' || adventureActive;

          if (isAdv && m.choicePick) {

            const safeText = text || '';

            const shortLabel = safeText.length > 28 ? `${safeText.slice(0, 28)}…` : safeText;

            return (

              <div key={m.id} className="flex justify-end">

                <div className="max-w-[90%] rounded-full px-3.5 py-2 text-[11px] font-bold bg-violet-100/90 text-violet-800 border border-violet-200/70 shadow-sm">

                  {t('companion.adventureChoicePicked', 'zh-CN', { label: shortLabel })}

                </div>

              </div>

            );

          }

          return (

            <div

              key={m.id}

              className={`max-w-[88%] ml-auto rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-md text-white ${

                isAdv

                  ? 'bg-gradient-to-br from-violet-600 via-fuchsia-600 to-rose-500'

                  : 'bg-gradient-to-br from-[var(--mitako-purple)] to-fuchsia-500'

              }`}

            >

              <RichTextContent text={text} variant={isAdv ? 'adventureUser' : 'user'} />

            </div>

          );

        }



        if (m.type === 'custom') {

          const Card = COMPANION_CARD_RENDERERS[m.content?.cardType];

          if (!Card) return null;

          const extra = {};

          if (m.content.cardType === 'companion_watch_form') {

            extra.onSubmit = cardCallbacks?.onWatchSubmit;

          }

          if (m.content.cardType === 'companion_product_picker') {

            extra.onSearch = cardCallbacks?.onProductSearch;

            extra.onAddWishlist = cardCallbacks?.onAddWishlist;

          }

          return (

            <div key={m.id} className="max-w-[95%] mr-auto animate-fade-up">

              <Card.component props={{ ...m.content.cardData, ...extra }} />

            </div>

          );

        }



        const text = typeof m.content === 'string' ? m.content : m.content?.text;

        const isAdvMsg = m.mode === 'adventure' || adventureActive;

        const isStreamingMsg = Boolean(m.streaming);

        if (m.systemNotice) {

          return (

            <div key={m.id} className="max-w-[92%] mx-auto">

              <div className="rounded-xl px-3 py-2 text-[11px] text-center text-violet-700 bg-violet-50/90 border border-violet-100">

                {text}

              </div>

            </div>

          );

        }

        const displayText = isAdvMsg ? stripAdventureChoiceLines(text) : text;

        const richVariant = isStreamingMsg ? 'adventureStream' : (isAdvMsg ? 'adventure' : 'default');



        return (

          <div key={m.id} className="max-w-[92%] mr-auto">

            <div

              className={`rounded-2xl px-3.5 py-3 text-sm leading-relaxed shadow-sm ${

                isAdvMsg

                  ? 'bg-gradient-to-br from-white via-violet-50/50 to-amber-50/40 border border-violet-100/80 text-slate-700'

                  : 'bg-white border border-rose-100 text-slate-700'

              } ${isStreamingMsg ? 'ring-2 ring-violet-200/60' : ''}`}

            >

              {isStreamingMsg && !displayText?.trim() ? (

                <p className="text-xs text-violet-500/90 animate-pulse leading-relaxed">

                  {t('companion.adventureTyping')}

                </p>

              ) : (

                <RichTextContent text={displayText} variant={richVariant} />

              )}

              {isStreamingMsg && displayText?.trim() && (

                <span className="inline-block w-2 h-4 ml-0.5 align-middle bg-violet-500 animate-pulse rounded-sm" aria-hidden="true" />

              )}

              {!isStreamingMsg && m.inner && (

                <InnerThoughtBlock inner={m.inner} />

              )}

              {!isStreamingMsg && m.illust && (

                <AdventureIllustCard illust={m.illust} />

              )}

            </div>

          </div>

        );

      })}

      {streaming && !hasStreamingBubble && (

        <p className={`text-xs animate-pulse px-1 ${adventureActive ? 'text-violet-500' : 'text-rose-400'}`}>

          {adventureActive ? t('companion.adventureTyping') : t('companion.typing')}

        </p>

      )}

    </main>

  );

}


