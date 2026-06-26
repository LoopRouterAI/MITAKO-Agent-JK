/** 冒险世界观 Loading 主题 — 文案与视觉随世界观变化 */

const DEFAULT = {
  id: 'fantasy',
  gradient: 'from-violet-600 via-fuchsia-500 to-amber-400',
  orb: 'bg-violet-400',
  ring: 'border-violet-300/60',
  lines: [
    '时空的褶皱正在为你展开……',
    '某股不明力量正在改写因果……',
    '伙伴已握住你的手——别松开。',
    '世界法则加载中，请屏息。',
  ],
};

const THEMES = [
  {
    id: 'cyber',
    match: /赛博|2077|cyber|夜之城|night city|第六街/i,
    gradient: 'from-fuchsia-600 via-cyan-500 to-yellow-400',
    orb: 'bg-cyan-400',
    ring: 'border-cyan-300/70',
    lines: [
      '霓虹在视网膜上燃烧——欢迎来到夜之城。',
      '荒坂塔的阴影正从数据海里浮起……',
      '义体在低鸣，你们被扔进了第六街。',
      '不明信号正在重写你们的身份芯片……',
    ],
  },
  {
    id: 'genshin',
    match: /原神|提瓦特|genshin|璃月|蒙德/i,
    gradient: 'from-sky-400 via-emerald-400 to-amber-300',
    orb: 'bg-sky-300',
    ring: 'border-sky-200/80',
    lines: [
      '元素力场在脚下汇聚……',
      '天空岛投下的光柱正在寻找旅者。',
      '风与岩的低语牵引你们坠入提瓦特。',
      '七神尚未察觉的穿越，正在发生。',
    ],
  },
  {
    id: 'sanguo',
    match: /三国|乱世|赤壁|蜀汉|曹魏/i,
    gradient: 'from-amber-600 via-rose-600 to-red-800',
    orb: 'bg-amber-400',
    ring: 'border-amber-200/70',
    lines: [
      '战鼓在远方擂响——乱世开门了。',
      '旌旗蔽日，你们被卷进历史的洪流。',
      '马蹄声由远及近，命运齿轮开始转动。',
      '天地变色，英雄与枭雄同在注视你们。',
    ],
  },
  {
    id: 'hp',
    match: /霍格沃茨|魔法|wizard|harry/i,
    gradient: 'from-indigo-700 via-purple-600 to-amber-500',
    orb: 'bg-indigo-300',
    ring: 'border-indigo-200/70',
    lines: [
      '猫头鹰掠过城堡尖顶……',
      '魔杖尖亮起微光，门钥匙已启动。',
      '分院帽在远处低语，新的章节开始了。',
      '九又四分之三的蒸汽正在呼唤你们。',
    ],
  },
];

export function resolveAdventureLoadingTheme(worldSetting = '') {
  const w = worldSetting || '';
  for (const t of THEMES) {
    if (t.match.test(w)) {
      return { ...DEFAULT, ...t, lines: t.lines };
    }
  }
  return DEFAULT;
}

export function loadingLineForPhase(theme, phase, tick = 0) {
  const lines = theme?.lines || DEFAULT.lines;
  const phaseBoost = {
    rift: 0,
    bible: 1,
    bible_done: 2,
    narrative: 3,
    ready: lines.length - 1,
  };
  const idx = (phaseBoost[phase] ?? tick) % lines.length;
  return lines[idx];
}
