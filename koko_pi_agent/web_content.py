# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

# Remote 模式的 Web 前端 HTML。
# Web UI 静态 HTML。

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Koko Remote</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
  --bg: #1a1b26;
  --bg-surface: #24283b;
  --bg-input: #1f2335;
  --text: #c0caf5;
  --text-dim: #565f89;
  --text-bright: #e0e6ff;
  --accent: #bb9af7;
  --accent-dim: #7c6da4;
  --green: #9ece6a;
  --red: #f7768e;
  --yellow: #e0af68;
  --blue: #7aa2f7;
  --border: #3b4261;
  --tool-bg: #1f2335;
  --code-bg: #16161e;
}

html, body { height: 100%; background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace; font-size: 14px; }

#app { display: flex; flex-direction: column; height: 100vh; max-width: 960px; margin: 0 auto; }

/* 顶部状态栏 */
#status-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 16px; border-bottom: 1px solid var(--border);
  font-size: 12px; color: var(--text-dim); flex-shrink: 0;
}
#status-bar .brand { color: var(--accent); font-weight: bold; font-size: 14px; }
#status-bar .info { display: flex; gap: 16px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot.connected { background: var(--green); }
.dot.disconnected { background: var(--red); }

/* 消息区域 */
#messages {
  flex: 1; overflow-y: auto; padding: 16px;
  scroll-behavior: smooth;
}
#messages::-webkit-scrollbar { width: 6px; }
#messages::-webkit-scrollbar-track { background: transparent; }
#messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

.msg { margin-bottom: 16px; line-height: 1.6; }
.msg-user { }
.msg-user .label { color: var(--accent); font-weight: bold; }
.msg-user .content { color: var(--text-bright); margin-top: 4px; white-space: pre-wrap; }
.msg-assistant .content { color: var(--text); margin-top: 4px; }
.msg-assistant .content p { margin-bottom: 8px; }
.msg-assistant .content code {
  background: var(--code-bg); padding: 2px 6px; border-radius: 4px;
  font-size: 13px;
}
.msg-assistant .content pre {
  background: var(--code-bg); padding: 12px; border-radius: 6px;
  margin: 8px 0; overflow-x: auto; border: 1px solid var(--border);
}
.msg-assistant .content pre code { background: none; padding: 0; }

.msg-system { color: var(--text-dim); font-size: 13px; white-space: pre-wrap; }
.msg-error { color: var(--red); }

/* 工具调用 */
.tool-block {
  background: var(--tool-bg); border: 1px solid var(--border); border-radius: 6px;
  margin: 8px 0; overflow: hidden;
}
.tool-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; cursor: pointer; user-select: none;
  font-size: 13px;
}
.tool-header:hover { background: rgba(255,255,255,0.03); }
.tool-header .icon { font-size: 12px; color: var(--text-dim); transition: transform 0.2s; }
.tool-header .icon.expanded { transform: rotate(90deg); }
.tool-header .name { color: var(--blue); font-weight: 600; }
.tool-header .status { margin-left: auto; font-size: 12px; }
.tool-header .status.ok { color: var(--green); }
.tool-header .status.err { color: var(--red); }
.tool-header .status.loading { color: var(--yellow); }
.tool-body {
  display: none; padding: 8px 12px; border-top: 1px solid var(--border);
  font-size: 12px; max-height: 300px; overflow-y: auto; white-space: pre-wrap;
  color: var(--text-dim);
}
.tool-body.show { display: block; }

/* 思考过程（折叠） */
.thinking-block {
  background: var(--tool-bg); border: 1px solid var(--border); border-radius: 6px;
  margin: 8px 0; overflow: hidden;
}
.thinking-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; cursor: pointer; user-select: none;
  font-size: 13px; color: var(--text-dim);
}
.thinking-header:hover { background: rgba(255,255,255,0.03); }
.thinking-header .icon { font-size: 12px; transition: transform 0.2s; }
.thinking-header .icon.expanded { transform: rotate(90deg); }
.thinking-body {
  display: none; padding: 8px 12px; border-top: 1px solid var(--border);
  font-size: 12px; max-height: 300px; overflow-y: auto; white-space: pre-wrap;
  color: var(--text-dim); font-style: italic;
}
.thinking-body.show { display: block; }

