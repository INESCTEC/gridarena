(function () {
  var messagesEl = document.getElementById('chat-messages');
  var form = document.getElementById('chat-form');
  var inputEl = document.getElementById('chat-input');
  var ws = null;
  var statusEl = null;

  function connect() {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/chat/ws');

    ws.onopen = function () {
      if (messagesEl && messagesEl.children.length === 0) {
        appendMessage('assistant', 'Hello! I\'m your Grid Assistant. Ask me anything about your low voltage grids.');
      }
    };

    ws.onmessage = function (event) {
      var msg = JSON.parse(event.data);
      handleMessage(msg);
    };

    ws.onclose = function () {
      setTimeout(connect, 3000);
    };
  }

  function handleMessage(msg) {
    if (msg.type === 'status') {
      showStatus(msg.content);
    } else if (msg.type === 'assistant_message') {
      clearStatus();
      appendMessage('assistant', msg.content);
    } else if (msg.type === 'error') {
      clearStatus();
      appendMessage('error', msg.content);
    } else if (msg.type === 'tool_result') {
      showStatus('Processing results...');
    }
  }

  function appendMessage(type, text) {
    if (!messagesEl) return;
    var div = document.createElement('div');
    div.className = 'msg msg--' + type;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function showStatus(text) {
    clearStatus();
    if (!messagesEl) return;
    statusEl = document.createElement('div');
    statusEl.className = 'msg msg--status';
    statusEl.textContent = text;
    messagesEl.appendChild(statusEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function clearStatus() {
    if (statusEl && statusEl.parentNode) {
      statusEl.parentNode.removeChild(statusEl);
    }
    statusEl = null;
  }

  function send() {
    if (!inputEl) return;
    var text = inputEl.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    appendMessage('user', text);
    ws.send(JSON.stringify({ type: 'user_message', content: text }));
    inputEl.value = '';
  }

  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      send();
    });
  }

  // Widget toggle logic
  var widget = document.getElementById('chat-widget');
  var toggle = document.getElementById('chat-toggle');
  var closeBtn = document.getElementById('chat-close');

  if (toggle && widget) {
    toggle.addEventListener('click', function () {
      widget.classList.remove('chat-widget--collapsed');
      if (inputEl) inputEl.focus();
    });
  }

  if (closeBtn && widget) {
    closeBtn.addEventListener('click', function () {
      widget.classList.add('chat-widget--collapsed');
    });
  }

  connect();
})();
