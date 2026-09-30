/* Digital Twin — detail page JS */

var BASE = '/digital-twins/' + DT_ID;

function setMsg(text, ok) {
  var el = document.getElementById('lifecycleMsg');
  el.textContent = text;
  el.style.color = ok ? '#059669' : '#dc2626';
}

function startTwin() {
  setMsg('Starting...', true);
  fetch(BASE + '/start', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) { setMsg(d.message || 'Started.', true); setTimeout(function(){ location.reload(); }, 1500); })
    .catch(function(e) { setMsg('Error: ' + e, false); });
}

function stopTwin() {
  setMsg('Stopping...', true);
  fetch(BASE + '/stop', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) { setMsg(d.message || 'Stopped.', true); setTimeout(function(){ location.reload(); }, 1500); })
    .catch(function(e) { setMsg('Error: ' + e, false); });
}

function tickTwin() {
  setMsg('Running tick...', true);
  fetch(BASE + '/tick', { method: 'POST' })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Tick failed'); });
      return r.json();
    })
    .then(function(d) {
      var m = d.metrics || {};
      setMsg('Tick completed. Convergence: ' + (m.convergence_status || '?') + ', MAE: ' + (m.voltage_mae != null ? m.voltage_mae.toFixed(4) : '—'), true);
      setTimeout(function(){ location.reload(); }, 2000);
    })
    .catch(function(e) { setMsg('Error: ' + e.message, false); });
}

function testSource() {
  setMsg('Testing source...', true);
  fetch(BASE + '/test-source', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.success) {
        setMsg('Source OK (HTTP ' + d.status_code + '). Payload size: ' + JSON.stringify(d.raw_payload).length + ' bytes.', true);
      } else {
        setMsg('Source failed: ' + (d.error || 'Unknown error'), false);
      }
    })
    .catch(function(e) { setMsg('Error: ' + e, false); });
}

function publishSample() {
  setMsg('Publishing sample...', true);
  fetch(BASE + '/publish-sample', { method: 'POST' })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || JSON.stringify(d)); });
      return r.json();
    })
    .then(function(d) {
      setMsg(d.message + ' (' + d.measurements_count + ' measurements)', true);
    })
    .catch(function(e) { setMsg('Error: ' + e.message, false); });
}

function cloneOffline() {
  var name = prompt('Name for the offline scenario:', 'Scenario from ' + DT_ID);
  if (name === null) return;
  setMsg('Cloning...', true);
  fetch(BASE + '/clone-offline', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name: name }),
  })
  .then(function(r) {
    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Clone failed'); });
    return r.json();
  })
  .then(function(d) {
    setMsg(d.message, true);
    setTimeout(function() { window.location.href = '/offline-scenarios/ui/' + d.scenario_id; }, 1500);
  })
  .catch(function(e) { setMsg('Error: ' + e.message, false); });
}

// ══════════════════════════════════════════
//  Live grid graph — same pattern as LV grid
// ══════════════════════════════════════════

var _latestMeasurements = {};

