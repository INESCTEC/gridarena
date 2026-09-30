(function () {

  // ── Grid preview ──

  window.updateGridPreview = function () {
    var el = document.getElementById('gridPreview');
    var gid = document.getElementById('gridId').value;
    if (!gid) { el.textContent = 'No grid selected.'; return; }
    el.innerHTML = '<strong>Selected:</strong> ' + gid;
    updateReview();
  };

  // ── Agent type cards ──

  window.selectAgent = function (type) {
    document.getElementById('agentType').value = type;
    var single = document.getElementById('chipSingle');
    var multi = document.getElementById('chipMulti');
    if (type === 'single') {
      single.classList.add('grid-chip--selected'); multi.classList.remove('grid-chip--selected');
      document.getElementById('scAgent').textContent = 'Single';
    } else {
      multi.classList.add('grid-chip--selected'); single.classList.remove('grid-chip--selected');
      document.getElementById('scAgent').textContent = 'Multi';
    }
    updateReview();
  };

  // ── Presets ──

  var presets = { quick: 1000, balanced: 5000, long: 50000 };

  window.applyPreset = function (name) {
    document.getElementById('timesteps').value = presets[name];
    document.querySelectorAll('.preset-btn').forEach(function (b) { b.classList.remove('active'); });
    event.target.classList.add('active');
    updateReview();
  };

  // ── Wrapper toggle ──

  window.toggleWrapChip = function (cb) {
    var label = cb.closest('.grid-chip');
    if (cb.checked) { label.classList.add('grid-chip--selected'); }
    else { label.classList.remove('grid-chip--selected'); }
    updateReview();
  };

  function getSelectedWrappers() {
    var wrappers = [];
    document.querySelectorAll('input[name="wrapper"]:checked').forEach(function (cb) { wrappers.push(cb.value); });
    return wrappers;
  }

  // ── Review ──

  function updateReview() {
    var grid = document.getElementById('gridId').value || 'None';
    var agent = document.getElementById('agentType').value;
    var ts = document.getElementById('timesteps').value;
    var vt = document.getElementById('violationThreshold').value;
    var rs = document.getElementById('rewardScale').value;
    var pmin = document.getElementById('pMin').value;
    var pmax = document.getElementById('pMax').value;
    var vref = document.getElementById('voltRef').value;
    var adm = document.getElementById('admittanceScale').value;
    var wraps = getSelectedWrappers();

    document.getElementById('reviewGrid').innerHTML =
      '<dt>Grid</dt><dd>' + grid + '</dd>'
      + '<dt>Agent Type</dt><dd>' + agent + '</dd>'
      + '<dt>Timesteps</dt><dd>' + ts + '</dd>'
      + '<dt>Violation Threshold</dt><dd>' + vt + '</dd>'
      + '<dt>Reward Scale</dt><dd>' + rs + '</dd>'
      + '<dt>Power Range</dt><dd>' + pmin + ' to ' + pmax + ' kW</dd>'
      + '<dt>Voltage Ref</dt><dd>' + vref + ' V</dd>'
      + '<dt>Admittance Scale</dt><dd>' + adm + '</dd>'
      + '<dt>Wrappers</dt><dd>' + (wraps.length ? wraps.join(', ') : 'None') + '</dd>';
  }

  ['gridId', 'timesteps', 'violationThreshold', 'rewardScale', 'pMin', 'pMax', 'voltRef', 'admittanceScale'].forEach(function (id) {
    document.getElementById(id).addEventListener('change', updateReview);
  });
  updateReview();

  // ── Submit ──

  var form = document.getElementById('trainForm');
  var msg = document.getElementById('trainMsg');
  var trainResult = document.getElementById('trainResult');
  var trainResultMsg = document.getElementById('trainResultMsg');

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var gridId = document.getElementById('gridId').value;
    msg.textContent = ''; trainResult.style.display = 'none';

    if (!gridId) { msg.textContent = 'Please select a grid.'; return; }

    var payload = {
      grid_id: gridId,
      agent_type: document.getElementById('agentType').value,
      timesteps: parseInt(document.getElementById('timesteps').value) || 5000,
      violation_threshold: parseFloat(document.getElementById('violationThreshold').value) || 0.1,
      reward_scale: parseFloat(document.getElementById('rewardScale').value) || 100,
      p_min_kw: parseFloat(document.getElementById('pMin').value) || -20,
      p_max_kw: parseFloat(document.getElementById('pMax').value) || 30,
      volt_ref: parseFloat(document.getElementById('voltRef').value) || 230,
      admittance_scale: parseFloat(document.getElementById('admittanceScale').value) || 1.0,
      active_wrappers: getSelectedWrappers()
    };

    msg.textContent = 'Starting training...';
    document.getElementById('trainBtn').disabled = true;

    try {
      var res = await fetch('/rl/train', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      msg.textContent = '';
      trainResult.style.display = 'block';
      trainResultMsg.textContent = data.message + ' — Run ID: ' + data.run_id;
      setTimeout(function () { location.reload(); }, 3000);
    } catch (err) {
      msg.textContent = 'Error: ' + err.message;
    } finally {
      document.getElementById('trainBtn').disabled = false;
    }
  });

  // ── Poll active runs ──

  var hasActive = false;
  document.querySelectorAll('#runsTable tbody tr').forEach(function (row) {
    var cells = row.cells;
    if (cells && cells[5]) {
      var txt = cells[5].textContent.trim().toLowerCase();
      if (txt === 'queued' || txt === 'running') hasActive = true;
    }
  });
  if (hasActive) { setTimeout(function () { location.reload(); }, 10000); }

})();
