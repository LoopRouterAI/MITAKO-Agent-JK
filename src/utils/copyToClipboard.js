/** 剪贴板复制（含 execCommand 降级） */
export async function copyToClipboard(text, btnId) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  const original = btn.innerHTML;

  const ok = () => {
    btn.innerHTML = '<span class="text-emerald-500 text-xs font-bold">已复制</span>';
    setTimeout(() => { btn.innerHTML = original; }, 1200);
  };

  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      ok();
      return;
    } catch {
      /* fallback */
    }
  }

  const area = document.createElement('textarea');
  area.value = text;
  area.style.position = 'fixed';
  area.style.left = '-9999px';
  document.body.appendChild(area);
  area.select();
  try {
    if (document.execCommand('copy')) ok();
  } finally {
    document.body.removeChild(area);
  }
}