function renderLiveGrid() {
  var container = document.getElementById('liveGridGraph');
  if (!GRAPH_DATA || !GRAPH_DATA.nodes || GRAPH_DATA.nodes.length === 0) {
    container.innerHTML = '<p style="padding:40px; color:#6b7280; text-align:center;">No grid nodes available.</p>';
    return;
  }

  var nodeValues = {};

  // Load from power-flow comparison results (has simulated voltage)
  var latestResultTimestamp = null;
  var converged = (RESULTS || []).filter(function(r) { return r.convergence_status === 'converged' && r.details; });
  if (converged.length > 0) {
    latestResultTimestamp = converged[0].timestamp;
    var details = converged[0].details;
    if (typeof details === 'string') { try { details = JSON.parse(details); } catch(e) { details = {}; } }
    if (details && typeof details === 'object') {
      Object.keys(details).forEach(function(nid) {
        nodeValues[nid] = details[nid];
        nodeValues[nid].has_data = true;
      });
    }
  }

  // Merge latest streamed measurements (has power values even without voltage)
  Object.keys(_latestMeasurements).forEach(function(nid) {
    var m = _latestMeasurements[nid];
    if (!nodeValues[nid]) {
      nodeValues[nid] = { has_data: true };
    }
    nodeValues[nid].power_active = m.power_active;
    nodeValues[nid].power_reactive = m.power_reactive;
    nodeValues[nid].measured_voltage = m.voltage_magnitude;
    nodeValues[nid].phase = m.phase;
    nodeValues[nid].datetime = m.datetime;
  });

  var nodes = GRAPH_DATA.nodes;
  var edges = GRAPH_DATA.edges || [];
  var posMap = {};
  nodes.forEach(function(n) { posMap[n.id] = { x: n.x, y: n.y }; });

  var edgeX = [], edgeY = [];
  edges.forEach(function(e) {
    var f = posMap[e.from], t = posMap[e.to];
    if (f && t) { edgeX.push(f.x, t.x, null); edgeY.push(f.y, t.y, null); }
  });

  var ptNodes = nodes.filter(function(n) { return n.type === 'pt'; });
  var dataNodes = nodes.filter(function(n) { return n.type !== 'pt' && nodeValues[n.id]; });
  var noDataNodes = nodes.filter(function(n) { return n.type !== 'pt' && !nodeValues[n.id]; });

  function voltageColor(nv) {
    var v = nv.simulated_voltage != null ? nv.simulated_voltage : (nv.true_voltage != null ? nv.true_voltage : null);
    if (v == null) return '#2563eb';
    var deviation = Math.abs(v - VOLTAGE_REF) / VOLTAGE_REF;
    if (deviation > 0.10) return '#ef4444';
    if (deviation > 0.05) return '#f59e0b';
    return '#059669';
  }

  function nodeLabel(n) {
    var nv = nodeValues[n.id];
    if (!nv) return n.id;
    var parts = [n.id];
    if (nv.simulated_voltage != null) parts.push(nv.simulated_voltage.toFixed(1) + 'V');
    if (nv.power_active != null) parts.push(nv.power_active.toFixed(0) + 'W');
    return parts.length > 1 ? parts[0] + '\n' + parts.slice(1).join(' | ') : n.id;
  }

  function nodeHover(n) {
    var nv = nodeValues[n.id];
    if (!nv) return n.id + ': no data';
    var lines = ['<b>' + n.id + '</b>'];
    if (nv.power_active != null) lines.push('P: ' + nv.power_active.toFixed(2) + ' W');
    if (nv.power_reactive != null && nv.power_reactive !== 0) lines.push('Q: ' + nv.power_reactive.toFixed(2) + ' VAr');
    if (nv.simulated_voltage != null) lines.push('PF Voltage: ' + nv.simulated_voltage.toFixed(2) + ' V');
    if (nv.true_voltage != null) lines.push('True V: ' + nv.true_voltage.toFixed(2) + ' V');
    if (nv.measured_voltage != null && nv.measured_voltage > 0) lines.push('Meas V: ' + nv.measured_voltage.toFixed(2) + ' V');
    if (nv.error != null) lines.push('Error: ' + nv.error.toFixed(4) + ' V');
    return lines.join('<br>');
  }

  var dataNodeColors = dataNodes.map(function(n) { return voltageColor(nodeValues[n.id]); });

  var traces = [
    {
      x: edgeX, y: edgeY, mode: 'lines',
      line: { width: 2, color: '#94a3b8' },
      hoverinfo: 'none', showlegend: false
    },
    {
      x: ptNodes.map(function(n) { return n.x; }),
      y: ptNodes.map(function(n) { return n.y; }),
      text: ptNodes.map(function(n) { return n.id + ' (' + VOLTAGE_REF + 'V)'; }),
      hovertext: ptNodes.map(function(n) { return n.id + ' (PT ref: ' + VOLTAGE_REF + 'V)'; }),
      mode: 'markers+text', textposition: 'top center', textfont: { size: 10 },
      marker: { size: 14, color: '#dc2626', symbol: 'square', line: { width: 1, color: '#1f2937' } },
      name: 'PT (Reference)', hoverinfo: 'text'
    },
    {
      x: dataNodes.map(function(n) { return n.x; }),
      y: dataNodes.map(function(n) { return n.y; }),
      text: dataNodes.map(nodeLabel),
      hovertext: dataNodes.map(nodeHover),
      mode: 'markers+text', textposition: 'top center', textfont: { size: 9 },
      marker: { size: 12, color: dataNodeColors, symbol: 'circle', line: { width: 1, color: '#1f2937' } },
      name: 'With data', hoverinfo: 'text'
    },
    {
      x: noDataNodes.map(function(n) { return n.x; }),
      y: noDataNodes.map(function(n) { return n.y; }),
      text: noDataNodes.map(function(n) { return n.id; }),
      hovertext: noDataNodes.map(function(n) { return n.id + ': no data'; }),
      mode: 'markers+text', textposition: 'top center', textfont: { size: 9 },
      marker: { size: 10, color: '#94a3b8', symbol: 'circle', line: { width: 1, color: '#1f2937' } },
      name: 'No data', hoverinfo: 'text'
    }
  ];

  Plotly.newPlot(container, traces, {
    showlegend: true, legend: { orientation: 'h', y: -0.05 },
    hovermode: 'closest',
    xaxis: { visible: false }, yaxis: { visible: false, scaleanchor: 'x' },
    margin: { l: 10, r: 10, t: 10, b: 40 },
    plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
  }, { responsive: true });

  container.on('plotly_click', function(data) {
    if (data.points && data.points.length > 0) {
      var idx = data.points[0].pointIndex;
      var trace = data.points[0].data;
      var allNodes = trace === traces[1] ? ptNodes : trace === traces[2] ? dataNodes : noDataNodes;
      if (allNodes[idx]) showNodeInfo(allNodes[idx].id, nodeValues, latestResultTimestamp);
    }
  });
}

