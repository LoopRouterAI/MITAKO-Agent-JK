import t from '../i18n/index.js';

/** 对话发言者类型与视觉配置 */
export const SPEAKER = {
  AI: 'ai',
  HUMAN: 'human',
};

export const AI_AGENT = {
  speaker: SPEAKER.AI,
  avatar: '/xiaojiao_avatar.png',
  name: () => t('agent.name'),
  badge: 'AI',
  badgeClass: 'bg-[var(--mitako-purple)] text-white border-[#7B61FF]/30',
  labelClass: 'text-[var(--mitako-purple)]',
  bubbleClass:
    'rounded-2xl rounded-tl-md bg-gradient-to-br from-white via-[#7B61FF]/[0.06] to-[#C8FF1A]/[0.08] border border-[#7B61FF]/15 text-slate-800 shadow-[0_4px_20px_rgba(123,97,255,0.08)]',
  ringClass: 'ring-2 ring-[#7B61FF]/20',
};

export const HUMAN_AGENT = {
  speaker: SPEAKER.HUMAN,
  avatar: null, // 使用 Lucide 图标占位
  name: () => t('speakers.humanName'),
  badge: t('speakers.humanBadge'),
  badgeClass: 'bg-teal-600 text-white border-teal-500/30',
  labelClass: 'text-teal-700',
  bubbleClass:
    'rounded-2xl rounded-tl-md bg-gradient-to-br from-teal-50 via-white to-emerald-50/80 border border-teal-200/80 text-slate-800 shadow-[0_4px_18px_rgba(20,184,166,0.12)]',
  ringClass: 'ring-2 ring-teal-400/25',
};

/** 构建 left 侧消息 user 元数据 */
export function buildLeftUserMeta(speaker = SPEAKER.AI, extra = {}) {
  const cfg = speaker === SPEAKER.HUMAN ? HUMAN_AGENT : AI_AGENT;
  return {
    avatar: cfg.avatar,
    name: extra.name || cfg.name(),
    speaker: cfg.speaker,
    badge: extra.badge || cfg.badge,
    agentId: extra.agentId || extra.agent_id || null,
  };
}

export function resolveSpeakerStyle(speaker) {
  return speaker === SPEAKER.HUMAN ? HUMAN_AGENT : AI_AGENT;
}
