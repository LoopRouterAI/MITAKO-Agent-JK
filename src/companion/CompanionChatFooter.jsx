import React from 'react';



import { AtSign, Plus, Send } from 'lucide-react';



import { adventureChoiceGradient, cleanAdventureChoiceLabel } from '../utils/formatText.js';



import CompanionSlashMenu from './CompanionSlashMenu.jsx';

import CompanionMentionMenu from './CompanionMentionMenu.jsx';



import t from '../i18n/index.js';



/** Companion 输入区 — + 菜单、/ 指令、@ 圈人、冒险选项 */

export default function CompanionChatFooter({

  input,

  setInput,

  streaming,

  onSend,

  onOpenOrderPicker,

  onOpenActionSheet,

  hasOrders,

  isCsMode,

  adventureActive,

  lastChoices,

  onPickChoice,

  persona,

  adventureMessages,

}) {

  const submit = (e) => {

    e.preventDefault();

    if (!input.trim() || streaming) return;

    onSend(input);

    setInput('');

  };



  const placeholder = adventureActive

    ? t('companion.adventureInputPlaceholder')

    : isCsMode

      ? t('companion.inputCsPlaceholder')

      : t('companion.inputPlaceholder');



  const showChoices = adventureActive && !streaming && lastChoices?.length > 0;

  const showAdventureStatus = adventureActive && streaming;



  return (

    <footer className={`border-t flex-shrink-0 ${adventureActive ? 'border-violet-100 bg-gradient-to-r from-violet-50/50 to-amber-50/30' : 'border-rose-100 bg-white'}`}>

      <CompanionSlashMenu

        input={input}

        adventureActive={adventureActive}

        hasOrders={hasOrders}

        onPick={(cmd) => setInput(cmd)}

      />

      <CompanionMentionMenu

        input={input}

        setInput={setInput}

        adventureActive={adventureActive}

        persona={persona}

        adventureMessages={adventureMessages}

      />

      {showAdventureStatus && (

        <div className="px-3 pt-2.5 pb-2 border-b border-violet-100/60">

          <div className="flex items-center gap-2.5 rounded-xl bg-violet-50/90 border border-violet-100 px-3 py-2.5">

            <span className="relative flex h-2.5 w-2.5">

              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400 opacity-60" />

              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-violet-500" />

            </span>

            <p className="text-[11px] font-semibold text-violet-700">{t('companion.adventureTyping')}</p>

          </div>

        </div>

      )}



      {showChoices && (

        <div className="px-3 pt-2.5 pb-2 border-b border-violet-100/60">

          <p className="text-[10px] font-bold text-violet-600 mb-2">{t('companion.adventureChoiceHint')}</p>

          <div className="flex flex-col gap-2 max-h-[min(36dvh,220px)] touch-scroll">

            {lastChoices.map(c => (

              <button

                key={`footer_${c.id}`}

                type="button"

                onClick={() => onPickChoice?.(c)}

                className={`w-full text-left flex items-start gap-2.5 px-3 py-3 rounded-xl text-white bg-gradient-to-r ${adventureChoiceGradient(c.id)} shadow-sm touch-target active:scale-[0.98] transition-transform`}

              >

                <span className="flex-shrink-0 w-7 h-7 rounded-full bg-white/25 flex items-center justify-center text-[12px] font-black">

                  {c.id}

                </span>

                <span className="flex-1 min-w-0 text-[12px] font-semibold leading-snug whitespace-normal break-words">

                  {cleanAdventureChoiceLabel(c.label)}

                </span>

              </button>

            ))}

          </div>

        </div>

      )}



      <form onSubmit={submit} className="p-3 flex gap-2 items-stretch">

        <button

          type="button"

          onClick={onOpenActionSheet}

          aria-label={t('companion.actionSheetTitle')}

          className={`touch-target flex-shrink-0 w-11 h-11 border rounded-xl flex items-center justify-center ${

            adventureActive

              ? 'text-violet-600 bg-violet-50 border-violet-100 hover:bg-violet-100'

              : 'text-slate-500 bg-slate-50 border-slate-100 hover:bg-slate-100'

          }`}

        >

          <Plus className="w-5 h-5" />

        </button>

        {hasOrders && !adventureActive && (

          <button

            type="button"

            onClick={onOpenOrderPicker}

            aria-label={t('companion.refOrderBtn')}

            title={t('companion.refOrderHint')}

            className="touch-target flex-shrink-0 w-11 h-11 text-rose-500 bg-rose-50 border border-rose-100 hover:bg-rose-100 rounded-xl flex items-center justify-center"

          >

            <AtSign className="w-4 h-4" />

          </button>

        )}

        <input

          value={input}

          onChange={e => setInput(e.target.value)}

          placeholder={placeholder}

          disabled={streaming}

          aria-label={t('companion.inputAria')}

          className={`flex-1 min-h-[44px] rounded-xl border px-4 py-3 text-sm focus:outline-none focus:ring-2 disabled:opacity-60 ${

            adventureActive

              ? 'border-violet-100 bg-white/80 focus:ring-violet-200'

              : 'border-rose-100 bg-rose-50/50 focus:ring-rose-200'

          }`}

        />

        <button

          type="submit"

          disabled={streaming || !input.trim()}

          className="rounded-xl bg-[var(--mitako-lime)] text-slate-900 px-4 flex items-center justify-center shadow-[var(--shadow-lime)] disabled:opacity-50 touch-target min-w-[44px]"

        >

          <Send className="w-4 h-4" />

        </button>

      </form>

    </footer>

  );

}


