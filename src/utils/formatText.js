import { MEME_MAP } from '../constants/memeMap.js';

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const chipBase = 'px-1.5 py-0.5 mx-0.5 rounded-[8px] font-semibold border inline-block';
const limeChip = `${chipBase} text-[var(--mitako-ink)] bg-[var(--mitako-lime)] border-[var(--mitako-ink)]`;
const whiteChip = `${chipBase} text-[var(--mitako-ink)] bg-white border-[var(--mitako-ink)]`;

function renderMemeTag(tag) {
  const meme = MEME_MAP[String(tag ?? '').trim().toLowerCase()];
  if (!meme?.src) return '';
  return `<img src="${escapeHtml(meme.src)}" alt="${escapeHtml(meme.alt || '')}" class="mitako-emote" loading="lazy" decoding="async">`;
}

/** 用户可见文本格式化：先转义，再插入受控白名单标签。 */
export function formatText(text, variant = 'default') {
  if (!text) return '';
  let formatted = escapeHtml(text).replace(/\n/g, '<br>');
  const chipClass = variant === 'user' ? whiteChip : limeChip;
  const chips = [];
  const makeChip = (label) => {
    const key = `%%MITAKOCHIP${chips.length}%%`;
    chips.push(`<span class="${chipClass}">${label}</span>`);
    return key;
  };

  formatted = formatted.replace(/\[@引用订单\s+([^\]]+)\]/g, (_m, orderId) => {
    return makeChip(`@${orderId.trim()}`);
  });

  formatted = formatted.replace(/订单\s*#\s*([A-Z0-9_-]{4,})/g, (_m, code) => {
    return makeChip(`订单 #${code}`);
  });

  formatted = formatted.replace(/\b([A-Z0-9_-]{4,})\s*订单/g, (_m, code) => {
    return makeChip(`${code}订单`);
  });

  formatted = formatted.replace(/#([^#\n\r]{1,40})#/g, '$1');

  formatted = formatted.replace(/\b([A-Z]{1,6}[_-][A-Z0-9_-]{6,})\b/g, (_m, code) => {
    return makeChip(code);
  });

  formatted = formatted.replace(/\*\*([^*\n]+)\*\*/g, (_m, word) =>
    `<strong class="font-bold text-[var(--mitako-ink)]">${word}</strong>`
  );

  formatted = formatted.replace(/&lt;(?:meme|emote):\s*([a-z0-9_-]+)&gt;/gi, (_m, tag) => renderMemeTag(tag));

  formatted = formatted.replace(/&lt;action:\s*\w+&gt;/gi, '');
  return formatted.replace(/%%MITAKOCHIP(\d+)%%/g, (_m, idx) => chips[Number(idx)] || '');
}
