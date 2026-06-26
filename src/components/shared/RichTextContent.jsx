import React from 'react';
import { formatText, formatAdventureText, formatAdventureStreamPreview } from '../../utils/formatText.js';

/** 双端共享富文本 — #词块# / @引用订单 / **加粗** / meme / action 剥离 */
export default function RichTextContent({ text, className = '', variant = 'default' }) {
  if (!text) return null;
  const html = variant === 'adventureStream'
    ? formatAdventureStreamPreview(text)
    : (variant === 'adventure' || variant === 'adventureUser')
      ? formatAdventureText(text)
      : formatText(text, variant);
  return (
    <span
      className={className}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