/* 权限弹窗 */
.perm-dialog {
  background: var(--bg-surface); border: 2px solid var(--yellow);
  border-radius: 8px; padding: 16px; margin: 12px 0;
}
.perm-dialog .title { color: var(--yellow); font-weight: bold; margin-bottom: 8px; }
.perm-dialog .desc { color: var(--text); margin-bottom: 12px; font-size: 13px; white-space: pre-wrap; }
.perm-dialog .actions { display: flex; gap: 8px; }
.perm-dialog button {
  padding: 6px 16px; border-radius: 4px; border: 1px solid var(--border);
  cursor: pointer; font-family: inherit; font-size: 13px;
}
.btn-allow { background: var(--green); color: var(--bg); border-color: var(--green); }
.btn-deny { background: transparent; color: var(--red); border-color: var(--red); }
.btn-always { background: transparent; color: var(--blue); border-color: var(--blue); }

/* ASCII 吉祥物浮层 */
#mascot-overlay {
  display: none; position: fixed; top: 64px; right: 20px; z-index: 1000;
  width: 232px; max-width: calc(100vw - 24px);
  max-height: calc(100vh - 16px); overflow: hidden;
  padding: 30px 16px 14px;
  background: var(--bg-surface); border: 1px solid var(--accent-dim);
  border-radius: 8px; box-shadow: 0 8px 28px rgba(0,0,0,0.45);
  cursor: grab; touch-action: none; user-select: none;
}
#mascot-overlay.show { display: block; }
#mascot-overlay.dragging { cursor: grabbing; }
#mascot-overlay pre {
  width: 19ch; height: 11.25em; margin: 0 auto; overflow: hidden;
  color: var(--accent);
  font: 600 14px/1.25 'SF Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace;
  text-align: left; white-space: pre; pointer-events: none;
}
#mascot-close {
  position: absolute; top: 5px; right: 6px;
  width: 26px; height: 24px; padding: 0;
  border: 1px solid transparent; border-radius: 4px;
  background: transparent; color: var(--text-dim);
  font: bold 16px/1 monospace; cursor: pointer; touch-action: manipulation;
}
#mascot-close:hover, #mascot-close:focus-visible {
  color: var(--text-bright); border-color: var(--border);
  background: rgba(187,154,247,0.12); outline: none;
}
@media (max-width: 600px) {
  #mascot-overlay { top: 52px; right: 8px; }
}

/* 斜杠命令菜单 */
#slash-menu {
  display: none; position: absolute; bottom: 100%; left: 0; right: 0;
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: 6px; margin-bottom: 4px; max-height: 240px;
  overflow-y: auto; box-shadow: 0 -4px 12px rgba(0,0,0,0.3);
}
#slash-menu.show { display: block; }
.slash-item {
  padding: 8px 12px; cursor: pointer; display: flex; gap: 8px; align-items: baseline;
}
.slash-item:hover, .slash-item.active { background: rgba(187,154,247,0.1); }
.slash-item .cmd-name { color: var(--accent); font-weight: 600; white-space: nowrap; }
.slash-item .cmd-desc { color: var(--text-dim); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 输入区域 */
#input-area {
  flex-shrink: 0; border-top: 1px solid var(--border);
  padding: 12px 16px; display: flex; gap: 8px; align-items: flex-end;
}
#input-area textarea {
  flex: 1; background: var(--bg-input); color: var(--text-bright);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 10px 12px; font-family: inherit; font-size: 14px;
  resize: none; outline: none; min-height: 42px; max-height: 200px;
  line-height: 1.5;
}
#input-area textarea:focus { border-color: var(--accent); }
#input-area textarea::placeholder { color: var(--text-dim); }
#send-btn {
  background: var(--accent); color: var(--bg); border: none;
  border-radius: 6px; padding: 10px 16px; cursor: pointer;
  font-family: inherit; font-size: 14px; font-weight: 600;
  white-space: nowrap;
}
#send-btn:hover { opacity: 0.9; }
#send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* 流式光标闪烁 */
.cursor { animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }

/* 完成指示 */
.done-indicator { color: var(--text-dim); font-size: 12px; margin-top: 4px; }

/* Markdown 列表 */
.msg-assistant .content ul, .msg-assistant .content ol { padding-left: 20px; margin: 8px 0; }
.msg-assistant .content li { margin: 4px 0; }
.msg-assistant .content h1, .msg-assistant .content h2, .msg-assistant .content h3 {
  color: var(--text-bright); margin: 12px 0 8px; }
.msg-assistant .content blockquote {
  border-left: 3px solid var(--accent-dim); padding-left: 12px;
  color: var(--text-dim); margin: 8px 0;
}
.msg-assistant .content table { border-collapse: collapse; margin: 8px 0; }
.msg-assistant .content th, .msg-assistant .content td {
  border: 1px solid var(--border); padding: 6px 12px; text-align: left; }
.msg-assistant .content th { background: var(--bg-surface); }
</style>
</head>
<body>
<div id="mascot-overlay" role="region" aria-label="Koko animated ASCII corgi" aria-hidden="true">
  <button id="mascot-close" type="button" aria-label="Close mascot" title="Close">x</button>
  <pre id="mascot-art" aria-hidden="true"></pre>
</div>
<div id="app">
  <div id="status-bar">
    <span class="brand">⚡ Koko Remote</span>
    <div class="info">
      <span id="conn-status"><span class="dot disconnected"></span>Connecting...</span>
      <span id="token-info"></span>
    </div>
  </div>
  <div id="messages"></div>
  <div id="input-area" style="position:relative;">
    <div id="slash-menu"></div>
    <textarea id="input" placeholder="Send a message... (Enter to send, Shift+Enter for newline)" rows="1"></textarea>
    <button id="send-btn">Send</button>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');
const connStatus = document.getElementById('conn-status');
const tokenInfo = document.getElementById('token-info');
const slashMenu = document.getElementById('slash-menu');
const mascotOverlay = document.getElementById('mascot-overlay');
const mascotClose = document.getElementById('mascot-close');
const mascotArt = document.getElementById('mascot-art');

const mascotFrames = [
  String.raw`     /\       /\
    /  \_____/  \
   /             \
  |   o       o   |
  |       ^       |
  |    \_____/    |
   \_____________/
     /|       |\
    /_|_______|_\
`,
  String.raw`     /\       /\
    /  \_____/  \
   /             \
  |   -       o   |
  |       ^       |
  |    \__U__/    |
   \_____________/
     /|       |\
    /_|_______|_\
`,
  String.raw`     /\       /\
    /  \_____/  \
   /             \
  |   o       -   |
  |       ^       |
  |    \__U__/    |
   \_____________/
     /|       |\
    /_|_______|_\
`,
].map(frame => frame.trimEnd());
const MASCOT_FRAME_MS = 360;
const MASCOT_VIEWPORT_GAP = 8;

let ws = null;
let streaming = false;
let allCommands = [];
let slashCursor = 0;
let slashFiltered = [];
let currentAssistantEl = null;
let currentStreamText = '';
let currentThinkingEl = null;
let currentThinkingText = '';
let autoScroll = true;
let pingTimer = null;
let connectedOnce = false;
let mascotFrameIndex = 0;
let mascotTimer = null;
let mascotDrag = null;

// Markdown 渲染配置
if (typeof marked !== 'undefined') {
  marked.setOptions({ breaks: true, gfm: true });
}

