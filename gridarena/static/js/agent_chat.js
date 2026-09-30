(function () {
  var widget = document.getElementById('doc-agent-widget');
  if (!widget) return;

  var toggleBtn = document.getElementById('doc-agent-toggle');
  var closeBtn = document.getElementById('doc-agent-close');
  var selectEl = document.getElementById('doc-agent-select');
  var deleteBtn = document.getElementById('doc-agent-delete');
  var fullpageLink = document.getElementById('doc-agent-fullpage-link');

  var chatView = document.getElementById('doc-agent-widget-chat');
  var emptyView = document.getElementById('doc-agent-widget-empty');
  var createView = document.getElementById('doc-agent-widget-create');
  var messagesEl = document.getElementById('doc-agent-widget-messages');
  var form = document.getElementById('doc-agent-widget-form');
  var inputEl = document.getElementById('doc-agent-widget-input');

  var agentsById = {};
  var currentAgent = null;
  var ws = null;

  function showView(view) {
    [chatView, emptyView, createView].forEach(function (v) { v.style.display = 'none'; });
    view.style.display = view === chatView ? 'flex' : 'block';
  }

  function disconnect() {
    if (ws) {
      ws.onclose = null;
      ws.close();
      ws = null;
    }
  }

  function updateFullpageLink() {
    fullpageLink.href = currentAgent
      ? '/chat/agents/ui?agent_id=' + encodeURIComponent(currentAgent.agent_id)
      : '/chat/agents/ui';
  }

  function loadAgents(preferredId) {
    return fetch('/chat/agents')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var agents = data.agents || [];
        agentsById = {};
        selectEl.innerHTML = '';
        agents.forEach(function (agent) {
          agentsById[agent.agent_id] = agent;
          var opt = document.createElement('option');
          opt.value = agent.agent_id;
          opt.textContent = agent.name;
          selectEl.appendChild(opt);
        });
        var newOpt = document.createElement('option');
        newOpt.value = '__new__';
        newOpt.textContent = '+ New Assistant…';
        selectEl.appendChild(newOpt);

        if (!agents.length) {
          currentAgent = null;
          disconnect();
          updateFullpageLink();
          showView(emptyView);
          return;
        }

        var target = (preferredId && agentsById[preferredId]) ? preferredId : agents[0].agent_id;
        selectEl.value = target;
        openAgentChat(agentsById[target]);
      })
      .catch(function () { /* widget just stays on whatever view it had */ });
  }

  function openAgentChat(agent) {
    currentAgent = agent;
    updateFullpageLink();
    messagesEl.innerHTML = '';
    showView(chatView);
    connect(agent.agent_id);
    appendMessage('assistant', 'Ask me anything about the documents attached to "' + agent.name + '".');
  }

  function connect(agentId) {
    disconnect();
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/chat/agents/' + agentId + '/ws');
    ws.onmessage = function (event) {
      var msg = JSON.parse(event.data);
      if (msg.type === 'assistant_message') {
        appendMessage('assistant', msg.content, msg.citations, agentId);
      } else if (msg.type === 'error') {
        appendMessage('error', msg.content);
      }
    };
  }

  function appendMessage(type, text, citations, agentId) {
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
        chip.href = '/chat/agents/' + agentId + '/sources/' + c.source_id + '/view#' + c.anchor;
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

  function showCreateView() {
    disconnect();
    document.getElementById('doc-agent-create-results').textContent = '';
    showView(createView);
  }

  function submitCreate() {
    var name = document.getElementById('doc-agent-name').value.trim();
    if (!name) return;
    var description = document.getElementById('doc-agent-desc').value.trim();
    var filesInput = document.getElementById('doc-agent-files');
    var resultsEl = document.getElementById('doc-agent-create-results');

    var formData = new FormData();
    formData.append('name', name);
    formData.append('description', description);
    Array.prototype.forEach.call(filesInput.files || [], function (f) {
      formData.append('files', f);
    });

    resultsEl.textContent = 'Creating...';
    fetch('/chat/agents', { method: 'POST', body: formData })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) {
          resultsEl.textContent = 'Error: ' + (res.data.detail || 'could not create assistant');
          return;
        }
        document.getElementById('doc-agent-name').value = '';
        document.getElementById('doc-agent-desc').value = '';
        filesInput.value = '';
        loadAgents(res.data.agent.agent_id);
      })
      .catch(function () { resultsEl.textContent = 'Error creating assistant.'; });
  }

  function deleteCurrentAgent() {
    if (!currentAgent) return;
    if (!window.confirm('Delete "' + currentAgent.name + '" and all its documents? This cannot be undone.')) return;
    fetch('/chat/agents/' + currentAgent.agent_id, { method: 'DELETE' })
      .then(function (r) {
        if (!r.ok) throw new Error('delete failed');
        loadAgents();
      })
      .catch(function () { window.alert('Could not delete the assistant.'); });
  }

  // ── Wiring ──

  document.querySelectorAll('[data-doc-agent-open]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      widget.classList.remove('doc-agent-widget--collapsed');
      loadAgents(currentAgent ? currentAgent.agent_id : null);
    });
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      widget.classList.add('doc-agent-widget--collapsed');
      disconnect();
    });
  }

  if (selectEl) {
    selectEl.addEventListener('change', function () {
      var val = selectEl.value;
      if (val === '__new__') {
        showCreateView();
      } else if (val && agentsById[val]) {
        openAgentChat(agentsById[val]);
      }
    });
  }

  if (deleteBtn) deleteBtn.addEventListener('click', deleteCurrentAgent);

  var emptyCreateBtn = document.getElementById('doc-agent-empty-create');
  if (emptyCreateBtn) emptyCreateBtn.addEventListener('click', showCreateView);

  var createCancel = document.getElementById('doc-agent-create-cancel');
  if (createCancel) {
    createCancel.addEventListener('click', function () {
      if (currentAgent) {
        selectEl.value = currentAgent.agent_id;
        openAgentChat(currentAgent);
      } else {
        loadAgents();
      }
    });
  }

  var createSubmit = document.getElementById('doc-agent-create-submit');
  if (createSubmit) createSubmit.addEventListener('click', submitCreate);

  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      send();
    });
  }

  // The launcher is site-wide but the feature may be disabled server-side --
  // only reveal it once /chat/config confirms it's on.
  if (toggleBtn) {
    fetch('/chat/config')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.allow_document_agents) toggleBtn.style.display = '';
      })
      .catch(function () { /* leave hidden */ });
  }
})();
