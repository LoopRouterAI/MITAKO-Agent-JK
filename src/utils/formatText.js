import { MEME_MAP } from '../constants/memeMap.js';

/** 格式化 LLM 文本：高亮词 + @引用订单 + 加粗 + meme 标签 */
export function formatText(text, variant = 'default') {
  if (!text) return '';
  let formatted = text.replace(/\n/g, '<br>');

  formatted = formatted.replace(/\[@引用订单\s+([^\]]+)\]/g, (_m, orderId) => {
    const chipClass = variant === 'user'
      ? 'px-1.5 py-0.5 mx-0.5 rounded-md font-bold text-white bg-white/20 border border-white/30 inline-block'
      : 'px-1.5 py-0.5 mx-0.5 rounded-md font-bold text-[var(--mitako-orange)] bg-[var(--mitako-orange)]/10 border border-[var(--mitako-orange)]/25 inline-block';
    return `<span class="${chipClass}">@${orderId.trim()}</span>`;
  });

  formatted = formatted.replace(/\*\*([^*\n]+)\*\*/g, (_m, word) =>
    `<strong class="font-bold">${word}</strong>`
  );

  const hashClass = variant === 'user'
    ? 'px-1.5 py-0.5 mx-0.5 rounded-md font-semibold text-white bg-white/15 border border-white/25 inline-block'
    : 'px-1.5 py-0.5 mx-0.5 rounded-md font-semibold text-[var(--mitako-purple)] bg-[#7B61FF]/8 border border-[#7B61FF]/15 inline-block';

  formatted = formatted.replace(/#([^#\n\r]+)#/g, (_m, word) =>
    `<span class="${hashClass}">${word}</span>`
  );
  formatted = formatted.replace(/<meme:\s*(\w+)>/g, (_m, tag) => {
    const mapped = MEME_MAP[tag.toLowerCase()];
    if (mapped) {
      return `<span class="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-md border ml-1.5 ${mapped.color} select-none">${mapped.emoji}</span>`;
    }
    return `<span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-md border ml-1.5 text-slate-500 bg-slate-100 select-none">[${tag}]</span>`;
  });
  return formatted.replace(/<action:\s*\w+>/g, '');
}

const ADVENTURE_CHIP = {
  v: 'text-violet-800 bg-violet-100 border-violet-200',
  r: 'text-rose-800 bg-rose-100 border-rose-200',
  c: 'text-cyan-800 bg-cyan-100 border-cyan-200',
  g: 'text-emerald-800 bg-emerald-100 border-emerald-200',
  a: 'text-amber-900 bg-amber-100 border-amber-200',
  default: 'text-fuchsia-800 bg-fuchsia-50 border-fuchsia-200',
};

const CHOICE_GRADIENTS = [
  'from-violet-500 to-indigo-500',
  'from-fuchsia-500 to-rose-500',
  'from-cyan-500 to-teal-500',
  'from-amber-500 to-orange-500',
  'from-emerald-500 to-green-600',
  'from-purple-500 to-pink-500',
];

/** 冒险选项按钮渐变色（按序号循环） */
export function adventureChoiceGradient(index) {
  return CHOICE_GRADIENTS[(index - 1) % CHOICE_GRADIENTS.length];
}

