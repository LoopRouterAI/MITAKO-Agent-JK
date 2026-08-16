# -*- coding: utf-8 -*-
"""客服 HTML 报告的静态样式与无依赖媒体预览脚本。"""

LIGHTBOX_HTML = """
<dialog class="lightbox" id="mediaLightbox" aria-labelledby="lightboxTitle">
  <section class="lightbox-panel">
    <header><b id="lightboxTitle">证据预览</b><button type="button" data-close-preview>关闭</button></header>
    <div id="lightboxBody" class="lightbox-body"></div>
  </section>
</dialog>
<script>
document.addEventListener('DOMContentLoaded', function () {
  try {
    var box = document.getElementById('mediaLightbox');
    var body = document.getElementById('lightboxBody');
    var title = document.getElementById('lightboxTitle');
    var opener = null;
    if (!box || !body || !title) return;
    function closePreview() {
      if (box.open) box.close();
    }
    function openPreview(button) {
      var src = button.getAttribute('data-preview-src') || '';
      var kind = button.getAttribute('data-preview-kind') || 'image';
      title.textContent = button.getAttribute('data-preview-title') || '证据预览';
      body.replaceChildren();
      if (kind === 'video') {
        var video = document.createElement('video');
        var seekSeconds = Number(button.getAttribute('data-preview-seconds'));
        video.src = src;
        video.controls = true;
        video.playsInline = true;
        if (Number.isFinite(seekSeconds) && seekSeconds >= 0) {
          video.addEventListener('loadedmetadata', function () {
            video.currentTime = seekSeconds;
          }, { once: true });
        }
        body.appendChild(video);
      } else {
        var img = document.createElement('img');
        img.src = src;
        img.alt = title.textContent;
        body.appendChild(img);
      }
      opener = button;
      box.showModal();
      box.querySelector('[data-close-preview]').focus();
    }
    document.querySelectorAll('[data-preview-src]').forEach(function (button) {
      button.addEventListener('click', function () { openPreview(button); });
    });
    document.querySelectorAll('[data-close-preview]').forEach(function (button) {
      button.addEventListener('click', closePreview);
    });
    box.addEventListener('click', function (event) {
      if (event.target === box) closePreview();
    });
    box.addEventListener('close', function () {
      body.replaceChildren();
      if (opener && opener.isConnected) opener.focus();
      opener = null;
    });
  } catch (error) {
    console.error('报告预览初始化失败', error);
  }
});
</script>
"""


