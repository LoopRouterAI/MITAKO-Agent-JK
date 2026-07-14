import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { sanitizePublicText } from '../../src/utils/publicText.js';

const hookSource = await readFile(new URL('../../src/hooks/useChatSSE.js', import.meta.url), 'utf8');
const appSource = await readFile(new URL('../../src/App.jsx', import.meta.url), 'utf8');
const chatInputSource = await readFile(new URL('../../src/components/chat/ChatInput.jsx', import.meta.url), 'utf8');
const i18nSource = await readFile(new URL('../../src/i18n/zh-CN.js', import.meta.url), 'utf8');
const attachmentSources = `${hookSource}\n${chatInputSource}\n${i18nSource}`;

assert.match(hookSource, /const userGenerationRef = useRef\(0\)/, '缺少用户会话代际');
assert.match(hookSource, /const sessionAbortControllerRef = useRef\(new AbortController\(\)\)/, '缺少会话级取消控制器');
assert.match(hookSource, /const prepareUserSwitch = useCallback/, '缺少同步用户切换清理入口');
assert.match(hookSource, /signal: sessionContext\.signal/, '异步请求未绑定当前会话取消信号');
assert.match(hookSource, /我上传了一段视频，请帮我创建审核任务。/, '视频附件默认文案不正确');
assert.match(hookSource, /我上传了一张照片，请帮我创建审核任务。/, '图片附件默认文案不正确');
assert.doesNotMatch(attachmentSources, /创建审核任务并转客服确认/, '真实附件路径仍会误触发人工转接');
assert.doesNotMatch(hookSource, /handoff\/reset\?session_id=session_\$\{sessionContext\.userId\}/, '切换用户仍会重置服务器人工会话');
assert.match(hookSource, /restoreHandoffState/, '切回用户时没有恢复人工服务状态');
assert.match(appSource, /<ChatPanel\s+key=\{currentUser\}/, '切换用户不会重建附件输入组件');
assert.match(
  appSource,
  /chat\.prepareUserSwitch\(\);\s*setOrderPickerOpen\(false\);\s*selectOrder\(null\);\s*setCurrentUser\(userId\);/,
  '用户切换必须先失效旧会话并清空订单，再更新当前用户',
);
assert.equal(sanitizePublicText('请补充外包装六面照片'), '请补充外包装六面照片', '外包装被外包身份词误替换');
assert.equal(sanitizePublicText('外包客服将处理'), '客服团队将处理', '外包客服身份词未净化');

console.log('0714 前端用户隔离与附件语义专项检查通过');
