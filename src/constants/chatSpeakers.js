import t from '../i18n/index.js';
import { MITAKO_AGENT_AVATAR } from './memeMap.js';

/** 对话发言者类型与视觉配置 */
export const SPEAKER = {
  AI: 'ai',
  HUMAN: 'human',
};

export const AI_AGENT = {
  speaker: SPEAKER.AI,
  avatar: MITAKO_AGENT_AVATAR,
  name: () => t('agent.name'),
  badge: 'AI',
  badgeClass: 'bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-[var(--mitako-ink)]',
  labelClass: 'text-[var(--mitako-ink)]',
  bubbleClass:
    'rounded-[8px] bg-white border-2 border-[var(--mitako-ink)] text-[var(--mitako-ink)] shadow-[4px_4px_0_rgba(17,20,17,0.92)]',
  ringClass: 'ring-2 ring-[var(--mitako-lime)]',
};

export const HUMAN_AGENT = {
  speaker: SPEAKER.HUMAN,
  avatar: null, // 使用 Lucide 图标占位
  name: () => t('speakers.humanName'),
  badge: t('speakers.humanBadge'),
  badgeClass: 'bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-[var(--mitako-ink)]',
  labelClass: 'text-[var(--mitako-ink)]',
  bubbleClass:
    'rounded-[8px] bg-[var(--mitako-lime)] border-2 border-[var(--mitako-ink)] text-[var(--mitako-ink)] shadow-[4px_4px_0_rgba(17,20,17,0.92)]',
  ringClass: 'ring-2 ring-[var(--mitako-lime)]',
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
