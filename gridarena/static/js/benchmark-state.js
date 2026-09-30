(function () {
  var userId = document.getElementById('userId');
  var estimationId = document.getElementById('estimationId');
  var noiseSelect = document.getElementById('noiseSelect');
  var obsSelect = document.getElementById('obsSelect');
  var downloadMsg = document.getElementById('downloadMsg');

  function getNoise() { return noiseSelect.value; }
  function getObs() { return obsSelect.value; }

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
    var noise = getNoise(), obs = getObs();
    downloadJsonFile(
      '/state_estimation_benchmark/training-state-data?noise_difficulty=' + encodeURIComponent(noise) + '&observability=' + encodeURIComponent(obs),
      'training_state_data_' + noise + '_' + obs + '.json'
    );
  });

  document.getElementById('btnDownloadInput').addEventListener('click', function () {
    var user = userId.value.trim();
    if (!user) { downloadMsg.textContent = 'Please enter your User ID in Benchmark Setup.'; return; }
    var noise = getNoise(), obs = getObs();
    downloadJsonFile(
      '/state_estimation_benchmark/state-data?user_id=' + encodeURIComponent(user) + '&noise_difficulty=' + encodeURIComponent(noise) + '&observability=' + encodeURIComponent(obs),
      'state_estimation_input_' + user + '_' + noise + '_' + obs + '.json'
    );
  });

  // ── Step 2: Submit ──

  var estimateFile = document.getElementById('estimateFile');
  var estimateDrop = document.getElementById('estimateDrop');
  var estimateLabel = document.getElementById('estimateFileLabel');
  var btnSubmit = document.getElementById('btnSubmit');
  var uploadMsg = document.getElementById('uploadMsg');
  var submitResult = document.getElementById('submitResult');
  var submitResultMsg = document.getElementById('submitResultMsg');

  estimateDrop.addEventListener('click', function (e) { e.stopPropagation(); estimateFile.value = ''; estimateFile.click(); });
  ['dragenter', 'dragover'].forEach(function (ev) { estimateDrop.addEventListener(ev, function (e) { e.preventDefault(); estimateDrop.classList.add('is-over'); }); });
  ['dragleave', 'dragend'].forEach(function (ev) { estimateDrop.addEventListener(ev, function (e) { e.preventDefault(); estimateDrop.classList.remove('is-over'); }); });
  estimateDrop.addEventListener('drop', function (e) { e.preventDefault(); estimateDrop.classList.remove('is-over'); if (e.dataTransfer && e.dataTransfer.files.length) { estimateFile.files = e.dataTransfer.files; onFile(); } });
  estimateFile.addEventListener('change', onFile);

  function onFile() { var f = estimateFile.files[0]; estimateLabel.textContent = f ? f.name : 'No file selected'; btnSubmit.disabled = !f; uploadMsg.textContent = ''; submitResult.style.display = 'none'; }

  btnSubmit.addEventListener('click', async function () {
    var user = userId.value.trim(), est = estimationId.value.trim();
    uploadMsg.textContent = ''; submitResult.style.display = 'none';
    if (!user) { uploadMsg.textContent = 'Please enter your User ID in Benchmark Setup.'; return; }
    if (!est) { uploadMsg.textContent = 'Please enter an Estimation Task ID in Benchmark Setup.'; return; }
    if (!estimateFile.files.length) { uploadMsg.textContent = 'Please select an estimate file.'; return; }
    btnSubmit.disabled = true; uploadMsg.textContent = 'Submitting...';
    try {
      var text = await estimateFile.files[0].text();
      var estimates; try { estimates = JSON.parse(text); } catch (e) { throw new Error('Invalid JSON: ' + e.message); }
      var res = await fetch('/state_estimation_benchmark/submit-estimates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: user, estimation_id: est, grid_id: estimates.grid_id, estimates: estimates.estimates, timestamp: estimates.timestamp })
      });
      if (!res.ok) throw new Error(await res.text());
      uploadMsg.textContent = ''; submitResult.style.display = 'block';
      submitResultMsg.textContent = 'Estimates submitted for task "' + est + '" as user "' + user + '".';
      document.getElementById('scSubmission').textContent = 'Submitted';
    } catch (e) { uploadMsg.textContent = 'Error: ' + e.message; } finally { btnSubmit.disabled = !estimateFile.files.length; }
  });

  // ── Step 3: Score ──

  var btnScore = document.getElementById('btnScore');
  var scoreResult = document.getElementById('scoreResult');
  var scoreTable = document.getElementById('scoreTable');
  var scoreError = document.getElementById('scoreError');
  var scoreErrorMsg = document.getElementById('scoreErrorMsg');

  btnScore.addEventListener('click', async function () {
    var user = userId.value.trim(), est = estimationId.value.trim();
    scoreResult.style.display = 'none'; scoreError.style.display = 'none';
    if (!user || !est) { scoreError.style.display = 'block'; scoreErrorMsg.textContent = 'Please enter both User ID and Estimation Task ID in Benchmark Setup.'; return; }
    btnScore.disabled = true;
    try {
      var res = await fetch('/state_estimation_benchmark/state-score?user_id=' + encodeURIComponent(user) + '&estimation_id=' + encodeURIComponent(est));
      if (!res.ok) throw new Error(await res.text());
      var data = await res.json();
      scoreResult.style.display = 'block';
      scoreTable.innerHTML = '<tr><th>User</th><td>' + data.user_id + '</td></tr>'
        + '<tr><th>Estimation Task</th><td>' + data.estimation_id + '</td></tr>'
        + '<tr><th>Score (SSE)</th><td><strong>' + Number(data.score).toFixed(6) + '</strong></td></tr>';
      document.getElementById('scScore').textContent = Number(data.score).toFixed(4);
    } catch (e) { scoreError.style.display = 'block'; scoreErrorMsg.textContent = e.message; } finally { btnScore.disabled = false; }
  });
})();