function renderMarkdown(text) {
  if (typeof marked !== 'undefined') {
    try { return marked.parse(text); } catch(e) {}
  }
  return escapeHtml(text);
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function connect() {
  if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
  if (ws) { try { ws.onclose = null; ws.close(); } catch(e) {} ws = null; }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');

  ws.onopen = () => {
    connStatus.innerHTML = '<span class="dot connected"></span>Connected';
    // 每 10 秒发一次应用层 ping，防止连接被中间件/浏览器回收
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping', data: {} }));
      }
    }, 10000);
  };

  ws.onclose = () => {
    connStatus.innerHTML = '<span class="dot disconnected"></span>Reconnecting...';
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    setTimeout(connect, 3000);
  };

  ws.onerror = () => {};

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    handleMessage(msg);
  };
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'connected':
      if (!connectedOnce) {
        addSystem('Session: ' + msg.data.session + ' | CWD: ' + msg.data.cwd);
        connectedOnce = true;
      }
      break;

    case 'commands':
      allCommands = msg.data || [];
      break;

    case 'system':
      addSystem(msg.data.message);
      break;

    case 'clear':
      messagesEl.innerHTML = '';
      addSystem('Conversation cleared.');
      break;

    case 'mascot_show':
      showMascot();
      break;

    case 'command_done':
      streaming = false;
      updateUI();
      break;

    case 'replay_user':
      addUser(msg.data.content);
      break;

    case 'replay_assistant': {
      const el = addAssistant('');
      updateAssistant(el, msg.data.content, false);
      break;
    }

    case 'stream_text':
      if (currentThinkingEl) {
        currentThinkingEl.querySelector('.thinking-header span:last-child').textContent = '💭 Thought';
        currentThinkingEl = null;
        currentThinkingText = '';
      }
      if (!currentAssistantEl) {
        currentAssistantEl = addAssistant('');
        currentStreamText = '';
      }
      currentStreamText += msg.data.text;
      updateAssistant(currentAssistantEl, currentStreamText, true);
      break;

    case 'stream_end':
      if (currentAssistantEl) {
        updateAssistant(currentAssistantEl, currentStreamText, false);
      }
      currentAssistantEl = null;
      currentStreamText = '';
      break;

    case 'thinking_text':
      if (!currentThinkingEl) {
        currentThinkingEl = addThinking();
        currentThinkingText = '';
      }
      currentThinkingText += msg.data.text;
      currentThinkingEl.querySelector('.thinking-body').textContent = currentThinkingText;
      break;

    case 'tool_use':
      if (currentThinkingEl) {
        currentThinkingEl.querySelector('.thinking-header span:last-child').textContent = '💭 Thought';
        currentThinkingEl = null;
        currentThinkingText = '';
      }
      addToolUse(msg.data);
      break;

    case 'tool_result':
      updateToolResult(msg.data);
      break;

    case 'permission_request':
      addPermissionDialog(msg.data);
      break;

    case 'ask_user':
      addAskUserDialog(msg.data);
      break;

    case 'turn_complete':
      break;

    case 'loop_complete':
      if (currentAssistantEl) {
        updateAssistant(currentAssistantEl, currentStreamText, false);
        currentAssistantEl = null;
        currentStreamText = '';
      }
      currentThinkingEl = null;
      currentThinkingText = '';
      const el = document.createElement('div');
      el.className = 'done-indicator';
      el.textContent = '✻ Done in ' + msg.data.elapsed.toFixed(1) + 's';
      messagesEl.appendChild(el);
      streaming = false;
      updateUI();
      scrollToBottom();
      break;

    case 'usage':
      tokenInfo.textContent = 'In: ' + formatTokens(msg.data.inputTokens) + ' | Out: ' + formatTokens(msg.data.outputTokens);
      break;

    case 'error':
      addError(msg.data.message);
      streaming = false;
      updateUI();
      break;

    case 'compact':
      addSystem('⟳ ' + msg.data.message);
      break;

    case 'retry':
      addSystem('↻ Retrying: ' + msg.data.reason);
      break;
  }
}

function formatTokens(n) {
  if (n > 1000000) return (n/1000000).toFixed(1) + 'M';
  if (n > 1000) return (n/1000).toFixed(1) + 'K';
  return '' + n;
}

function addUser(text) {
  const div = document.createElement('div');
  div.className = 'msg msg-user';
  div.innerHTML = '<span class="label">❯ </span><span class="content">' + escapeHtml(text) + '</span>';
  messagesEl.appendChild(div);
  scrollToBottom();
}