function showNodeInfo(nodeId, nodeValues, latestResultTimestamp) {
  var nv = nodeValues[nodeId];
  var grid = document.getElementById('nodeInfoGrid');
  var content = document.getElementById('nodeInfoContent');
  var placeholder = document.getElementById('nodeInfoPlaceholder');

  placeholder.style.display = 'none';
  content.style.display = '';

  var items = [['Node ID', '<strong>' + nodeId + '</strong>']];

  if (nodeId === 'PT') {
    items.push(['Type', 'Transformer Point']);
    items.push(['Reference Voltage', VOLTAGE_REF.toFixed(1) + ' V']);
  } else if (nv && nv.has_data) {
    if (nv.phase) items.push(['Phase', nv.phase]);
    var ts = nv.datetime || latestResultTimestamp;
    if (ts) items.push(['Timestamp', ts.substring(0, 19)]);

    if (nv.power_active != null) items.push(['Active Power', nv.power_active.toFixed(2) + ' W']);
    if (nv.power_reactive != null && nv.power_reactive !== 0) items.push(['Reactive Power', nv.power_reactive.toFixed(2) + ' VAr']);

    if (nv.simulated_voltage != null) items.push(['PF Voltage', '<strong>' + nv.simulated_voltage.toFixed(2) + ' V</strong>']);
    if (nv.measured_voltage != null && nv.measured_voltage > 0) items.push(['Measured Voltage', nv.measured_voltage.toFixed(2) + ' V']);
    if (nv.true_voltage != null) items.push(['True Voltage', nv.true_voltage.toFixed(2) + ' V']);
    if (nv.error != null) items.push(['Voltage Error', nv.error.toFixed(4) + ' V']);

    var statusV = nv.simulated_voltage != null ? nv.simulated_voltage : nv.true_voltage;
    if (statusV != null) {
      var deviation = Math.abs(statusV - VOLTAGE_REF) / VOLTAGE_REF;
      var statusText = 'Normal', statusColor = '#059669';
      if (deviation > 0.10) { statusText = 'Violation'; statusColor = '#ef4444'; }
      else if (deviation > 0.05) { statusText = 'Warning'; statusColor = '#f59e0b'; }
      items.push(['Voltage Status', '<span style="color:' + statusColor + '; font-weight:600;">' + statusText + '</span>']);
      items.push(['Deviation', (deviation * 100).toFixed(2) + '%']);
    }
  } else {
    items.push(['Status', '<span style="color:#94a3b8;">No data</span>']);
  }

  grid.innerHTML = items.map(function(pair) {
    return '<dt>' + pair[0] + '</dt><dd>' + pair[1] + '</dd>';
  }).join('');

  loadNodeHistory(nodeId);
}

var _lastNodeHistoryId = null;

