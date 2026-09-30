(function () {
  var userId = document.getElementById('userId');
  var gridId = document.getElementById('gridId');
  var voltageLimit = document.getElementById('voltageLimit');
  var scenarioSelect = document.getElementById('scenarioSelect');
  var difficultySelect = document.getElementById('difficultySelect');
  var downloadMsg = document.getElementById('downloadMsg');

  function getOpts() {
    return { limit: voltageLimit.value, scenario: scenarioSelect.value, difficulty: difficultySelect.value };
  }

  // ── Step 1: Download ──

  async function downloadJsonFile(url, filename) {
    downloadMsg.textContent = 'Preparing download...';
    try {
      var res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      var data = await res.json();
      var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      var blobUrl = window.URL.createObjectURL(blob);
      var a = document.createElement('a'); a.href = blobUrl; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(blobUrl);
      downloadMsg.textContent = 'Download started.';
    } catch (e) { downloadMsg.textContent = 'Download failed: ' + e.message; }
  }

  document.getElementById('btnDownloadTrain').addEventListener('click', function () {
    var o = getOpts();
    if (!o.limit) { downloadMsg.textContent = 'Please enter a voltage limit in Benchmark Setup.'; return; }
    downloadJsonFile(
      '/voltage_control_benchmark/training-scenarios?voltage_limit=' + encodeURIComponent(o.limit) + '&Scenario=' + encodeURIComponent(o.scenario) + '&difficulty=' + encodeURIComponent(o.difficulty),
      'training_scenarios_' + o.scenario + '_' + o.difficulty + '.json'
    );
  });

  document.getElementById('btnDownloadControl').addEventListener('click', function () {
    var o = getOpts();
    if (!o.limit) { downloadMsg.textContent = 'Please enter a voltage limit in Benchmark Setup.'; return; }
    downloadJsonFile(
      '/voltage_control_benchmark/voltage-control-data?voltage_limit=' + encodeURIComponent(o.limit) + '&Scenario=' + encodeURIComponent(o.scenario) + '&difficulty=' + encodeURIComponent(o.difficulty),
      'voltage_control_data_' + o.scenario + '_' + o.difficulty + '.json'
    );
  });

  // ── Step 2: Submit ──

  var resultFile = document.getElementById('resultFile');
  var resultDrop = document.getElementById('resultDrop');
  var resultLabel = document.getElementById('resultFileLabel');
  var btnSubmit = document.getElementById('btnSubmit');
  var uploadMsg = document.getElementById('uploadMsg');
  var submitResult = document.getElementById('submitResult');
  var submitResultMsg = document.getElementById('submitResultMsg');

  resultDrop.addEventListener('click', function (e) { e.stopPropagation(); resultFile.value = ''; resultFile.click(); });
  ['dragenter', 'dragover'].forEach(function (ev) { resultDrop.addEventListener(ev, function (e) { e.preventDefault(); resultDrop.classList.add('is-over'); }); });
  ['dragleave', 'dragend'].forEach(function (ev) { resultDrop.addEventListener(ev, function (e) { e.preventDefault(); resultDrop.classList.remove('is-over'); }); });
  resultDrop.addEventListener('drop', function (e) { e.preventDefault(); resultDrop.classList.remove('is-over'); if (e.dataTransfer && e.dataTransfer.files.length) { resultFile.files = e.dataTransfer.files; onFile(); } });
  resultFile.addEventListener('change', onFile);

  function onFile() { var f = resultFile.files[0]; resultLabel.textContent = f ? f.name : 'No file selected'; btnSubmit.disabled = !f; uploadMsg.textContent = ''; submitResult.style.display = 'none'; }

  btnSubmit.addEventListener('click', async function () {
    var user = userId.value.trim(), grid = gridId.value.trim();
    uploadMsg.textContent = ''; submitResult.style.display = 'none';
    if (!user) { uploadMsg.textContent = 'Please enter a Submission ID in Benchmark Setup.'; return; }
    if (!grid) { uploadMsg.textContent = 'Please enter a Grid ID in Benchmark Setup.'; return; }
    if (!resultFile.files.length) { uploadMsg.textContent = 'Please select a results file.'; return; }
    btnSubmit.disabled = true; uploadMsg.textContent = 'Submitting...';
    try {
      var text = await resultFile.files[0].text();
      var guesses; try { guesses = JSON.parse(text); } catch (e) { throw new Error('Invalid JSON: ' + e.message); }
      var res = await fetch('/voltage_control_benchmark/submit-results', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ guess_id: user, grid_id: grid, guesses: guesses }) });
      if (!res.ok) throw new Error(await res.text());
      uploadMsg.textContent = ''; submitResult.style.display = 'block';
      submitResultMsg.textContent = 'Control results for grid "' + grid + '" submitted as user "' + user + '".';
      document.getElementById('scSubmission').textContent = 'Submitted';
    } catch (e) { uploadMsg.textContent = 'Error: ' + e.message; } finally { btnSubmit.disabled = !resultFile.files.length; }
  });

  // ── Step 3: Score ──

  var btnScore = document.getElementById('btnScore');
  var scoreResult = document.getElementById('scoreResult');
  var scoreTable = document.getElementById('scoreTable');
  var scoreDetail = document.getElementById('scoreDetail');
  var scoreError = document.getElementById('scoreError');
  var scoreErrorMsg = document.getElementById('scoreErrorMsg');

  btnScore.addEventListener('click', async function () {
    var user = userId.value.trim(), grid = gridId.value.trim();
    scoreResult.style.display = 'none'; scoreError.style.display = 'none';
    if (!user || !grid) { scoreError.style.display = 'block'; scoreErrorMsg.textContent = 'Please enter both Submission ID and Grid ID in Benchmark Setup.'; return; }
    btnScore.disabled = true;
    try {
      var res = await fetch('/voltage_control_benchmark/score?guess_id=' + encodeURIComponent(user) + '&grid_id=' + encodeURIComponent(grid));
      if (!res.ok) throw new Error(await res.text());
      var data = await res.json();
      scoreResult.style.display = 'block';
      scoreTable.innerHTML = '<tr><th>User</th><td>' + user + '</td></tr>'
        + '<tr><th>Grid</th><td>' + grid + '</td></tr>'
        + '<tr><th>Overall Score</th><td><strong>' + (Number(data.overall_score) * 100).toFixed(2) + '%</strong></td></tr>'
        + '<tr><th>Total Nodes</th><td>' + data.total_nodes + '</td></tr>';
      document.getElementById('scScore').textContent = (Number(data.overall_score) * 100).toFixed(1) + '%';

      var detail = '';
      (data.per_timestamp || []).forEach(function (t) {
        detail += t.datetime + ' (key: ' + t.anonymised_key + ')\n';
        detail += '  nodes: ' + t.nodes_total;
        if (typeof t.average_node_score !== 'undefined') detail += ', avg_score: ' + t.average_node_score;
        detail += ', effort: ' + t.effort_norm + ', factor: ' + t.effort_factor + ', ts_score: ' + t.timestamp_score + '\n\n';
      });
      scoreDetail.textContent = detail || 'No per-timestamp data.';
    } catch (e) { scoreError.style.display = 'block'; scoreErrorMsg.textContent = e.message; } finally { btnScore.disabled = false; }
  });
})();
