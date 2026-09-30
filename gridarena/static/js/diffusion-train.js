(function () {

  // ── Grid selection (text input + autocomplete) ──

  var selectedGrids = new Set();

  // Known grid IDs from the datalist, for a soft "unknown grid" hint.
  var knownGrids = new Set(
    Array.prototype.map.call(
      document.querySelectorAll('#gridOptions option'),
      function (o) { return o.value; }
    )
  );

  function renderSelectedGrids() {
    var list = document.getElementById('selectedGridList');
    var hint = document.getElementById('noGridsHint');
    list.querySelectorAll('.grid-chip').forEach(function (c) { c.remove(); });

    if (selectedGrids.size === 0) {
      hint.style.display = '';
      return;
    }
    hint.style.display = 'none';
    selectedGrids.forEach(function (gid) {
      var chip = document.createElement('span');
      chip.className = 'grid-chip grid-chip--selected';
      chip.textContent = gid + '  ✕';
      chip.title = 'Remove ' + gid;
      chip.style.cursor = 'pointer';
      if (!knownGrids.has(gid)) {
        chip.style.borderColor = '#f59e0b';
        chip.title = gid + ' is not in the known grid list — training will fail if it does not exist. Click to remove.';
      }
      chip.addEventListener('click', function () { removeGrid(gid); });
      list.appendChild(chip);
    });
  }

  function addGrid(gid) {
    gid = (gid || '').trim();
    if (!gid || selectedGrids.has(gid)) { return; }
    selectedGrids.add(gid);
    renderSelectedGrids();
    updateDataPreview();
    updateReview();
  }

  function removeGrid(gid) {
    selectedGrids.delete(gid);
    renderSelectedGrids();
    updateDataPreview();
    updateReview();
  }

  function getSelectedGrids() { return Array.from(selectedGrids); }

  var gridInput = document.getElementById('gridInput');
  var addGridBtn = document.getElementById('addGridBtn');

  function commitGridInput() {
    addGrid(gridInput.value);
    gridInput.value = '';
    gridInput.focus();
  }

  addGridBtn.addEventListener('click', commitGridInput);
  gridInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); commitGridInput(); }
  });
  // Picking a value from the autocomplete dropdown adds it immediately.
  gridInput.addEventListener('change', function () {
    if (knownGrids.has(gridInput.value.trim())) { commitGridInput(); }
  });

  renderSelectedGrids();

  // ── Shared payload (data selection + architecture + core hyperparams) ──

  function basePayload(gridIds) {
    return {
      grid_ids: gridIds,
      architecture: document.getElementById('architecture').value || 'axial',
      phase: document.getElementById('phase').value || null,
      start: document.getElementById('startDt').value || null,
      end: document.getElementById('endDt').value || null,
      p_min: document.getElementById('pMin').value ? parseFloat(document.getElementById('pMin').value) : null,
      p_max: document.getElementById('pMax').value ? parseFloat(document.getElementById('pMax').value) : null,
      num_epochs: parseInt(document.getElementById('numEpochs').value) || 75,
      train_batch_size: parseInt(document.getElementById('batchSize').value) || 16,
      learning_rate: parseFloat(document.getElementById('learningRate').value) || 1e-4,
      lr_warmup_steps: parseInt(document.getElementById('warmupSteps').value) || 500,
      power_subtract: document.getElementById('powerSubtractMode').value === 'auto' ? 'auto' : parseFloat(document.getElementById('powerSubtractCustom').value) || 5.62,
      power_rescale: document.getElementById('powerRescaleMode').value === 'auto' ? 'auto' : parseFloat(document.getElementById('powerRescaleCustom').value) || 18.46
    };
  }

  // Fire a background job and reload to reveal the new run row.
  async function launchJob(url, payload, msgEl, btnEl) {
    var grids = payload.grid_ids;
    if (!grids.length) { msgEl.textContent = 'Please select at least one grid.'; return; }
    msgEl.textContent = 'Starting...';
    btnEl.disabled = true;
    try {
      var res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      msgEl.textContent = data.message + ' — Run ID: ' + data.run_id;
      setTimeout(function () { location.reload(); }, 2500);
    } catch (err) {
      msgEl.textContent = 'Error: ' + err.message;
    } finally {
      btnEl.disabled = false;
    }
  }

  // ── Data preview ──

  function updateDataPreview() {
    var el = document.getElementById('dataPreview');
    var grids = getSelectedGrids();
    if (!grids.length) { el.textContent = 'No grids selected.'; return; }
    var phase = document.getElementById('phase').value || 'All';
    var start = document.getElementById('startDt').value || 'Any';
    var end = document.getElementById('endDt').value || 'Any';
    el.innerHTML = '<strong>' + grids.length + ' grid(s) selected:</strong> ' + grids.join(', ')
      + ' &bull; Phase: ' + phase + ' &bull; Range: ' + start + ' to ' + end;
  }

  document.getElementById('phase').addEventListener('change', function () { updateDataPreview(); updateReview(); });

  // ── Presets ──

  var presets = {
    fast: { epochs: 10, batch: 16, lr: 0.001, warmup: 100 },
    balanced: { epochs: 75, batch: 16, lr: 0.0001, warmup: 500 },
    quality: { epochs: 200, batch: 8, lr: 0.00005, warmup: 1000 }
  };

  window.applyPreset = function (name) {
    var p = presets[name];
    document.getElementById('numEpochs').value = p.epochs;
    document.getElementById('batchSize').value = p.batch;
    document.getElementById('learningRate').value = p.lr;
    document.getElementById('warmupSteps').value = p.warmup;
    document.querySelectorAll('.preset-btn').forEach(function (b) { b.classList.remove('active'); });
    event.target.classList.add('active');
    updateReview();
  };

  // ── DP toggle ──

  window.toggleDp = function () {
    var enabled = document.getElementById('dpEnabled').checked;
    document.getElementById('dpParams').style.display = enabled ? 'block' : 'none';
    var card = document.getElementById('dpCard');
    var status = document.getElementById('dpStatus');
    if (enabled) {
      card.classList.add('dp-card--enabled');
      status.textContent = 'Enabled';
      status.className = 'dp-status dp-status--on';
      document.getElementById('scDp').textContent = 'Enabled';
    } else {
      card.classList.remove('dp-card--enabled');
      status.textContent = 'Disabled';
      status.className = 'dp-status dp-status--off';
      document.getElementById('scDp').textContent = 'Disabled';
    }
    updateReview();
  };

  // ── Review ──

  function updateReview() {
    var grids = getSelectedGrids();
    var phase = document.getElementById('phase').value || 'All';
    var epochs = document.getElementById('numEpochs').value;
    var batch = document.getElementById('batchSize').value;
    var lr = document.getElementById('learningRate').value;
    var dp = document.getElementById('dpEnabled').checked ? 'Enabled' : 'Disabled';
    var subMode = document.getElementById('powerSubtractMode').value;
    var rescMode = document.getElementById('powerRescaleMode').value;

    var arch = document.getElementById('architecture').value;

    var html = '<dt>Grids</dt><dd>' + (grids.length ? grids.join(', ') : '<em>None selected</em>') + '</dd>'
      + '<dt>Architecture</dt><dd>' + arch + '</dd>'
      + '<dt>Phase</dt><dd>' + phase + '</dd>'
      + '<dt>Epochs</dt><dd>' + epochs + '</dd>'
      + '<dt>Batch Size</dt><dd>' + batch + '</dd>'
      + '<dt>Learning Rate</dt><dd>' + lr + '</dd>'
      + '<dt>Normalisation</dt><dd>subtract: ' + subMode + ', rescale: ' + rescMode + '</dd>'
      + '<dt>Differential Privacy</dt><dd>' + dp + '</dd>';

    document.getElementById('reviewGrid').innerHTML = html;
  }

  // Listen for changes on key fields
  ['numEpochs', 'batchSize', 'learningRate', 'warmupSteps', 'architecture'].forEach(function (id) {
    document.getElementById(id).addEventListener('change', updateReview);
  });
  updateReview();

  // ── Diagnostics: privacy check & epoch search ──

  document.getElementById('privacyBtn').addEventListener('click', function () {
    var payload = Object.assign(basePayload(getSelectedGrids()), {
      val_frac: parseFloat(document.getElementById('pcValFrac').value) || 0.2,
      buffer_days: parseInt(document.getElementById('pcBufferDays').value) || 0,
      num_canaries: parseInt(document.getElementById('pcNumCanaries').value) || 5,
      num_generated_samples: parseInt(document.getElementById('pcNumGenerated').value) || 128
    });
    launchJob('/diffusion/privacy-check', payload,
      document.getElementById('privacyMsg'), document.getElementById('privacyBtn'));
  });

  document.getElementById('epochBtn').addEventListener('click', function () {
    var payload = Object.assign(basePayload(getSelectedGrids()), {
      max_epochs: parseInt(document.getElementById('esMaxEpochs').value) || 75,
      checkpoint_interval: parseInt(document.getElementById('esCheckpointInterval').value) || 10,
      val_frac: parseFloat(document.getElementById('esValFrac').value) || 0.2,
      sweep_inference_steps: parseInt(document.getElementById('esSweepSteps').value) || 100
    });
    launchJob('/diffusion/epoch-search', payload,
      document.getElementById('epochMsg'), document.getElementById('epochBtn'));
  });

  // ── Submit ──

  var form = document.getElementById('trainForm');
  var msg = document.getElementById('trainMsg');
  var trainResult = document.getElementById('trainResult');
  var trainResultMsg = document.getElementById('trainResultMsg');

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var gridIds = getSelectedGrids();
    msg.textContent = ''; trainResult.style.display = 'none';

    if (!gridIds.length) { msg.textContent = 'Please select at least one grid.'; return; }

    var payload = Object.assign(basePayload(gridIds), {
      dp_enabled: document.getElementById('dpEnabled').checked,
      dp_max_grad_norm: parseFloat(document.getElementById('dpMaxGradNorm').value) || 1.0,
      dp_noise_multiplier: parseFloat(document.getElementById('dpNoiseMultiplier').value) || 1.0,
      dp_target_delta: parseFloat(document.getElementById('dpTargetDelta').value) || 1e-5
    });

    msg.textContent = 'Starting training...';
    document.getElementById('trainBtn').disabled = true;

    try {
      var res = await fetch('/diffusion/train', {
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
    if (cells && cells[6]) {
      var txt = cells[6].textContent.trim().toLowerCase();
      if (txt === 'queued' || txt === 'running') hasActive = true;
    }
  });
  if (hasActive) { setTimeout(function () { location.reload(); }, 10000); }

})();