REPORT_CSS = """
:root {
  color-scheme:light;
  --ink:#10131f; --ink-2:#252a38; --muted:#687083; --line:#e8ecdf;
  --card:#fff; --lime:#c8ec5f; --gold:#ffd43d; --rose:#ff75a8;
  --violet:#8b5cf6; --cyan:#12d6c7; --shadow:0 20px 52px rgba(16,19,31,.10);
  font-family:system-ui,"Segoe UI","Microsoft YaHei UI","Microsoft YaHei",sans-serif;
}
* { box-sizing:border-box; }
:where(h1,h2,h3,h4,p,li,td,th,summary,button,a,b,span,figcaption) { overflow-wrap:anywhere; word-break:normal; }
body {
  margin:0; color:var(--ink);
  background:#f5f7f3;
}
a { color:inherit; }
button { font:inherit; color:inherit; cursor:pointer; }
summary { min-height:44px; }
.shell { width:min(1180px,calc(100vw - 32px)); margin:0 auto; padding:26px 0 56px; }
.hero > *, .panel, .metric, .evidence-card, .media-tile { min-width:0; }
.hero {
  position:relative; display:grid; grid-template-columns:minmax(0,1fr) 220px;
  gap:22px; align-items:stretch; overflow:hidden; padding:30px;
  border:1px solid rgba(16,19,31,.08); border-radius:8px;
  background:linear-gradient(135deg,rgba(255,255,255,.98),rgba(248,255,230,.92));
  box-shadow:var(--shadow);
}
.hero.simple { display:block; }
.hero::after { content:""; position:absolute; inset:auto 0 0; height:10px; background:var(--gold); }
.hero.tone-green::after { background:#2eaf5d; }
.hero.tone-amber::after { background:#f0a31a; }
.hero.tone-red::after { background:#df4b4b; }
.hero.tone-gray::after { background:#6b7280; }
.hero.tone-green .verdict-card { background:#e9f8ee; border-color:#78c895; }
.hero.tone-amber .verdict-card { background:#fff5d9; border-color:#e8bd59; }
.hero.tone-red .verdict-card { background:#fff0f0; border-color:#e29292; }
.hero.tone-gray .verdict-card { background:#f1f3f5; border-color:#aeb4bd; }
.badge {
  display:inline-flex; align-items:center; min-height:31px; padding:6px 11px;
  border:1px solid rgba(16,19,31,.10); border-radius:8px;
  background:linear-gradient(90deg,var(--lime),#efffb2);
  box-shadow:0 10px 24px rgba(139,214,0,.18); font-size:12px; font-weight:950;
}
.severity-flag {
  display:grid; grid-template-columns:auto 1fr; align-items:center; width:min(100%,620px);
  margin-top:14px; padding:12px 14px; border:2px solid #8c94a3; border-radius:8px; background:#f4f5f7;
}
.severity-flag small { grid-column:1 / -1; color:var(--muted); font-weight:900; }
.severity-flag b { font-size:34px; line-height:1; }
.severity-flag span { padding-left:14px; color:var(--ink-2); font-size:13px; line-height:1.55; }
.severity-yes { border-color:#d63636; background:#fff0f0; }
.severity-yes b { color:#b21f1f; }
.opening-evidence-banner {
  display:grid; grid-template-columns:minmax(150px,220px) 1fr; gap:16px; align-items:center;
  margin-top:14px; padding:14px 16px; border:2px solid #d39b24; border-radius:8px; background:#fff8e7;
}
.opening-evidence-banner div { display:grid; gap:3px; }
.opening-evidence-banner small { color:var(--muted); font-weight:900; }
.opening-evidence-banner b { color:#8c6208; font-size:25px; }
.opening-evidence-banner p { margin:0; }
.opening-evidence-banner span { display:block; color:var(--muted); font-size:12px; }
.opening-pass { border-color:#52a66d; background:#effaf2; }
.opening-pass b { color:#22743c; }
h1 { max-width:850px; margin:16px 0 0; font-size:clamp(30px,3.6vw,42px); line-height:1.08; letter-spacing:0; text-wrap:pretty; overflow-wrap:anywhere; }
h2 { margin:0 0 12px; font-size:22px; line-height:1.2; }
h3 { margin:20px 0 10px; font-size:16px; }
p { line-height:1.75; }
.lead { max-width:850px; margin:16px 0 0; color:var(--ink-2); font-size:17px; }
.verdict-card {
  display:grid; align-content:center; gap:8px; min-height:190px; padding:20px;
  border:1px solid rgba(16,19,31,.10); border-radius:8px; box-shadow:0 18px 42px rgba(16,19,31,.14);
}
.verdict-card small, .metric small, .evidence-card small, .muted, .section-head p { color:var(--muted); }
.fine-print { margin:10px 0; color:var(--muted); font-size:12px; line-height:1.6; }
.verdict-card b { font-size:clamp(36px,4vw,44px); line-height:1; }
.verdict-card span { font-weight:900; }
.panel, .metric { border:1px solid rgba(16,19,31,.08); border-radius:8px; background:var(--card); box-shadow:var(--shadow); }
.panel { margin-top:16px; padding:22px; }
.failure-panel { background:linear-gradient(135deg,#fff2e7,#fff 74%); border-color:rgba(255,138,31,.35); }
.technical-details > summary, .summary-signals > summary, .summary-review-details > summary { display:flex; min-height:44px; align-items:center; cursor:pointer; font-weight:900; list-style-position:inside; }
.technical-details-body { margin-top:16px; }
.table-wrap { width:100%; max-width:100%; overflow-x:auto; overscroll-behavior-inline:contain; }
.table-wrap table { width:100%; border-collapse:collapse; }
.summary-review-details { margin-top:14px; padding:14px; border:1px solid var(--line); border-radius:8px; background:#fbfdf8; }
.summary-review-details-body { margin-top:12px; }
.technical-details-body > .panel { box-shadow:none; border-color:var(--line); }
.summary-attention, .summary-reason, .summary-gaps, .human-action { margin-top:12px; padding:14px; border-radius:8px; background:#f7faef; }
.summary-attention h3, .summary-reason h3, .summary-gaps h3, .human-action h3 { margin-top:0; }
.attention-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
.attention-grid article { min-width:0; }
.attention-grid h4 { margin:0 0 8px; }
.summary-signals { margin-top:14px; }
.metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:12px; margin-top:16px; }
.causality-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; margin:14px 0; }
.causality-grid article { min-width:0; padding:14px; border:1px solid var(--line); border-radius:8px; background:#f8fff0; }
.causality-grid small { display:block; color:var(--muted); margin-bottom:7px; }
.causality-grid b { display:block; overflow-wrap:anywhere; }
.material-readiness-summary { border-left:5px solid #6b7280 !important; }
.material-readiness-summary.status-green { border-left-color:#2eaf5d !important; background:#f2fbf5; }
.material-readiness-summary.status-amber { border-left-color:#f0a31a !important; background:#fffaf0; }
.material-readiness-summary.status-red { border-left-color:#df4b4b !important; background:#fff5f5; }
.material-readiness-summary span { display:block; margin-top:7px; color:var(--muted); font-size:12px; }
.material-readiness-details { margin-top:14px; padding:14px; border-radius:8px; }
.material-readiness-details summary { cursor:pointer; font-weight:900; }
.causality-panel { border-left:5px solid var(--cyan); }
.metric { min-height:112px; padding:16px; }
.metric.hot { background:linear-gradient(135deg,var(--lime),#fff7a6); }
.metric b { display:block; margin-top:8px; font-size:24px; line-height:1.15; }
.lead, .metric b, .evidence-card p, .media-tile figcaption { overflow-wrap:anywhere; word-break:break-word; }
.section-head { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:14px; }
.section-head p { max-width:520px; margin:0; font-size:13px; }
.evidence-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; }
.evidence-card { min-height:210px; padding:13px; border:1px solid var(--line); border-radius:8px; background:linear-gradient(135deg,#fff,#fbfff0); }
.evidence-card p { margin:10px 0; font-size:14px; }
.evidence-card .evidence-impact { display:grid; gap:3px; padding:9px 10px; border-left:4px solid var(--cyan); border-radius:8px; background:#effcf9; color:var(--ink-2); }
.evidence-impact strong { font-size:12px; }
.evidence-card b { display:inline-flex; max-width:100%; padding:5px 9px; border-radius:8px; background:linear-gradient(90deg,var(--lime),var(--gold)); font-size:12px; }
.risk-panel { border-top:4px solid #d76543; background:#fffaf7; }
.issue-panel { border-top:4px solid var(--cyan); background:#f7fcfd; }
.boundary-panel { border-top:4px solid #75a43a; background:#fbfdf8; }
.boundary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; }
.boundary-card { min-width:0; padding:16px; border:1px solid var(--line); border-radius:8px; background:#fff; }
.boundary-card h3 { margin-top:0; }
.boundary-card p { margin:0; overflow-wrap:anywhere; }
.status-card { border-left:6px solid #d3d8df; }
.status-green { border-left-color:#2eaf5d; background:#f2fbf5; }
.status-amber { border-left-color:#f0a31a; background:#fffaf0; }
.status-red { border-left-color:#df4b4b; background:#fff5f5; }
.status-gray { border-left-color:#6b7280; background:#f4f5f6; }
.evidence-link { display:inline-flex; max-width:100%; min-height:44px; align-items:center; margin:2px 4px 2px 0; padding:6px 9px; border:1px solid #9bc7bd; border-radius:8px; color:#11665b; font-weight:800; text-decoration:none; }
.evidence-link:hover, .evidence-link:focus-visible { background:#e8f8f4; outline:2px solid #12a895; outline-offset:2px; }
.human-action { margin-top:16px; padding:18px; border:1px solid var(--line); border-left-width:8px; border-radius:8px; }
.human-action h3 { margin:0 0 6px; }
.human-action p { margin:0; font-size:17px; font-weight:750; }
.inference-channels-panel summary { cursor:pointer; margin-bottom:12px; font-size:18px; font-weight:900; }
.minor-report .video-only, .minor-report .product-only { display:none !important; }
.boundary-list { margin:0; padding-left:20px; }
.boundary-list li { margin:7px 0; line-height:1.65; overflow-wrap:anywhere; }
.evidence-media { display:grid; gap:8px; margin:8px 0 10px; }
.thumb { display:block; width:100%; min-height:44px; padding:0; overflow:hidden; border:1px solid rgba(16,19,31,.12); border-radius:8px; background:#10131f; }
.thumb img, .media-tile img { display:block; width:100%; aspect-ratio:16/10; object-fit:contain; background:#10131f; }
.jump { display:inline-flex; width:max-content; max-width:100%; min-height:44px; align-items:center; padding:8px 10px; border:1px solid rgba(16,19,31,.12); border-radius:8px; background:#fff; text-decoration:none; font-size:12px; font-weight:950; white-space:normal; }
.inline-preview { display:inline-flex; width:max-content; min-height:44px; align-items:center; padding:6px 0; border:0; background:transparent; color:var(--ink); text-align:left; font-weight:950; }
.proof { background:linear-gradient(135deg,#fff,#fff7da); }
.media-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:12px; }
.media-tile { margin:0; overflow:hidden; border:1px solid var(--line); border-radius:8px; background:#fff; box-shadow:0 12px 28px rgba(16,19,31,.08); }
.media-tile > button { display:block; width:100%; min-height:44px; padding:0; border:0; background:#10131f; }
.media-tile figcaption { display:grid; gap:4px; padding:9px; color:var(--muted); font-size:12px; }
.media-tile figcaption a { color:var(--ink); font-weight:950; }
.lightbox:not([open]) { display:none; }
.lightbox[open] { position:fixed; inset:0; z-index:50; display:grid; width:100vw; max-width:none; height:100dvh; max-height:none; margin:0; place-items:center; padding:22px; border:0; background:transparent; }
.lightbox::backdrop { background:rgba(16,19,31,.72); backdrop-filter:blur(10px); }
.lightbox-panel { position:relative; z-index:1; width:min(1080px,100%); max-height:92vh; overflow:hidden; border:1px solid rgba(255,255,255,.34); border-radius:8px; background:#fff; box-shadow:0 28px 72px rgba(0,0,0,.32); }
.lightbox-panel header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 14px; border-bottom:1px solid var(--line); background:linear-gradient(90deg,var(--lime),#fff8bd); }
.lightbox-panel header button { min-width:44px; min-height:44px; padding:8px 12px; border:1px solid rgba(16,19,31,.16); border-radius:8px; background:#fff; font-weight:950; }
.lightbox-body { display:grid; place-items:center; max-height:calc(92vh - 62px); padding:12px; background:#10131f; }
.lightbox-body img, .lightbox-body video { display:block; max-width:100%; max-height:calc(92vh - 86px); border-radius:8px; object-fit:contain; }
@media (max-width:760px) {
  .shell { width:min(100% - 20px,1180px); padding-top:12px; }
  .hero { grid-template-columns:1fr; padding:18px; border-radius:8px; }
  h1, p, .lead { overflow-wrap:anywhere; word-break:normal; }
  h1 { font-size:30px; }
  .metrics { grid-template-columns:1fr; }
  .metric { min-height:auto; }
  .verdict-card { min-height:130px; }
  .verdict-card b { font-size:38px; }
  .section-head { display:block; }
  .panel { padding:16px; border-radius:8px; }
}
@media (max-width:520px) {
  .shell { width:calc(100% - 20px); max-width:370px; margin-inline:auto; }
}
"""
