import zhCN from './zh-CN.js';

const dictionaries = { 'zh-CN': zhCN };

/** 轻量 i18n：按 key 路径取文案；数组 key 返回整段数组供 Loading 轮播 */
export function t(key, locale = 'zh-CN', vars = {}) {
  const dict = dictionaries[locale] || zhCN;
  const value = key.split('.').reduce((obj, k) => (obj ? obj[k] : undefined), dict);
  if (Array.isArray(value)) return value;
  if (typeof value !== 'string') return key;
  return Object.entries(vars).reduce(
    (str, [k, v]) => str.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v)),
    value
  );
}

export default t;
