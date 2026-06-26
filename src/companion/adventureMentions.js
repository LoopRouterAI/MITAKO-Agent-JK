/** GalGame / 文字冒险常用 / 指令 → LLM 结构化行动 */
export const GALGAME_SLASH_MAP = {
  '/观察': '【行动：环顾四周，描写环境细节与可疑之处】',
  '/调查': '【行动：仔细调查眼前最显眼的人或物】',
  '/威胁': '【行动：以威胁或压迫姿态面对当前局面】',
  '/沉默': '【行动：保持沉默，观察对方反应】',
  '/逃跑': '【行动：寻找脱身或躲藏路线】',
  '/等待': '【行动：按兵不动，等待局势变化】',
};

export function expandGalgameSlash(text) {
  const key = (text || '').trim();
  return GALGAME_SLASH_MAP[key] || text;
}

const SCENE_NPC_HINTS = ['盗宝团', '企业狗', '商贩', '守卫', '路人', '敌人', 'Boss'];

/** 从最近冒险消息提取可 @ 的角色名 */
export function collectMentionCandidates(persona, adventureMessages = []) {
  const agent = persona?.agent_name?.trim();
  const userTitle = persona?.user_title?.trim() || '主人';
  const names = new Set();
  if (agent) names.add(agent);
  if (userTitle) names.add(userTitle);

  for (let i = adventureMessages.length - 1; i >= 0 && names.size < 12; i -= 1) {
    const m = adventureMessages[i];
    if (m.role !== 'assistant') continue;
    (m.dialogues || []).forEach(d => {
      if (d.name) names.add(d.name);
    });
    const raw = typeof m.content === 'string' ? m.content : '';
    const sayMatches = raw.matchAll(/<say[^>]*name="([^"]+)"/gi);
    for (const sm of sayMatches) {
      if (sm[1]) names.add(sm[1].trim());
    }
    break;
  }

  SCENE_NPC_HINTS.forEach(n => names.add(n));
  return [...names].filter(Boolean).slice(0, 14);
}

/** 当前输入中 @ 后的过滤词 */
export function mentionFilterFromInput(input) {
  const m = (input || '').match(/@([^\s@]*)$/);
  return m ? m[1].toLowerCase() : null;
}

/** 是否应显示 @ 候选菜单 */
export function shouldShowMentionMenu(input, adventureActive) {
  return adventureActive && mentionFilterFromInput(input) !== null;
}

/** 将 @角色 转为 LLM 可理解的结构化用户输入 */
export function expandAdventureMentions(text, persona) {
  if (!text || !text.includes('@')) return text;
  const agent = persona?.agent_name || '伙伴';
  const userTitle = persona?.user_title || '主人';

  return text.replace(/@([^\s@，。！？,.!?]+)\s*/g, (_m, who) => {
    const target = who.trim();
    if (!target) return _m;
    if (target === agent || target === '伙伴') {
      return `【对 ${agent} 说】`;
    }
    if (target === userTitle || target === '主人' || target === '我') {
      return `【${agent} 对 ${userTitle} 说】`;
    }
    return `【对 ${target} 说】`;
  });
}

/** 插入 @名字 到输入框 */
export function insertMention(input, name) {
  const base = input || '';
  const at = base.lastIndexOf('@');
  if (at < 0) return `@${name} `;
  return `${base.slice(0, at)}@${name} `;
}
