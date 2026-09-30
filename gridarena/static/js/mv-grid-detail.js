(function () {
  var mvGridId = window.MV_GRID_ID;

  // ── Render network graph on load ──
  if (window.GRAPH_DATA) {
    ensurePlotly(function () {
      renderMVGraph('networkGraph', window.GRAPH_DATA, function (cpId) {
        showConnectForm(cpId);
      });
    });
  }

  var labelToggle = document.getElementById('toggleNodeLabels');
  if (labelToggle) {
    labelToggle.addEventListener('change', function () {
      // Traces: [0] edges (lines), [1..4] substation/junction/connection_point/connected_cp (markers+text).
      Plotly.restyle('networkGraph', { mode: this.checked ? 'markers+text' : 'markers' }, [1, 2, 3, 4]);
    });
  }

  // ── Connect form ──
  window.showConnectForm = function (cpId) {
    document.getElementById('connectSection').style.display = 'block';
    document.getElementById('connectPointId').textContent = cpId;
    document.getElementById('connectCpId').value = cpId;
    document.getElementById('connectMsg').textContent = '';
    document.getElementById('lvGridSelect').value = '';
    document.getElementById('connectSection').scrollIntoView({ behavior: 'smooth' });
  };

  var connectForm = document.getElementById('connectForm');
  if (connectForm) {
    connectForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      var cpId = document.getElementById('connectCpId').value;
      var lvGridId = document.getElementById('lvGridSelect').value;
      var msg = document.getElementById('connectMsg');

      if (!lvGridId) { msg.textContent = 'Please select an LV grid.'; return; }

      var impReal = document.getElementById('trImpReal').value;
      var impImag = document.getElementById('trImpImag').value;

      var payload = {
        lv_grid_id: lvGridId,
        rated_power_kva: parseFloat(document.getElementById('ratedPower').value) || 400,
        primary_voltage_kv: parseFloat(document.getElementById('primaryVoltage').value) || 20,
        secondary_voltage_v: parseFloat(document.getElementById('secondaryVoltage').value) || 230,
        imp_real: impReal ? parseFloat(impReal) : null,
        imp_imag: impImag ? parseFloat(impImag) : null
      };

      msg.textContent = 'Connecting...';
      try {
        var res = await fetch('/mv_grid/' + mvGridId + '/connect/' + encodeURIComponent(cpId), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Connection failed');
        msg.textContent = data.message;
        setTimeout(function () { location.reload(); }, 1500);
      } catch (err) {
        msg.textContent = 'Error: ' + err.message;
      }
    });
  }

  // ── Disconnect ──
  window.disconnectLV = async function (mvId, cpId, lvId) {
    if (!confirm('Disconnect LV grid "' + lvId + '" from point "' + cpId + '"?')) return;
    try {
      var res = await fetch('/mv_grid/' + mvId + '/disconnect/' + encodeURIComponent(cpId) + '/' + encodeURIComponent(lvId), {
        method: 'DELETE'
      });
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Disconnect failed');
      location.reload();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  // ── View P/V ──
  window.viewPV = async function (mvId, lvId) {
    var section = document.getElementById('pvSection');
    var info = document.getElementById('pvInfo');

    section.style.display = 'block';
    document.getElementById('pvLvId').textContent = lvId;
    info.textContent = 'Loading...';
    section.scrollIntoView({ behavior: 'smooth' });

    try {
      var res = await fetch('/mv_grid/' + mvId + '/pv/' + encodeURIComponent(lvId));
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to load P/V data');

      info.textContent = data.n_nodes + ' nodes | ' + data.count + ' timestamps | Aggregation: ' + data.aggregation;

      var timestamps = data.pv_pairs.map(function (p) { return p.datetime; });
      var powers = data.pv_pairs.map(function (p) { return p.avg_power_active; });
      var voltages = data.pv_pairs.map(function (p) { return p.avg_voltage_magnitude; });

      ensurePlotly(function () {
        Plotly.newPlot('pvChart', [
          { x: timestamps, y: powers, name: 'Avg Power (kW)', yaxis: 'y1' },
          { x: timestamps, y: voltages, name: 'Avg Voltage (V)', yaxis: 'y2' }
        ], {
          title: 'Aggregated P/V at MV/LV Boundary — ' + lvId,
          xaxis: { title: 'Datetime' },
          yaxis: { title: 'Power (kW)', side: 'left' },
          yaxis2: { title: 'Voltage (V)', side: 'right', overlaying: 'y' },
          legend: { orientation: 'h' },
          plot_bgcolor: '#f8fafc', paper_bgcolor: '#ffffff'
        });
      });
    } catch (err) {
      info.textContent = 'Error: ' + err.message;
    }
  };
})();
