import React, { useState } from 'react';
import { Sparkles } from 'lucide-react';
import t from '../i18n/index.js';

const PERSONALITIES = [
  { id: 'gentle', labelKey: 'personalityGentle' },
  { id: 'genki', labelKey: 'personalityGenki' },
  { id: 'cool', labelKey: 'personalityCool' },
  { id: 'onee', labelKey: 'personalityOnee' },
];

const RELATIONSHIPS = ['搭档', '恋人', '主仆', '师徒', '挚友', '守护者'];

/** 首次设定伙伴 — 名称/称谓/关系均会过审后注入 LLM */
export default function OnboardingFlow({ onComplete }) {
  const [agentName, setAgentName] = useState('');
  const [userTitle, setUserTitle] = useState('主人');
  const [relationship, setRelationship] = useState('搭档');
  const [customRel, setCustomRel] = useState('');
  const [phone, setPhone] = useState('');
  const [personality, setPersonality] = useState('gentle');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!agentName.trim() || agentName.trim().length < 2) {
      setError(t('companion.onboardingNameRequired'));
      return;
    }
    setLoading(true);
    setError('');
    const rel = (customRel.trim() || relationship).slice(0, 16);
    try {
      await onComplete({
        agent_name: agentName.trim(),
        user_title: userTitle.trim() || '主人',
        relationship: rel,
        phone: phone.trim(),
        personality,
        onboarded: true,
      });
    } catch (err) {
      setError(
        err.message === 'bad_word' || err.message?.includes('不当')
          ? t('companion.onboardingBadWord')
          : err.message?.includes('称谓')
            ? t('companion.onboardingTitleLen')
            : err.message?.includes('关系')
              ? t('companion.onboardingRelLen')
              : err.message || t('companion.onboardingNameLen'),
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={submit} className="w-full max-w-md mx-auto p-6 space-y-4 bg-white rounded-2xl border border-rose-100 shadow-sm">
      <div className="text-center mb-4">
        <div className="w-14 h-14 mx-auto mb-3 rounded-2xl bg-gradient-to-br from-rose-300 to-fuchsia-400 flex items-center justify-center">
          <Sparkles className="w-7 h-7 text-white" />
        </div>
        <h2 className="text-xl font-bold text-slate-800">{t('companion.onboardingTitle')}</h2>
        <p className="text-xs text-slate-400 mt-1">{t('companion.onboardingAuditHint')}</p>
      </div>
      <input
        placeholder={t('companion.agentName')}
        value={agentName}
        onChange={e => setAgentName(e.target.value.slice(0, 16))}
        maxLength={16}
        required
        className="w-full rounded-xl border border-rose-100 bg-rose-50/50 px-4 py-3 text-slate-800 placeholder:text-slate-400"
      />
      <input
        placeholder={t('companion.userTitle')}
        value={userTitle}
        onChange={e => setUserTitle(e.target.value.slice(0, 16))}
        maxLength={16}
        className="w-full rounded-xl border border-rose-100 bg-rose-50/50 px-4 py-3 text-slate-800 placeholder:text-slate-400"
      />
      <div>
        <p className="text-xs text-slate-500 mb-2">{t('companion.relationshipLabel')}</p>
        <div className="flex flex-wrap gap-2 mb-2">
          {RELATIONSHIPS.map(r => (
            <button
              key={r}
              type="button"
              onClick={() => { setRelationship(r); setCustomRel(''); }}
              className={`text-[11px] font-semibold px-3 py-1.5 rounded-full border ${
                relationship === r && !customRel
                  ? 'bg-violet-100 text-violet-800 border-violet-200'
                  : 'bg-white text-slate-600 border-rose-100'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
        <input
          placeholder={t('companion.relationshipCustom')}
          value={customRel}
          onChange={e => setCustomRel(e.target.value.slice(0, 16))}
          maxLength={16}
          className="w-full rounded-xl border border-rose-100 bg-rose-50/50 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400"
        />
      </div>
      <input
        placeholder={t('companion.phoneOptional')}
        value={phone}
        onChange={e => setPhone(e.target.value)}
        inputMode="tel"
        className="w-full rounded-xl border border-rose-100 bg-rose-50/50 px-4 py-3 text-slate-800 placeholder:text-slate-400"
      />
      <p className="text-xs text-slate-500">{t('companion.personality')}</p>
      <div className="grid grid-cols-2 gap-2">
        {PERSONALITIES.map(p => (
          <button
            key={p.id}
            type="button"
            onClick={() => setPersonality(p.id)}
            className={`rounded-xl py-2 text-sm font-bold border ${
              personality === p.id
                ? 'bg-[var(--mitako-lime)] text-slate-900 border-[var(--mitako-lime-deep)]'
                : 'border-rose-100 text-slate-600 bg-white'
            }`}
          >
            {t(`companion.${p.labelKey}`)}
          </button>
        ))}
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}
      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-xl bg-gradient-to-r from-rose-400 to-fuchsia-500 text-white font-bold py-3 shadow-md disabled:opacity-60"
      >
        {t('companion.startChat')}
      </button>
    </form>
  );
}
