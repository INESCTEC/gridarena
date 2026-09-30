(function () {
  var agent = window.DOC_AGENT;
  if (!agent) return;

  var messagesEl = document.getElementById('doc-agent-page-messages');
  var sourcesListEl = document.getElementById('doc-agent-page-sources-list');
  var form = document.getElementById('doc-agent-page-form');
  var inputEl = document.getElementById('doc-agent-page-input');
  var ws = null;

  function renderSources() {
    sourcesListEl.innerHTML = '';
    (agent.sources || []).forEach(function (src) {
      var row = document.createElement('div');
      row.className = 'doc-agent-source-item';
      var link = document.createElement('a');
      link.href = '/chat/agents/' + agent.agent_id + '/sources/' + src.source_id + '/view';
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = src.title || src.filename;
      row.appendChild(link);
      sourcesListEl.appendChild(row);
    });
  }

  function connect() {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/chat/agents/' + agent.agent_id + '/ws');
    ws.onmessage = function (event) {
      var msg = JSON.parse(event.data);
      if (msg.type === 'assistant_message') {
        appendMessage('assistant', msg.content, msg.citations);
      } else if (msg.type === 'error') {
        appendMessage('error', msg.content);
      }
    };
  }

  function appendMessage(type, text, citations) {
    var div = document.createElement('div');
    div.className = 'msg msg--' + type;
    div.textContent = text;
    messagesEl.appendChild(div);

    if (citations && citations.length) {
      var chips = document.createElement('div');
      citations.forEach(function (c) {
        var chip = document.createElement('a');
        chip.className = 'citation-chip';
        chip.textContent = '[' + c.marker + '] ' + c.filename + (c.section ? ' › ' + c.section : '');
        chip.href = '/chat/agents/' + agent.agent_id + '/sources/' + c.source_id + '/view#' + c.anchor;
        chip.target = '_blank';
        chip.rel = 'noopener';
        chips.appendChild(chip);
      });
      messagesEl.appendChild(chips);
    }

    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function send() {
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

  var deleteBtn = document.getElementById('doc-agent-page-delete');
  if (deleteBtn) {
    deleteBtn.addEventListener('click', function () {
      if (!window.confirm('Delete "' + agent.name + '" and all its documents? This cannot be undone.')) return;
      fetch('/chat/agents/' + agent.agent_id, { method: 'DELETE' })
        .then(function (r) {
          if (!r.ok) throw new Error('delete failed');
          if (ws) ws.close();
          window.location.href = '/chat/agents/ui';
        })
        .catch(function () { window.alert('Could not delete the assistant.'); });
    });
  }

  renderSources();
  appendMessage('assistant', 'Ask me anything about the documents attached to "' + agent.name + '".');
  connect();
})();