function addAssistant(text) {
  const div = document.createElement('div');
  div.className = 'msg msg-assistant';
  div.innerHTML = '<div class="content"></div>';
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function updateAssistant(el, text, isStreaming) {
  const contentEl = el.querySelector('.content');
  // 检测 <think>...</think> 标签，分离思考内容和正文
  const thinkMatch = text.match(/^<think>([\s\S]*?)<\/think>\s*([\s\S]*)$/);
  if (thinkMatch) {
    const thinkText = thinkMatch[1].trim();
    const bodyText = thinkMatch[2].trim();
    let html = '';
    if (thinkText) {
      html += '<div class="thinking-block">' +
        '<div class="thinking-header" onclick="toggleThinking(this)">' +
          '<span class="icon">▶</span>' +
          '<span>💭 Thought</span>' +
        '</div>' +
        '<div class="thinking-body">' + escapeHtml(thinkText) + '</div>' +
      '</div>';
    }
    if (bodyText) {
      html += renderMarkdown(bodyText);
    }
    if (isStreaming) html += '<span class="cursor">▎</span>';
    contentEl.innerHTML = html;
  } else if (text.startsWith('<think>') && isStreaming) {
    // 思考还没结束，显示为折叠的 thinking 块 + 光标
    const thinkBody = text.replace(/^<think>\s*/, '');
    let html = '<div class="thinking-block">' +
      '<div class="thinking-header" onclick="toggleThinking(this)">' +
        '<span class="icon">▶</span>' +
        '<span>💭 Thinking...</span>' +
      '</div>' +
      '<div class="thinking-body">' + escapeHtml(thinkBody) + '</div>' +
    '</div>';
    html += '<span class="cursor">▎</span>';
    contentEl.innerHTML = html;
  } else {
    let html = renderMarkdown(text);
    if (isStreaming) html += '<span class="cursor">▎</span>';
    contentEl.innerHTML = html;
  }
  scrollToBottom();
}

function addThinking() {
  const div = document.createElement('div');
  div.className = 'thinking-block';
  div.innerHTML =
    '<div class="thinking-header" onclick="toggleThinking(this)">' +
      '<span class="icon">▶</span>' +
      '<span>💭 Thinking...</span>' +
    '</div>' +
    '<div class="thinking-body"></div>';
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function toggleThinking(header) {
  header.querySelector('.icon').classList.toggle('expanded');
  header.nextElementSibling.classList.toggle('show');
}

function addSystem(text) {
  const div = document.createElement('div');
  div.className = 'msg msg-system';
  div.textContent = text;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function addError(text) {
  const div = document.createElement('div');
  div.className = 'msg msg-error';
  div.textContent = '✖ ' + text;
  messagesEl.appendChild(div);
  scrollToBottom();
}

// 工具调用
const toolElements = {};

function addToolUse(data) {
  const div = document.createElement('div');
  div.className = 'tool-block';

  const argsStr = data.args ? JSON.stringify(data.args, null, 2) : '';
  let argsPreview = '';
  if (data.args) {
    if (data.args.command) argsPreview = data.args.command;
    else if (data.args.file_path) argsPreview = data.args.file_path;
    else if (data.args.pattern) argsPreview = data.args.pattern;
    else if (data.args.path) argsPreview = data.args.path;
  }

  div.innerHTML =
    '<div class="tool-header" onclick="toggleTool(this)">' +
      '<span class="icon">▶</span>' +
      '<span class="name">' + escapeHtml(data.toolName) + '</span>' +
      (argsPreview ? '<span style="color:var(--text-dim);font-size:12px;margin-left:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:500px;">' + escapeHtml(argsPreview) + '</span>' : '') +
      '<span class="status loading">⏳ running...</span>' +
    '</div>' +
    '<div class="tool-body">' +
      (argsStr ? '<div style="color:var(--blue);margin-bottom:8px;">Args:\n' + escapeHtml(argsStr) + '</div>' : '') +
      '<div class="tool-output"></div>' +
    '</div>';

  messagesEl.appendChild(div);
  toolElements[data.toolName + '_' + (data.toolId || '')] = div;
  scrollToBottom();
}

function updateToolResult(data) {
  const key = data.toolName + '_' + (data.toolId || '');
  const div = toolElements[key];
  if (div) {
    const statusEl = div.querySelector('.status');
    if (data.isError) {
      statusEl.className = 'status err';
      statusEl.textContent = '✗ ' + data.elapsed.toFixed(1) + 's';
    } else {
      statusEl.className = 'status ok';
      statusEl.textContent = '✓ ' + data.elapsed.toFixed(1) + 's';
    }
    const outputEl = div.querySelector('.tool-output');
    if (data.output) {
      const truncated = data.output.length > 5000 ? data.output.substring(0, 5000) + '\n... (truncated)' : data.output;
      outputEl.textContent = truncated;
    }
    delete toolElements[key];
  } else {
    // 如果没有匹配到，直接创建一个完成的 tool block
    const block = document.createElement('div');
    block.className = 'tool-block';
    const status = data.isError ? '✗' : '✓';
    const statusClass = data.isError ? 'err' : 'ok';
    block.innerHTML =
      '<div class="tool-header" onclick="toggleTool(this)">' +
        '<span class="icon">▶</span>' +
        '<span class="name">' + escapeHtml(data.toolName) + '</span>' +
        '<span class="status ' + statusClass + '">' + status + ' ' + data.elapsed.toFixed(1) + 's</span>' +
      '</div>' +
      '<div class="tool-body">' + escapeHtml(data.output || '') + '</div>';
    messagesEl.appendChild(block);
  }
  scrollToBottom();
}

function toggleTool(header) {
  const icon = header.querySelector('.icon');
  const body = header.nextElementSibling;
  icon.classList.toggle('expanded');
  body.classList.toggle('show');
}

// 权限弹窗
function addPermissionDialog(data) {
  const div = document.createElement('div');
  div.className = 'perm-dialog';
  div.id = 'perm-' + data.id;
  div.innerHTML =
    '<div class="title">🔒 Permission Required: ' + escapeHtml(data.toolName) + '</div>' +
    '<div class="desc">' + escapeHtml(data.description) + '</div>' +
    '<div class="actions">' +
      '<button class="btn-allow" onclick="respondPerm(\'' + data.id + '\', \'allow\')">Allow</button>' +
      '<button class="btn-always" onclick="respondPerm(\'' + data.id + '\', \'allowAlways\')">Allow Always</button>' +
      '<button class="btn-deny" onclick="respondPerm(\'' + data.id + '\', \'deny\')">Deny</button>' +
    '</div>';
  messagesEl.appendChild(div);
  scrollToBottom();
}

function respondPerm(id, response) {
  ws.send(JSON.stringify({ type: 'permission_response', data: { id, response } }));
  const el = document.getElementById('perm-' + id);
  if (el) {
    el.innerHTML = '<div style="color:var(--text-dim)">🔒 Permission: ' + response + '</div>';
  }
}

// Ask User 弹窗
function addAskUserDialog(data) {
  const div = document.createElement('div');
  div.className = 'perm-dialog';
  div.id = 'ask-' + data.id;

  let html = '<div class="title">❓ Question</div>';
  const questions = data.questions || [];
  questions.forEach((q, qi) => {
    html += '<div style="margin-bottom:12px;">';
    html += '<div style="margin-bottom:6px;color:var(--text-bright);">' + escapeHtml(q.question || q.Text || '') + '</div>';
    const options = q.options || q.Options || [];
    options.forEach((opt, oi) => {
      const label = opt.label || opt.Label || '';
      const desc = opt.description || opt.Description || '';
      html += '<label style="display:block;margin:4px 0;cursor:pointer;">' +
        '<input type="radio" name="ask_' + data.id + '_' + qi + '" value="' + escapeHtml(label) + '"> ' +
        '<span style="color:var(--blue)">' + escapeHtml(label) + '</span>' +
        (desc ? ' <span style="color:var(--text-dim);font-size:12px;">— ' + escapeHtml(desc) + '</span>' : '') +
        '</label>';
    });
    // Other 选项
    html += '<label style="display:block;margin:4px 0;cursor:pointer;">' +
      '<input type="radio" name="ask_' + data.id + '_' + qi + '" value="__other__"> ' +
      '<span style="color:var(--text-dim)">Other: </span>' +
      '<input type="text" id="ask_other_' + data.id + '_' + qi + '" style="background:var(--bg-input);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:4px 8px;font-family:inherit;font-size:13px;width:300px;">' +
      '</label>';
    html += '</div>';
  });
  html += '<div class="actions"><button class="btn-allow" onclick="respondAsk(\'' + data.id + '\',' + questions.length + ')">Submit</button></div>';

  div.innerHTML = html;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function respondAsk(id, qCount) {
  const answers = {};
  for (let i = 0; i < qCount; i++) {
    const radios = document.querySelectorAll('input[name="ask_' + id + '_' + i + '"]');
    let val = '';
    radios.forEach(r => {
      if (r.checked) {
        if (r.value === '__other__') {
          val = document.getElementById('ask_other_' + id + '_' + i).value;
        } else {
          val = r.value;
        }
      }
    });
    answers['question_' + i] = val;
  }
  ws.send(JSON.stringify({ type: 'ask_user_response', data: { id, answers } }));
  const el = document.getElementById('ask-' + id);
  if (el) {
    el.innerHTML = '<div style="color:var(--text-dim)">✓ Answered</div>';
  }
}

// 滚动控制
messagesEl.addEventListener('scroll', () => {
  const { scrollTop, scrollHeight, clientHeight } = messagesEl;
  autoScroll = scrollHeight - scrollTop - clientHeight < 60;
});

function scrollToBottom() {
  if (autoScroll) {
    requestAnimationFrame(() => {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    });
  }
}

// 输入处理
function sendMessage() {
  if (slashMenu.classList.contains('show')) { hideSlashMenu(); }
  const text = inputEl.value.trim();
  if (!text || streaming) return;
  addUser(text);
  ws.send(JSON.stringify({ type: 'user_message', data: { content: text } }));
  inputEl.value = '';
  inputEl.style.height = 'auto';
  streaming = true;
  updateUI();
}

function updateUI() {
  sendBtn.disabled = streaming;
  inputEl.disabled = streaming;
  if (!streaming) inputEl.focus();
}

function renderMascotFrame() {
  mascotArt.textContent = mascotFrames[mascotFrameIndex];
}

function stopMascotAnimation() {
  if (mascotTimer !== null) {
    window.clearInterval(mascotTimer);
    mascotTimer = null;
  }
}

function startMascotAnimation() {
  stopMascotAnimation();
  mascotFrameIndex = 0;
  renderMascotFrame();
  mascotTimer = window.setInterval(() => {
    mascotFrameIndex = (mascotFrameIndex + 1) % mascotFrames.length;
    renderMascotFrame();
  }, MASCOT_FRAME_MS);
}

function clampMascotPosition(left, top) {
  const rect = mascotOverlay.getBoundingClientRect();
  const maxLeft = Math.max(
    MASCOT_VIEWPORT_GAP,
    window.innerWidth - rect.width - MASCOT_VIEWPORT_GAP,
  );
  const maxTop = Math.max(
    MASCOT_VIEWPORT_GAP,
    window.innerHeight - rect.height - MASCOT_VIEWPORT_GAP,
  );
  return {
    left: Math.min(Math.max(left, MASCOT_VIEWPORT_GAP), maxLeft),
    top: Math.min(Math.max(top, MASCOT_VIEWPORT_GAP), maxTop),
  };
}

function setMascotPosition(left, top) {
  const clamped = clampMascotPosition(left, top);
  mascotOverlay.style.right = 'auto';
  mascotOverlay.style.left = Math.round(clamped.left) + 'px';
  mascotOverlay.style.top = Math.round(clamped.top) + 'px';
}

function keepMascotInViewport() {
  if (!mascotOverlay.classList.contains('show')) return;
  const rect = mascotOverlay.getBoundingClientRect();
  setMascotPosition(rect.left, rect.top);
}

function stopMascotDrag() {
  if (mascotDrag === null) return;
  const pointerId = mascotDrag.pointerId;
  mascotDrag = null;
  mascotOverlay.classList.remove('dragging');
  if (mascotOverlay.hasPointerCapture(pointerId)) {
    mascotOverlay.releasePointerCapture(pointerId);
  }
}

function showMascot() {
  mascotOverlay.classList.add('show');
  mascotOverlay.setAttribute('aria-hidden', 'false');
  startMascotAnimation();
  window.requestAnimationFrame(keepMascotInViewport);
}

function hideMascot() {
  stopMascotAnimation();
  stopMascotDrag();
  mascotOverlay.classList.remove('show');
  mascotOverlay.setAttribute('aria-hidden', 'true');
  if (!inputEl.disabled) inputEl.focus();
}

function onMascotPointerDown(event) {
  if (!event.isPrimary || event.button !== 0 || mascotClose.contains(event.target)) {
    return;
  }
  const rect = mascotOverlay.getBoundingClientRect();
  mascotDrag = {
    pointerId: event.pointerId,
    offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top,
  };
  mascotOverlay.classList.add('dragging');
  mascotOverlay.setPointerCapture(event.pointerId);
  event.preventDefault();
}

function onMascotPointerMove(event) {
  if (mascotDrag === null || event.pointerId !== mascotDrag.pointerId) return;
  setMascotPosition(
    event.clientX - mascotDrag.offsetX,
    event.clientY - mascotDrag.offsetY,
  );
  event.preventDefault();
}

function onMascotPointerEnd(event) {
  if (mascotDrag === null || event.pointerId !== mascotDrag.pointerId) return;
  stopMascotDrag();
}

// ── 斜杠命令菜单 ──

function showSlashMenu(filter) {
  const prefix = filter.toLowerCase();
  slashFiltered = allCommands.filter(c => c.name.startsWith(prefix));
  if (slashFiltered.length === 0) { hideSlashMenu(); return; }
  slashCursor = 0;
  renderSlashMenu();
  slashMenu.classList.add('show');
}

function hideSlashMenu() {
  slashMenu.classList.remove('show');
  slashFiltered = [];
  slashCursor = 0;
}

function renderSlashMenu() {
  slashMenu.innerHTML = slashFiltered.map((c, i) =>
    '<div class="slash-item' + (i === slashCursor ? ' active' : '') + '" data-idx="' + i + '">' +
      '<span class="cmd-name">/' + escapeHtml(c.name) + '</span>' +
      '<span class="cmd-desc">' + escapeHtml(c.description) + '</span>' +
    '</div>'
  ).join('');
  // 点击选中
  slashMenu.querySelectorAll('.slash-item').forEach(el => {
    el.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const idx = parseInt(el.dataset.idx);
      selectSlashItem(idx);
    });
  });
  // 滚动到当前高亮项
  const activeEl = slashMenu.querySelector('.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

function selectSlashItem(idx) {
  const cmd = slashFiltered[idx];
  if (!cmd) return;
  inputEl.value = '/' + cmd.name + ' ';
  hideSlashMenu();
  inputEl.focus();
}

inputEl.addEventListener('keydown', (e) => {
  if (slashMenu.classList.contains('show')) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      slashCursor = Math.min(slashCursor + 1, slashFiltered.length - 1);
      renderSlashMenu();
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      slashCursor = Math.max(slashCursor - 1, 0);
      renderSlashMenu();
      return;
    }
    if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
      e.preventDefault();
      selectSlashItem(slashCursor);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      hideSlashMenu();
      return;
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + 'px';

  const val = inputEl.value;
  // 检测是否在输入斜杠命令
  if (val.startsWith('/') && !val.includes('\n')) {
    const prefix = val.substring(1).split(' ')[0];
    if (!val.includes(' ')) {
      showSlashMenu(prefix);
    } else {
      hideSlashMenu();
    }
  } else {
    hideSlashMenu();
  }
});

sendBtn.addEventListener('click', sendMessage);
mascotOverlay.addEventListener('pointerdown', onMascotPointerDown);
mascotOverlay.addEventListener('pointermove', onMascotPointerMove);
mascotOverlay.addEventListener('pointerup', onMascotPointerEnd);
mascotOverlay.addEventListener('pointercancel', onMascotPointerEnd);
mascotOverlay.addEventListener('lostpointercapture', onMascotPointerEnd);
mascotClose.addEventListener('pointerdown', (event) => event.stopPropagation());
mascotClose.addEventListener('click', hideMascot);

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && mascotOverlay.classList.contains('show')) {
    event.preventDefault();
    hideMascot();
  }
});

window.addEventListener('resize', () => {
  window.requestAnimationFrame(keepMascotInViewport);
});

// 启动
connect();
inputEl.focus();
</script>
</body>
</html>"""
