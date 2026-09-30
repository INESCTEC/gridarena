(function () {
  var userId = document.getElementById('userId');
  var gridId = document.getElementById('gridId');
  var difficultySelect = document.getElementById('difficultySelect');
  var downloadMsg = document.getElementById('downloadMsg');

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
      document.getElementById('scDataset').textContent = 'Downloaded';
    } catch (e) { downloadMsg.textContent = 'Download failed: ' + e.message; }
  }

  document.getElementById('btnDownloadTrain').addEventListener('click', function () {
    var diff = difficultySelect.value;
    downloadJsonFile('/topology_discovery_benchmark/training-topology-data?difficulty=' + encodeURIComponent(diff), 'training_topology_data_' + diff + '.json');
  });

  document.getElementById('btnDownloadHidden').addEventListener('click', function () {
    var diff = difficultySelect.value;
    downloadJsonFile('/topology_discovery_benchmark/topology-data?difficulty=' + encodeURIComponent(diff), 'topology_data_' + diff + '.json');
  });

  // ── Step 2: Submit ──

  var guessFile = document.getElementById('guessFile');
  var guessDrop = document.getElementById('guessDrop');
  var guessLabel = document.getElementById('guessFileLabel');
  var btnSubmit = document.getElementById('btnSubmit');
  var uploadMsg = document.getElementById('uploadMsg');
  var submitResult = document.getElementById('submitResult');
  var submitResultMsg = document.getElementById('submitResultMsg');

  guessDrop.addEventListener('click', function (e) { e.stopPropagation(); guessFile.value = ''; guessFile.click(); });
  ['dragenter', 'dragover'].forEach(function (ev) { guessDrop.addEventListener(ev, function (e) { e.preventDefault(); guessDrop.classList.add('is-over'); }); });
  ['dragleave', 'dragend'].forEach(function (ev) { guessDrop.addEventListener(ev, function (e) { e.preventDefault(); guessDrop.classList.remove('is-over'); }); });
  guessDrop.addEventListener('drop', function (e) { e.preventDefault(); guessDrop.classList.remove('is-over'); if (e.dataTransfer && e.dataTransfer.files.length) { guessFile.files = e.dataTransfer.files; onFile(); } });
  guessFile.addEventListener('change', onFile);

  function onFile() { var f = guessFile.files[0]; guessLabel.textContent = f ? f.name : 'No file selected'; btnSubmit.disabled = !f; uploadMsg.textContent = ''; submitResult.style.display = 'none'; }

  btnSubmit.addEventListener('click', async function () {
    var user = userId.value.trim(), grid = gridId.value.trim();
    uploadMsg.textContent = ''; submitResult.style.display = 'none';
    if (!user) { uploadMsg.textContent = 'Please enter a Submission ID in Benchmark Setup.'; return; }
    if (!grid) { uploadMsg.textContent = 'Please enter a Grid ID in Benchmark Setup.'; return; }
    if (!guessFile.files.length) { uploadMsg.textContent = 'Please select a prediction file.'; return; }
    btnSubmit.disabled = true; uploadMsg.textContent = 'Submitting...';
    try {
      var text = await guessFile.files[0].text();
      var guesses; try { guesses = JSON.parse(text); } catch (e) { throw new Error('Invalid JSON: ' + e.message); }
      var res = await fetch('/topology_discovery_benchmark/submit-results', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ guess_id: user, grid_id: grid, guesses: guesses }) });
      if (!res.ok) throw new Error(await res.text());
      uploadMsg.textContent = ''; submitResult.style.display = 'block'; submitResultMsg.textContent = 'Topology predictions for grid "' + grid + '" submitted.';
      document.getElementById('scSubmission').textContent = 'Submitted';
    } catch (e) { uploadMsg.textContent = 'Error: ' + e.message; } finally { btnSubmit.disabled = !guessFile.files.length; }
  });

  // ── Step 3: Score ──

  var btnScore = document.getElementById('btnScore');
  var scoreResult = document.getElementById('scoreResult');
  var scoreTable = document.getElementById('scoreTable');
  var scoreError = document.getElementById('scoreError');
  var scoreErrorMsg = document.getElementById('scoreErrorMsg');

  btnScore.addEventListener('click', async function () {
    var user = userId.value.trim(), grid = gridId.value.trim();
    scoreResult.style.display = 'none'; scoreError.style.display = 'none';
    if (!user || !grid) { scoreError.style.display = 'block'; scoreErrorMsg.textContent = 'Please enter both Submission ID and Grid ID in Benchmark Setup.'; return; }
    btnScore.disabled = true;
    try {
      var res = await fetch('/topology_discovery_benchmark/score?guess_id=' + encodeURIComponent(user) + '&grid_id=' + encodeURIComponent(grid));
      if (!res.ok) throw new Error(await res.text());
      var data = await res.json();
      scoreResult.style.display = 'block';
      scoreTable.innerHTML = '<tr><th>User</th><td>' + data.guess_id + '</td></tr>'
        + '<tr><th>Grid</th><td>' + data.grid_id + '</td></tr>'
        + '<tr><th>Accuracy</th><td><strong>' + (data.accuracy * 100).toFixed(2) + '%</strong></td></tr>'
        + '<tr><th>Correct Edges</th><td>' + data.correct + ' / ' + data.total_true_edges + '</td></tr>'
        + '<tr><th>Extra Edges</th><td>' + data.incorrect_extra + '</td></tr>'
        + '<tr><th>Missed Edges</th><td>' + data.missed + '</td></tr>';
      document.getElementById('scScore').textContent = (data.accuracy * 100).toFixed(1) + '%';
    } catch (e) { scoreError.style.display = 'block'; scoreErrorMsg.textContent = e.message; } finally { btnScore.disabled = false; }
  });
})();