function loadNodeHistory(nodeId) {
  var powerDiv = document.getElementById('nodePowerChart');
  var voltageDiv = document.getElementById('nodeVoltageChart');
  var loadingEl = document.getElementById('nodeChartsLoading');

  if (_lastNodeHistoryId === nodeId) return;
  _lastNodeHistoryId = nodeId;

  powerDiv.innerHTML = '';
  voltageDiv.innerHTML = '';

  if (nodeId === 'PT') return;

  loadingEl.style.display = '';
  loadingEl.textContent = 'Loading history for ' + nodeId + '...';

  fetch(BASE + '/node-history/' + encodeURIComponent(nodeId))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      loadingEl.style.display = 'none';
      var pts = data.points || [];
      if (pts.length === 0) {
        powerDiv.innerHTML = '<p style="font-size:11px; color:#6b7280; text-align:center; padding:10px;">No history data yet.</p>';
        return;
      }

      var timestamps = pts.map(function(p) { return p.timestamp; });
      var compactLayout = {
        margin: { t: 25, b: 30, l: 45, r: 10 },
        font: { size: 10 },
        xaxis: { type: 'date' },
        showlegend: true,
        legend: { orientation: 'h', y: 1.15, font: { size: 9 } },
        height: 180,
        plot_bgcolor: '#fafbfc',
      };

      // Power chart
      var powerTraces = [];
      var pActive = pts.map(function(p) { return p.power_active; });
      if (pActive.some(function(v) { return v != null; })) {
        powerTraces.push({
          x: timestamps, y: pActive, type: 'scatter', mode: 'lines+markers',
          name: 'P (W)', line: { color: '#2563eb', width: 1.5 }, marker: { size: 3 },
        });
      }
      var pReactive = pts.map(function(p) { return p.power_reactive; });
      if (pReactive.some(function(v) { return v != null && v !== 0; })) {
        powerTraces.push({
          x: timestamps, y: pReactive, type: 'scatter', mode: 'lines+markers',
          name: 'Q (VAr)', line: { color: '#f59e0b', width: 1.5 }, marker: { size: 3 },
        });
      }
      if (powerTraces.length > 0) {
        var pLayout = JSON.parse(JSON.stringify(compactLayout));
        pLayout.yaxis = { title: 'Power' };
        Plotly.newPlot(powerDiv, powerTraces, pLayout, { responsive: true, displayModeBar: false });
      }

      // Voltage chart
      var voltageTraces = [];
      var simV = pts.map(function(p) { return p.simulated_voltage; });
      if (simV.some(function(v) { return v != null; })) {
        voltageTraces.push({
          x: timestamps, y: simV, type: 'scatter', mode: 'lines+markers',
          name: 'PF Voltage', line: { color: '#7c3aed', width: 1.5 }, marker: { size: 3 },
        });
      }
      var trueV = pts.map(function(p) { return p.true_voltage; });
      if (trueV.some(function(v) { return v != null; })) {
        voltageTraces.push({
          x: timestamps, y: trueV, type: 'scatter', mode: 'lines+markers',
          name: 'True Voltage', line: { color: '#059669', width: 1.5 }, marker: { size: 3 },
        });
      }
      if (voltageTraces.length > 0) {
        // Reference voltage line
        voltageTraces.push({
          x: [timestamps[0], timestamps[timestamps.length - 1]],
          y: [VOLTAGE_REF, VOLTAGE_REF],
          type: 'scatter', mode: 'lines', name: 'V ref',
          line: { color: '#dc2626', width: 1, dash: 'dash' },
        });
        var vLayout = JSON.parse(JSON.stringify(compactLayout));
        vLayout.yaxis = { title: 'Voltage (V)' };
        Plotly.newPlot(voltageDiv, voltageTraces, vLayout, { responsive: true, displayModeBar: false });
      }
    })
    .catch(function(e) {
      loadingEl.style.display = 'none';
      powerDiv.innerHTML = '<p style="font-size:11px; color:#dc2626; padding:10px;">Failed to load history.</p>';
    });
}

if (window.Plotly) { renderLiveGrid(); }
else {
  var s = document.createElement('script');
  s.src = 'https://cdn.plot.ly/plotly-2.27.0.min.js';
  s.onload = renderLiveGrid;
  document.head.appendChild(s);
}


// ══════════════════════════════════════════
//  Latest measurements table
// ══════════════════════════════════════════

