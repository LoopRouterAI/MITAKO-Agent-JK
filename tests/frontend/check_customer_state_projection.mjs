import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const hook = await readFile(new URL('../../src/hooks/useChatSSE.js', import.meta.url), 'utf8');
const app = await readFile(new URL('../../src/App.jsx', import.meta.url), 'utf8');
const panel = await readFile(new URL('../../src/components/chat/ChatPanel.jsx', import.meta.url), 'utf8');
const desk = await readFile(new URL('../../src/desk/HumanAgentDesk.jsx', import.meta.url), 'utf8');
const card = await readFile(new URL('../../src/components/shared/ConversationStateCard.jsx', import.meta.url), 'utf8');
const i18n = await readFile(new URL('../../src/i18n/zh-CN.js', import.meta.url), 'utf8');

assert.match(hook, /const \[conversationState, setConversationState\] = useState\(null\)/);
assert.match(hook, /eventData\?\.conversation_state/);
assert.match(hook, /setConversationState\(eventData\.conversation_state\)/);
assert.match(hook, /setConversationState\(statusData\.conversation_state\)/);
assert.match(hook, /setConversationState\(data\.conversation_state\)/);
assert.match(
  hook,
  /const restoreHandoffState = useCallback\([^]*setConversationState\(data\.conversation_state\)/,
);
assert.match(hook, /conversationState,/);
assert.match(app, /conversationState=\{chat\.conversationState\}/);
assert.match(panel, /<ConversationStateCard state=\{conversationState\}/);
assert.match(desk, /<ConversationStateCard state=\{brief\?\.conversation_state\}/);
assert.match(card, /failed: t\('conversationState\.statusFailed'\)/);
assert.match(i18n, /statusFailed: '未执行成功'/);
assert.doesNotMatch(card, /tool_name|Prompt|Gemini|百度云/);

console.log('客服公开状态在用户端与坐席端使用同一投影');
