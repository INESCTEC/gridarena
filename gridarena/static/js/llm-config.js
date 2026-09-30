(function () {
  var selectedIdx = -1;

  window.selectAgent = function (idx) {
    var agent = AGENTS[idx];
    if (!agent) return;

    var cards = document.querySelectorAll('.llm-agent-card');
    cards.forEach(function (c) { c.classList.remove('llm-agent-card--selected'); });
    var card = document.querySelector('[data-agent-idx="' + idx + '"]');
    if (card) card.classList.add('llm-agent-card--selected');

    selectedIdx = idx;

    document.getElementById('detailName').textContent = agent.name;
    document.getElementById('detailDesc').textContent = agent.description;

    var tbody = document.getElementById('detailTools');
    tbody.innerHTML = '';
    agent.tools.forEach(function (t) {
      var tr = document.createElement('tr');
      tr.innerHTML = '<td><code>' + t.name + '</code></td><td style="font-size:12px;">' + (t.description || '—') + '</td>';
      tbody.appendChild(tr);
    });

    var kwDiv = document.getElementById('detailKeywords');
    kwDiv.innerHTML = '';
    agent.keywords.forEach(function (kw) {
      var span = document.createElement('span');
      span.className = 'llm-tag';
      span.textContent = kw;
      kwDiv.appendChild(span);
    });

    var ragP = document.getElementById('detailRag');
    if (agent.has_rag_docs) {
      ragP.innerHTML = 'Embedded from <code>' + agent.rag_doc_file + '</code>';
    } else {
      ragP.textContent = 'No RAG documentation configured.';
    }

    document.getElementById('agentDetail').style.display = '';
    document.getElementById('agentDetail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };

  window.closeDetail = function () {
    document.getElementById('agentDetail').style.display = 'none';
    var cards = document.querySelectorAll('.llm-agent-card');
    cards.forEach(function (c) { c.classList.remove('llm-agent-card--selected'); });
    selectedIdx = -1;
  };

})();
