/**
 * PF Data Generation tab on the MV grids home page (/mv_grid/ui).
 * Lets the user pick one or more MV grids and run the same perturbation
 * config against each -- one POST /pf-datagen/mv/{grid_id}/run per grid.
 */
(function () {

  // ── Grid picker ──

  window.pfFilterGridChecklist = function () {
    var q = document.getElementById('pfGridSearch').value.toLowerCase();
    document.querySelectorAll('#pfGridChecklist .pf-grid-row').forEach(function (row) {
      var id = row.getAttribute('data-grid-id') || '';
      row.style.display = id.indexOf(q) !== -1 ? '' : 'none';
    });
  };

  window.pfSelectAllVisible = function () {
    document.querySelectorAll('#pfGridChecklist .pf-grid-row').forEach(function (row) {
      if (row.style.display !== 'none') {
        var cb = row.querySelector('.pfGridCheckbox');
        if (cb) cb.checked = true;
      }
    });
    pfUpdateSelectedCount();
  };

  window.pfClearSelection = function () {
    document.querySelectorAll('.pfGridCheckbox').forEach(function (cb) { cb.checked = false; });
    pfUpdateSelectedCount();
  };

  window.pfUpdateSelectedCount = function () {
    var n = document.querySelectorAll('.pfGridCheckbox:checked').length;
    document.getElementById('pfSelectedCount').textContent = n + ' grid' + (n === 1 ? '' : 's') + ' selected';
  };

  function pfSelectedGridIds() {
    return Array.prototype.slice.call(document.querySelectorAll('.pfGridCheckbox:checked'))
      .map(function (cb) { return cb.value; });
  }

  // ── Data source (Historical database) picker ──

  var pfDatabases = [];
  var pfDatabasesLoading = true;
  var pfDatabasesFetchError = null;

  (async function pfLoadHistoricalDatabases() {
    var select = document.getElementById('pfHistoricalDatabase');
    var info = document.getElementById('pfHistoricalDatabaseInfo');
    var startBtn = document.getElementById('pfStartBtn');
    if (!select) return;

    if (startBtn) {
      startBtn.disabled = true;
      startBtn.textContent = 'Loading data source...';
    }

    try {
      var res = await fetch('/historical/databases');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var databases = await res.json();
      pfDatabases = databases;

      select.innerHTML = '';
      if (!databases.length) {
        select.innerHTML = '<option value="">No historical databases yet</option>';
        info.textContent = 'Upload one on the Historical page first.';
        return;
      }

      var usable = databases.filter(function (d) { return d.grid_level !== 'Mixed' && d.grid_level !== 'Empty'; });
      if (!usable.length) {
        info.textContent = 'No usable databases -- every one mixes grid levels or has no series. Upload a homogeneous database on the Historical page.';
      }

      databases.forEach(function (d) {
        var opt = document.createElement('option');
        opt.value = d.database_id;
        var disabled = d.grid_level === 'Mixed' || d.grid_level === 'Empty';
        opt.disabled = disabled;
        opt.textContent = d.database_id + (d.name ? ' (' + d.name + ')' : '') + ' -- ' + d.grid_level
          + (disabled ? ' [not usable]' : '') + ' -- ' + d.n_series + ' series';
        select.appendChild(opt);
      });

      select.addEventListener('change', function () {
        var d = databases.find(function (x) { return x.database_id === select.value; });
        info.textContent = d ? (d.n_series + ' series, ' + d.n_records + ' records, detected level: ' + d.grid_level) : '';
      });
      if (usable.length) {
        select.value = usable[0].database_id;
        select.dispatchEvent(new Event('change'));
      }
    } catch (err) {
      pfDatabasesFetchError = err.message;
      select.innerHTML = '<option value="">Failed to load databases</option>';
      info.textContent = 'Error: ' + err.message;
    } finally {
      pfDatabasesLoading = false;
      if (startBtn) {
        startBtn.disabled = false;
        startBtn.textContent = 'Start Run(s)';
      }
    }
  })();

  // ── Config form ──

  window.pfDatagenToggleTopologyFields = function () {
    var type = document.getElementById('pfTopologyType').value;
    document.getElementById('pfTopologyFields').style.display = type === 'none' ? 'none' : 'block';
    document.getElementById('pfNVariantsField').style.display = type === 'random' ? 'flex' : 'none';
  };

  function pfSetMsg(el, text, isError) {
    el.textContent = text;
    el.style.color = isError ? '#dc2626' : '';
    el.style.fontWeight = isError ? '600' : '';
  }

  var pfDatagenForm = document.getElementById('pfDatagenForm');
  if (pfDatagenForm) {
    pfDatagenForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      var msg = document.getElementById('pfDatagenMsg');

      try {
        var problems = [];

        var gridIds = pfSelectedGridIds();
        if (gridIds.length === 0) {
          problems.push('Select at least one MV grid (step 1).');
        }

        var dbSelect = document.getElementById('pfHistoricalDatabase');
        var historicalDatabaseId = dbSelect.value;
        if (pfDatabasesLoading) {
          problems.push('Still loading historical databases -- wait a moment and try again.');
        } else if (pfDatabasesFetchError) {
          problems.push('Could not load historical databases (' + pfDatabasesFetchError + ') -- reload the page and try again.');
        } else if (!pfDatabases.length) {
          problems.push('No historical databases exist yet -- upload one on the Historical page first (step 2).');
        } else if (!historicalDatabaseId) {
          problems.push('Select a historical database as the data source (step 2).');
        } else {
          var selectedOpt = dbSelect.options[dbSelect.selectedIndex];
          if (!selectedOpt || selectedOpt.disabled) {
            problems.push('The selected historical database is not usable -- it mixes grid levels or has no series. Pick a homogeneous MV/LV/Feeder database (step 2).');
          }
        }

        if (problems.length) {
          pfSetMsg(msg, 'Cannot start run(s): ' + problems.join(' '), true);
          return;
        }

        var seedVal = document.getElementById('pfSeed').value;
        var payload = {
          historical_database_id: historicalDatabaseId,
          reassignment_period_timesteps: parseInt(document.getElementById('pfReassignmentPeriod').value, 10) || 100,
          scenario_count: parseInt(document.getElementById('pfScenarioCount').value, 10) || 1000,
          load_noise_sigma: parseFloat(document.getElementById('pfLoadNoiseSigma').value) || 0,
          topology_perturbation: {
            type: document.getElementById('pfTopologyType').value,
            k: parseInt(document.getElementById('pfTopologyK').value, 10) || 1,
            n_variants: parseInt(document.getElementById('pfNVariants').value, 10) || 10
          },
          admittance_perturbation: {
            enabled: document.getElementById('pfAdmittanceEnabled').checked,
            sigma: parseFloat(document.getElementById('pfAdmittanceSigma').value) || 0.2
          },
          chunk_commit_size: parseInt(document.getElementById('pfChunkCommitSize').value, 10) || 100,
          seed: seedVal ? parseInt(seedVal, 10) : null
        };

        pfSetMsg(msg, 'Starting ' + gridIds.length + ' run(s)...', false);

        var results = await Promise.all(gridIds.map(async function (gridId) {
          try {
            var res = await fetch('/pf-datagen/mv/' + encodeURIComponent(gridId) + '/run', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            });
            var data = await res.json();
            if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : 'Failed to start run');
            return { gridId: gridId, ok: true };
          } catch (err) {
            return { gridId: gridId, ok: false, error: err.message };
          }
        }));

        var started = results.filter(function (r) { return r.ok; });
        var failed = results.filter(function (r) { return !r.ok; });

        var text = 'Started ' + started.length + ' run(s).';
        if (failed.length) {
          text += ' Failed for: ' + failed.map(function (r) { return r.gridId + ' (' + r.error + ')'; }).join(', ');
        }
        pfSetMsg(msg, text, failed.length > 0);

        if (started.length) {
          setTimeout(function () { location.reload(); }, 2000);
        }
      } catch (err) {
        pfSetMsg(msg, 'Unexpected error starting run(s): ' + err.message, true);
      }
    });
  }

  // Poll (via full reload, same pattern as diffusion-train.js) while any run is active.
  (function pollActivePFRuns() {
    var rows = document.querySelectorAll('#pfRunsTableBody tr[id^="pfRunRow-"]');
    var hasActive = false;
    rows.forEach(function (row) {
      var statusEl = row.querySelector('[id^="pfRunStatus-"]');
      if (statusEl) {
        var txt = statusEl.textContent.trim().toLowerCase();
        if (txt === 'queued' || txt === 'running') hasActive = true;
      }
    });
    if (hasActive) { setTimeout(function () { location.reload(); }, 10000); }
  })();

  // ── Results viewer ──

  window.viewPFResults = async function (runId) {
    var section = document.getElementById('pfResultsSection');
    var info = document.getElementById('pfResultsInfo');
    section.style.display = 'block';
    document.getElementById('pfResultsRunId').textContent = runId;
    info.textContent = 'Loading...';
    section.scrollIntoView({ behavior: 'smooth' });

    try {
      var runRes = await fetch('/pf-datagen/runs/' + runId);
      var run = await runRes.json();
      if (!runRes.ok) throw new Error(run.detail || 'Failed to load run');

      var summary = run.summary || {};
      info.textContent = 'MV Grid: ' + run.mv_grid_id +
        ' | Status: ' + run.status +
        ' | Converged: ' + (summary.converged || 0) + '/' + (summary.total_output_groups || 0) +
        ' | Thermal violations: ' + (summary.thermal_violations || 0) +
        ' (preview based on first 500 rows of each table below)';

      var exportLinks = document.getElementById('pfExportLinks');
      exportLinks.innerHTML = 'Export: ' +
        ['bus', 'branch', 'ybus', 'runtime'].map(function (t) {
          return '<a href="/pf-datagen/runs/' + runId + '/export.csv?table=' + t + '">' + t + '.csv</a>';
        }).join(' | ');

      var busRes = await fetch('/pf-datagen/runs/' + runId + '/results?table=bus&limit=500');
      var busData = await busRes.json();
      var vmValues = (busData.rows || []).map(function (r) { return r.vm; }).filter(function (v) { return v != null; });

      var branchRes = await fetch('/pf-datagen/runs/' + runId + '/results?table=branch&limit=500');
      var branchData = await branchRes.json();
      var violationCounts = {};
      (branchData.rows || []).forEach(function (r) {
        if (r.thermal_violation) {
          violationCounts[r.connection_id] = (violationCounts[r.connection_id] || 0) + 1;
        }
      });

      ensurePlotly(function () {
        Plotly.newPlot('pfVoltageChart', [{ x: vmValues, type: 'histogram', marker: { color: '#2563eb' } }], {
          title: 'Solved Voltage Magnitude Distribution (preview)',
          xaxis: { title: 'Voltage (V)' }, yaxis: { title: 'Count' },
          plot_bgcolor: '#f8fafc', paper_bgcolor: '#ffffff'
        });

        var connIds = Object.keys(violationCounts);
        Plotly.newPlot('pfViolationChart', [{
          x: connIds, y: connIds.map(function (c) { return violationCounts[c]; }),
          type: 'bar', marker: { color: '#dc2626' }
        }], {
          title: 'Thermal Violations by Connection (preview)',
          xaxis: { title: 'Connection ID' }, yaxis: { title: 'Violation Count' },
          plot_bgcolor: '#f8fafc', paper_bgcolor: '#ffffff'
        });
      });
    } catch (err) {
      info.textContent = 'Error: ' + err.message;
    }
  };
})();