function refreshMeasurements() {
  var loading = document.getElementById('measurementsLoading');
  var table = document.getElementById('measurementsTable');
  var body = document.getElementById('measurementsBody');
  var empty = document.getElementById('measurementsEmpty');

  loading.style.display = '';
  loading.textContent = 'Loading latest measurements...';
  loading.style.color = '#6b7280';
  table.style.display = 'none';
  empty.style.display = 'none';

  fetch(BASE + '/latest-state')
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'HTTP ' + r.status); });
      return r.json();
    })
    .then(function(data) {
      loading.style.display = 'none';
      var measurements = [];
      if (data.latest_measurements && data.latest_measurements.measurements) {
        measurements = data.latest_measurements.measurements;
      }
      if (measurements.length === 0) {
        empty.style.display = '';
        return;
      }

      // Store measurements for the grid graph
      measurements.forEach(function(m) {
        if (m.node_id) _latestMeasurements[m.node_id] = m;
      });

      body.innerHTML = '';
      measurements.forEach(function(m) {
        var tr = document.createElement('tr');
        tr.innerHTML =
          '<td><strong>' + (m.node_id || '—') + '</strong></td>' +
          '<td>' + (m.phase || '—') + '</td>' +
          '<td>' + (m.datetime ? m.datetime.substring(0, 19) : '—') + '</td>' +
          '<td>' + (m.power_active != null ? m.power_active.toFixed(2) : '—') + '</td>' +
          '<td>' + (m.power_reactive != null ? m.power_reactive.toFixed(2) : '—') + '</td>' +
          '<td>' + (m.voltage_magnitude != null ? m.voltage_magnitude.toFixed(2) : '—') + '</td>' +
          '<td>' + (m.voltage_angle != null ? m.voltage_angle.toFixed(2) : '—') + '</td>';
        body.appendChild(tr);
      });
      table.style.display = '';

      // Re-render graph with measurement data
      if (window.Plotly && GRAPH_DATA && GRAPH_DATA.nodes && GRAPH_DATA.nodes.length > 0) {
        renderLiveGrid();
      }
    })
    .catch(function(e) {
      loading.style.display = 'none';
      empty.style.display = '';
      empty.textContent = 'No measurements available. Run a Tick first.';
    });
}

refreshMeasurements();


// ══════════════════════════════════════════
//  Voltage comparison bar chart
// ══════════════════════════════════════════

(function() {
  if (typeof Plotly === 'undefined' || !RESULTS || RESULTS.length === 0) return;

  var converged = RESULTS.filter(function(r) { return r.convergence_status === 'converged' && r.details; });
  if (converged.length === 0) return;

  var latest = converged[0];
  var details = latest.details;
  if (typeof details === 'string') {
    try { details = JSON.parse(details); } catch(e) { return; }
  }
  if (!details || typeof details !== 'object') return;

  var nodes = Object.keys(details).sort();
  var trueV = nodes.map(function(n) { return details[n].true_voltage; });
  var simV = nodes.map(function(n) { return details[n].simulated_voltage; });

  Plotly.newPlot('voltageChart', [
    { x: nodes, y: trueV, type: 'bar', name: 'True Voltage', marker: { color: '#3b82f6' } },
    { x: nodes, y: simV, type: 'bar', name: 'Simulated Voltage', marker: { color: '#f59e0b' } },
  ], {
    barmode: 'group',
    margin: { t: 30, b: 50, l: 50, r: 20 },
    xaxis: { title: 'Node' },
    yaxis: { title: 'Voltage (V)' },
    legend: { orientation: 'h', y: 1.12 },
    font: { size: 11 },
  }, { responsive: true });

  if (converged.length > 1) {
    var timestamps = converged.map(function(r) { return r.timestamp; }).reverse();
    var maes = converged.map(function(r) { return r.voltage_mae; }).reverse();

    var chartDiv = document.createElement('div');
    chartDiv.className = 'dt-chart';
    chartDiv.id = 'maeChart';
    chartDiv.style.marginTop = '16px';
    document.getElementById('voltageChart').parentElement.appendChild(chartDiv);

    Plotly.newPlot('maeChart', [{
      x: timestamps, y: maes, type: 'scatter', mode: 'lines+markers',
      name: 'Voltage MAE', line: { color: '#ef4444', width: 2 },
    }], {
      margin: { t: 30, b: 50, l: 50, r: 20 },
      xaxis: { title: 'Timestamp' },
      yaxis: { title: 'MAE (V)' },
      font: { size: 11 },
    }, { responsive: true });
  }
})();


// ══════════════════════════════════════════
//  Auto-refresh if running
// ══════════════════════════════════════════

(function() {
  var statusEl = document.getElementById('scStatus');
  if (statusEl && statusEl.textContent.trim().toLowerCase() === 'running') {
    setTimeout(function() { location.reload(); }, 15000);
  }
})();
