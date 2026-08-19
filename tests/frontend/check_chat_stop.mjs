import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const hookSource = await readFile(new URL('../../src/hooks/useChatSSE.js', import.meta.url), 'utf8');
const appSource = await readFile(new URL('../../src/App.jsx', import.meta.url), 'utf8');
const panelSource = await readFile(new URL('../../src/components/chat/ChatPanel.jsx', import.meta.url), 'utf8');
const inputSource = await readFile(new URL('../../src/components/chat/ChatInput.jsx', import.meta.url), 'utf8');
const i18nSource = await readFile(new URL('../../src/i18n/zh-CN.js', import.meta.url), 'utf8');

assert.match(hookSource, /const stopCurrentTurn = useCallback/, 'Hook 未暴露停止当前轮次动作');
assert.match(hookSource, /abortControllerRef\.current\.abort\(\)/, '停止动作未复用当前 AbortController');
assert.match(hookSource, /activeTurnIdRef\.current \+= 1/, '停止动作未让旧流事件立即失效');
assert.match(hookSource, /streamInFlightRef\.current = false/, '停止动作未同步恢复再次发送能力');
assert.match(hookSource, /setIsAwaitingStream\(false\)/, '停止动作未恢复输入状态');
assert.match(hookSource, /activeTurnUiIdsRef/, '停止动作未跟踪并清理局部助手气泡');
assert.match(hookSource, /startsWith\('welcome_scan_'\)/, '发送新轮次未清理未完成欢迎状态卡');
assert.doesNotMatch(
  hookSource.match(/const handleHandoff = useCallback\([^]*?\n  \}, \[[^]*?\]\);/)?.[0] || '',
  /streamFinalizedRef\.current = true/,
  '转接事件不应在 done 前提前完成当前流',
);
assert.match(
  hookSource,
  /turnId !== activeTurnIdRef\.current[^]*return/,
  '旧轮次事件没有代际隔离',
);
assert.match(hookSource, /let receivedDone = false/, '流读取未记录服务端成功终态');
assert.match(
  hookSource,
  /if \(!receivedDone[^)]*\) discardCurrentTurnUi/,
  'EOF 未收到 done 时仍可能按成功收口',
);
assert.match(hookSource, /stopCurrentTurn,/, 'Hook 返回值未暴露 stopCurrentTurn');

assert.match(appSource, /onStop=\{chat\.stopCurrentTurn\}/, 'App 未向聊天面板传递停止动作');
assert.match(panelSource, /onStop,/, 'ChatPanel 未声明停止动作');
assert.match(panelSource, /onStop=\{onStop\}/, 'ChatPanel 未向输入区传递停止动作');
assert.match(inputSource, /import \{[^}]*Square[^}]*\} from 'lucide-react'/, '停止按钮未使用 lucide Square 图标');
assert.match(inputSource, /isAwaitingStream \? \(/, '生成期间发送按钮未原位切换为停止按钮');
assert.match(inputSource, /onClick=\{onStop\}/, '停止按钮未绑定停止动作');
assert.match(inputSource, /aria-label=\{t\('input\.stop'\)\}/, '停止按钮缺少 i18n aria-label');
assert.match(inputSource, /title=\{t\('input\.stop'\)\}/, '停止按钮缺少 tooltip');
assert.match(i18nSource, /stop: '停止生成'/, '缺少停止按钮中文文案');

console.log('聊天停止、Abort、输入恢复与旧流隔离检查通过');
