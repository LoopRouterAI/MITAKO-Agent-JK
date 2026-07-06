const u = (...codes) => String.fromCharCode(...codes);

const PUBLIC_TEXT_REPLACEMENTS = [
  [u(0x603b, 0x90e8, 0x5ba2, 0x8bc9, 0x4e3b, 0x7ba1), '升级处理专员'],
  [u(0x603b, 0x90e8, 0x4e3b, 0x7ba1), '升级处理专员'],
  [u(0x603b, 0x90e8, 0x5ba2, 0x670d), '升级处理'],
  [u(0x603b, 0x90e8), '服务中心'],
  [u(0x79fb, 0x4ea4, 0x6458, 0x8981), '服务记录'],
  [u(0x79fb, 0x4ea4, 0x7b80, 0x62a5), '服务记录'],
  [u(0x7528, 0x6237, 0x771f, 0x5b9e, 0x610f, 0x56fe), '处理判断'],
  [u(0x771f, 0x5b9e, 0x610f, 0x56fe), '问题概况'],
  [u(0x8868, 0x9762, 0x610f, 0x56fe), '问题概况'],
  [u(0x41, 0x49, 0x20, 0x5bf9, 0x8bdd, 0x56de, 0x987e), '前文记录'],
  [u(0x5185, 0x90e8, 0x5907, 0x6ce8), '服务备注'],
  [u(0x8d28, 0x68c0, 0x4e0e, 0x98ce, 0x9669, 0x63d0, 0x793a), '服务建议'],
  [u(0x4e1a, 0x52a1, 0x51c6, 0x5907, 0x6001), '服务准备状态'],
  [u(0x53, 0x4f, 0x50, 0x20, 0x5206, 0x652f), '服务类型'],
  [u(0x53, 0x4f, 0x50, 0x5206, 0x652f), '服务类型'],
  [u(0x65c1, 0x542c, 0x8d28, 0x68c0), '服务质检'],
  [u(0x8f6c, 0x4ea4, 0x5ba1, 0x8ba1), '服务记录'],
  ['Gemini', '审核服务'],
  ['gemini', '审核服务'],
  ['GPT', '复核服务'],
  ['gpt', '复核服务'],
  ['DeepSeek', '服务模型'],
  ['deepseek', '服务模型'],
  ['YOLO', '辅助检测'],
  ['yolo', '辅助检测'],
  ['Token', '服务额度'],
  ['token', '服务额度'],
  ['Prompt', '服务规则'],
  ['prompt', '服务规则'],
  ['API Key', '服务凭证'],
  ['api key', '服务凭证'],
  ['endpoint', '服务接口'],
  ['Endpoint', '服务接口'],
  ['Mock', '演示数据'],
  ['mock', '演示数据'],
  ['外包', '服务团队'],
];

export function sanitizePublicText(value) {
  let text = typeof value === 'string' ? value : String(value ?? '');
  for (const [from, to] of PUBLIC_TEXT_REPLACEMENTS) {
    text = text.split(from).join(to);
  }
  text = text.replace(/https?:\/\/\S+/gi, '服务链接');
  return text;
}

export function sanitizePublicObject(value) {
  return JSON.parse(JSON.stringify(value ?? null), (_key, item) => (
    typeof item === 'string' ? sanitizePublicText(item) : item
  ));
}