/** 选项文案清洗 — 去掉 #g:词# 等后端标记 */
export function cleanAdventureChoiceLabel(label) {
  if (!label) return '';
  return label
    .replace(/#([vrcga]):([^#\n\r]+)#/g, '$2')
    .replace(/#([^#\n\r]+)#/g, '$1')
    .replace(/<[^>]+>/g, '')
    .trim();
}

/** 压缩冒险正文空行 — 避免 \n\n 渲染成大片留白 */
function normalizeAdventureWhitespace(text) {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\n\n/g, '\n')
    .trim();
}

/** 清洗 LLM 泄漏的 markup — 前后端均应调用 */
export function sanitizeAdventureDisplayText(text) {
  if (!text) return '';
  let s = text;
  s = s.replace(/^>\s*(.+?)\s*>\/SAY>>\s*$/gim, '<say role="agent" name="">$1</say>');
  s = s.replace(/>\s*\/SAY>>/gi, '');
  s = s.replace(/^>\s*([^>\n/]+?)\s*>$/gm, '>>$1<<');
  s = s.replace(/<>\s*\/SAY>>/gi, '');
  s = s.replace(/<\/SAY>>/gi, '');
  s = s.replace(/<<SAY:[^>]*>>/gi, '');
  s = s.replace(/<<SCENE>>|<\/SCENE>>|<<NARR>>|<\/NARR>>|<<SEP>>/gi, '');
  s = s.replace(/<>\s*([^<>\n]+?)\s*<>/g, '>>$1<<');
  s = s.replace(/^<>\s*/gm, '');
  s = s.replace(/\s*<>$/gm, '');
  s = s.replace(/^<>\s*$/gm, '');
  s = s.replace(/——\s*<\s*$/gm, '——');
  s = s.replace(/(?<![<])<\s*$/gm, '');
  s = s.replace(/<inner>[\s\S]*?<\/inner>/gi, '');
  s = s.replace(/<illust:[^>]*\/?>/gi, '');
  return s.trim();
}

/** 冒险模式富文本 — 场景/分隔/对话/旁白/多色高亮/emote */
export function formatAdventureText(text) {
  if (!text) return '';
  let body = normalizeAdventureWhitespace(
    sanitizeAdventureDisplayText(text)
      .replace(/^\s*\[\d+\]\s*.+$/gm, '')
      .replace(/<share:[^>]+>/gi, '')
  );

  // <say role="agent" name="红玉">台词</say> — 对白块（须在换 br 前）
  body = body.replace(
    /<say\s+role="([^"]+)"\s+name="([^"]*)">([\s\S]*?)<\/say>/gi,
    (_m, role, name, line) => `<<SAY:${role}:${name}>>${line.trim()}<</SAY>>`,
  );

  // >>场景标题<< — 须在换 br 前处理
  body = body.replace(/>>\s*([^<\n]+?)\s*<</g, (_m, title) =>
    `<<SCENE>>${title.trim()}<</SCENE>>`
  );

  // --- 装饰分隔线（独立一行）
  body = body.replace(/^---$/gm, '<<SEP>>');

  // 【旁白/系统】— 标记为块级，稍后替换 HTML
  body = body.replace(/【([^】\n]+)】/g, (_m, inner) =>
    `<<NARR>>${inner.trim()}<</NARR>>`
  );

  body = body.replace(/\n/g, '<br>');
  body = body.replace(/(?:<br>\s*){2,}/g, '<br>');

  body = body.replace(/<<SCENE>>([^<]+)<\/SCENE>>/g, (_m, title) =>
    `<div class="relative overflow-hidden rounded-xl my-2 border border-violet-200/80">
      <div class="absolute inset-0 bg-gradient-to-r from-violet-600/15 via-fuchsia-500/10 to-amber-400/15"></div>
      <div class="relative px-3 py-2.5 flex items-center gap-2">
        <span class="w-1.5 h-6 rounded-full bg-gradient-to-b from-violet-500 to-fuchsia-500"></span>
        <span class="text-[13px] font-bold tracking-wide bg-gradient-to-r from-violet-700 via-fuchsia-600 to-orange-500 bg-clip-text text-transparent">${title}</span>
      </div>
    </div>`
  );

  body = body.replace(/<<SEP>>/g,
    '<div class="my-2 flex items-center gap-2" aria-hidden="true"><span class="h-px flex-1 bg-gradient-to-r from-transparent via-violet-300 to-transparent"></span><span class="text-[10px] text-violet-400">✦</span><span class="h-px flex-1 bg-gradient-to-r from-transparent via-amber-300 to-transparent"></span></div>'
  );

  body = body.replace(/<<NARR>>([^<]+)<\/NARR>>/g, (_m, inner) =>
    `<div class="my-2 rounded-xl border border-dashed border-indigo-200/90 bg-indigo-50/70 px-3 py-2.5">
      <p class="text-[10px] font-bold uppercase tracking-wider text-indigo-500 mb-1">旁白</p>
      <p class="text-[12px] leading-relaxed text-indigo-950">${inner}</p>
    </div>`
  );

  body = body.replace(/<<SAY:([^:]+):([^>]*)>>([^<]+)<\/SAY>>/g, (_m, role, name, line) => {
    const who = name || (role === 'agent' ? '伙伴' : role === 'user' ? '主人' : '角色');
    const tone = role === 'agent'
      ? 'border-rose-300 bg-rose-50/80 text-rose-950'
      : role === 'user'
        ? 'border-violet-300 bg-violet-50/80 text-violet-950'
        : 'border-slate-300 bg-slate-50/80 text-slate-900';
    return `<div class="my-2 rounded-xl border-l-4 ${tone} px-3 py-2">
      <p class="text-[10px] font-bold opacity-70 mb-0.5">${who}</p>
      <p class="text-[13px] leading-relaxed font-medium">${line}</p>
    </div>`;
  });

  // 「对话」— 兼容旧格式（须在 blockquote > 之前）
  body = body.replace(/「([^」\n]+)」/g, (_m, inner) =>
    `<span class="inline-block my-0.5 pl-2 border-l-2 border-rose-300 text-rose-900 font-medium">${inner}</span>`
  );

  // 禁止把已规范化的 >>场景<< 或 <say> 再当成 blockquote
  // > 引用 — 仅匹配非场景、非 say 的孤立行（LLM 遗留）
  body = body.replace(/(?:^|<br>)&gt;\s*([^<]+?)(?=<br>|$)/g, (full, inner, offset, str) => {
    const trimmed = inner.trim();
    if (trimmed.startsWith('&gt;') || trimmed.includes('SCENE') || trimmed.includes('SAY')) return full;
    if (/^&gt;[^<]+&lt;$/.test(trimmed)) return full;
    return `<blockquote class="my-1.5 pl-3 py-1 border-l-2 border-cyan-300 bg-cyan-50/60 rounded-r-lg text-cyan-950 italic text-[13px]">${trimmed}</blockquote>`;
  });

  // **加粗**（须在 *斜体* 之前）
  body = body.replace(/\*\*([^*\n]+)\*\*/g, (_m, word) =>
    `<strong class="font-bold text-slate-900">${word}</strong>`
  );

  // *斜体强调*
  body = body.replace(/\*([^*\n]+)\*/g, (_m, word) =>
    `<em class="italic text-fuchsia-700">${word}</em>`
  );

  // ~~删除线~~
  body = body.replace(/~~([^~\n]+)~~/g, (_m, word) =>
    `<del class="text-slate-400">${word}</del>`
  );

  // #v:词# / #r:词# 等多色高亮
  body = body.replace(/#([vrcga]):([^#\n\r]+)#/g, (_m, tone, word) => {
    const cls = ADVENTURE_CHIP[tone] || ADVENTURE_CHIP.default;
    return `<span class="px-1.5 py-0.5 mx-0.5 rounded-md font-semibold border inline-block ${cls}">${word}</span>`;
  });

  // #普通高亮# — 金色默认
  body = body.replace(/#([^#\n\r]+)#/g, (_m, word) =>
    `<span class="px-1.5 py-0.5 mx-0.5 rounded-md font-semibold text-amber-900 bg-gradient-to-r from-amber-100 to-orange-50 border border-amber-200 inline-block">${word}</span>`
  );

  // <emote:sparkle> 等
  body = body.replace(/<emote:\s*(\w+)>/gi, (_m, tag) => {
    const mapped = MEME_MAP[tag.toLowerCase()];
    if (mapped) {
      return `<span class="inline-flex items-center text-xs font-semibold px-2 py-0.5 rounded-full border ml-1 ${mapped.color}">${mapped.emoji}</span>`;
    }
    return `<span class="inline-flex px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 text-xs ml-1">[${tag}]</span>`;
  });

  // 兜底：剥掉任何仍残留的尖括号 markup
  body = body.replace(/<(?!\/?(?:br|strong|em|del|span|div|blockquote|p)\b)[^>]+>/gi, '');

  return body.replace(/<action:\s*\w+>/gi, '');
}

/** 流式打字机预览 — 轻量转义，避免半截标签导致富文本抖动 */
export function formatAdventureStreamPreview(text) {
  if (!text) return '';
  let safe = normalizeAdventureWhitespace(stripAdventureChoiceLines(sanitizeAdventureDisplayText(text)));
  safe = safe.replace(/<inner>[\s\S]*?<\/inner>/gi, '');
  safe = safe.replace(/<illust:[^>]*\/?>/gi, '');
  // 去掉未闭合的标签片段，减少闪烁
  safe = safe.replace(/(\[\d+\][^\n]*)$/, '');
  safe = safe.replace(/(>>[^<\n]*)$/, '');
  safe = safe.replace(/(#[^#\n]*)$/, '');
  safe = safe.replace(/(\*\*[^*\n]*)$/, '');
  safe = safe.replace(/(<[^>\n]*)$/, '');
  const escaped = safe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  return escaped.replace(/\n/g, '<br>').replace(/(?:<br>\s*){2,}/g, '<br>');
}

/** 从冒险正文中剥离选项行，供按钮区单独渲染 */
export function stripAdventureChoiceLines(text) {
  if (!text) return '';
  return text.replace(/^\s*\[\d+\]\s*.+$/gm, '').trim();
}
