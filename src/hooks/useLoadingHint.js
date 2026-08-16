import { useEffect, useState } from 'react';
import t from '../i18n/index.js';

/** 二次元友好 Loading 文案轮播 — 按 Agent 步骤切换语料池 */
export function useLoadingHint(step, active) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => {
      setIndex(i => i + 1);
    }, 2400);
    return () => clearInterval(id);
  }, [active, step]);

  useEffect(() => {
    setIndex(0);
  }, [step]);

  const pool = t(`loading.${step}`, 'zh-CN');
  const hints = Array.isArray(pool) ? pool : [pool];
  return hints[index % hints.length];
}
