/* Offline Scenario — detail page JS */

function setMsg(text, ok) {
  var el = document.getElementById('simMsg');
  el.textContent = text;
  el.style.color = ok ? '#059669' : '#dc2626';
}

// ══════════════════════════════════════════
//  Simulation controls
// ══════════════════════════════════════════

function runSimulation() {
  setMsg('Starting simulation...', true);
  fetch(BASE + '/run-powerflow-timeseries', { method: 'POST' })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
      return r.json();
    })
    .then(function(d) {
      setMsg(d.message, true);
      setTimeout(function() { location.reload(); }, 3000);
    })
    .catch(function(e) { setMsg('Error: ' + e.message, false); });
}

function deleteScenario() {
  if (!confirm('Delete this scenario and all its results?')) return;
  fetch(BASE, { method: 'DELETE' })
    .then(function(r) { return r.json(); })
    .then(function() { window.location.href = '/offline-scenarios/ui'; })
    .catch(function(e) { alert('Error: ' + e); });
}


// ══════════════════════════════════════════
//  Interactive connection graph
// ══════════════════════════════════════════

var _selectedNode1 = null;
var _selectedNode2 = null;
var _connChanges = CONNECTION_CHANGES.slice();

function _getEffectiveConnections() {
  var conns = {};
  (GRID_SNAPSHOT.connections || []).forEach(function(c) {
    conns[c.connection_id] = Object.assign({}, c, { status: 'original' });
  });
  _connChanges.forEach(function(ch) {
    if (ch.action === 'remove' && conns[ch.connection_id]) {
      conns[ch.connection_id].status = 'removed';
    } else if (ch.action === 'disable' && conns[ch.connection_id]) {
      conns[ch.connection_id].status = 'disabled';
    } else if (ch.action === 'enable' && conns[ch.connection_id]) {
      conns[ch.connection_id].status = 'original';
    } else if (ch.action === 'add') {
      conns[ch.connection_id] = {
        connection_id: ch.connection_id,
        from_node_id: ch.from_node_id, to_node_id: ch.to_node_id,
        cable_id: ch.cable_id, length: ch.length,
        status: 'added',
      };
    }
  });
  return conns;
}

function renderConnGraph() {
  var container = document.getElementById('connGraph');
  if (typeof Plotly === 'undefined' || !GRAPH_DATA || !GRAPH_DATA.nodes || GRAPH_DATA.nodes.length === 0) {
    container.innerHTML = '<p style="padding:30px; color:#6b7280; text-align:center;">No grid data.</p>';
    return;
  }

  var nodes = GRAPH_DATA.nodes;
  var posMap = {};
  nodes.forEach(function(n) { posMap[n.id] = { x: n.x, y: n.y }; });

  var conns = _getEffectiveConnections();
  var traces = [];

  // Original edges (solid gray)
  var origX = [], origY = [];
  // Added edges (solid green)
  var addX = [], addY = [];
  // Removed edges (dashed red)
  var remX = [], remY = [];

  Object.values(conns).forEach(function(c) {
    var f = posMap[c.from_node_id], t = posMap[c.to_node_id];
    if (!f || !t) return;
    if (c.status === 'removed' || c.status === 'disabled') {
      remX.push(f.x, t.x, null); remY.push(f.y, t.y, null);
    } else if (c.status === 'added') {
      addX.push(f.x, t.x, null); addY.push(f.y, t.y, null);
    } else {
      origX.push(f.x, t.x, null); origY.push(f.y, t.y, null);
    }
  });

  traces.push({ x: origX, y: origY, mode: 'lines', line: { width: 2.5, color: '#94a3b8' }, hoverinfo: 'none', showlegend: false });
  if (addX.length > 0) {
    traces.push({ x: addX, y: addY, mode: 'lines', line: { width: 3, color: '#059669' }, hoverinfo: 'none', name: 'Added', showlegend: true });
  }
  if (remX.length > 0) {
    traces.push({ x: remX, y: remY, mode: 'lines', line: { width: 2, color: '#ef4444', dash: 'dash' }, hoverinfo: 'none', name: 'Removed', showlegend: true });
  }

  // Edge midpoints for click-to-remove
  var edgeMidX = [], edgeMidY = [], edgeIds = [];
  Object.values(conns).forEach(function(c) {
    if (c.status === 'removed' || c.status === 'disabled') return;
    var f = posMap[c.from_node_id], t = posMap[c.to_node_id];
    if (!f || !t) return;
    edgeMidX.push((f.x + t.x) / 2);
    edgeMidY.push((f.y + t.y) / 2);
    edgeIds.push(c.connection_id);
  });

  traces.push({
    x: edgeMidX, y: edgeMidY, mode: 'markers',
    marker: { size: 6, color: 'rgba(148,163,184,0.4)', symbol: 'x' },
    hovertext: edgeIds.map(function(id) { return 'Click to remove: ' + id; }),
    hoverinfo: 'text', showlegend: false,
    customdata: edgeIds,
  });

  var ptNodes = nodes.filter(function(n) { return n.type === 'pt'; });
  var normalNodes = nodes.filter(function(n) { return n.type !== 'pt'; });

  function nodeColor(n) {
    if (n.id === _selectedNode1) return '#f59e0b';
    return n.type === 'pt' ? '#dc2626' : '#2563eb';
  }

  traces.push({
    x: ptNodes.map(function(n) { return n.x; }), y: ptNodes.map(function(n) { return n.y; }),
    text: ptNodes.map(function(n) { return n.id; }),
    mode: 'markers+text', textposition: 'top center', textfont: { size: 10 },
    marker: { size: 14, color: ptNodes.map(nodeColor), symbol: 'square', line: { width: 1, color: '#1f2937' } },
    name: 'PT', hoverinfo: 'text',
    customdata: ptNodes.map(function(n) { return n.id; }),
  });

  traces.push({
    x: normalNodes.map(function(n) { return n.x; }), y: normalNodes.map(function(n) { return n.y; }),
    text: normalNodes.map(function(n) { return n.id; }),
    mode: 'markers+text', textposition: 'top center', textfont: { size: 9 },
    marker: { size: 12, color: normalNodes.map(nodeColor), symbol: 'circle', line: { width: 1, color: '#1f2937' } },
    name: 'Node', hoverinfo: 'text',
    customdata: normalNodes.map(function(n) { return n.id; }),
  });

  Plotly.newPlot(container, traces, {
    showlegend: true, legend: { orientation: 'h', y: -0.05, font: { size: 9 } },
    hovermode: 'closest',
    xaxis: { visible: false }, yaxis: { visible: false, scaleanchor: 'x' },
    margin: { l: 10, r: 10, t: 10, b: 40 },
    plot_bgcolor: '#fff', paper_bgcolor: '#fff'
  }, { responsive: true, displayModeBar: false });

  container.on('plotly_click', function(data) {
    if (!data.points || data.points.length === 0) return;
    var pt = data.points[0];
    var cd = pt.customdata;
    if (!cd) return;

    // Check if clicked an edge midpoint
    var edgeTraceIdx = traces.length - 3; // edge midpoints trace
    if (pt.data === traces[edgeTraceIdx] || (pt.curveNumber === edgeTraceIdx)) {
      removeConnection(cd);
      return;
    }

    // Clicked a node
    onNodeClick(cd);
  });
}

function onNodeClick(nodeId) {
  var hint = document.getElementById('connGraphHint');
  var status = document.getElementById('connSelectionStatus');
  var form = document.getElementById('addConnForm');

  if (!_selectedNode1) {
    _selectedNode1 = nodeId;
    hint.textContent = 'First node: ' + nodeId + '. Now click the second node.';
    status.textContent = 'From: ' + nodeId + ' → select second node...';
    form.style.display = 'none';
    renderConnGraph();
  } else if (!_selectedNode2 && nodeId !== _selectedNode1) {
    _selectedNode2 = nodeId;
    hint.textContent = 'Connection: ' + _selectedNode1 + ' → ' + _selectedNode2 + '. Set cable and length, then click Add.';
    status.textContent = _selectedNode1 + ' → ' + _selectedNode2;
    form.style.display = '';
  } else {
    cancelSelection();
    onNodeClick(nodeId);
  }
}

function cancelSelection() {
  _selectedNode1 = null;
  _selectedNode2 = null;
  document.getElementById('connGraphHint').textContent = 'Click a node to start adding a connection. Click an edge to remove it.';
  document.getElementById('connSelectionStatus').textContent = 'Select first node on the graph...';
  document.getElementById('addConnForm').style.display = 'none';
  renderConnGraph();
}

function confirmAddConnection() {
  if (!_selectedNode1 || !_selectedNode2) return;
  var cableId = document.getElementById('chCable').value;
  var length = parseFloat(document.getElementById('chLength').value) || 50;
  var connId = 'C_' + _selectedNode1 + '_' + _selectedNode2;

  _connChanges.push({
    action: 'add', connection_id: connId,
    from_node_id: _selectedNode1, to_node_id: _selectedNode2,
    cable_id: cableId, length: length,
  });

  _saveChanges();
  cancelSelection();
}

function removeConnection(connId) {
  if (!confirm('Remove connection "' + connId + '"?')) return;

  var isAdded = _connChanges.some(function(c) { return c.action === 'add' && c.connection_id === connId; });
  if (isAdded) {
    _connChanges = _connChanges.filter(function(c) { return !(c.action === 'add' && c.connection_id === connId); });
  } else {
    _connChanges.push({ action: 'remove', connection_id: connId });
  }

  _saveChanges();
}

function clearAllChanges() {
  if (!confirm('Clear all connection changes?')) return;
  _connChanges = [];
  _saveChanges();
}

function _saveChanges() {
  fetch(BASE + '/changes/connections', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(_connChanges),
  })
  .then(function(r) {
    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail ? JSON.stringify(d.detail) : 'Failed'); });
    return r.json();
  })
  .then(function() { location.reload(); })
  .catch(function(e) { setMsg('Error saving changes: ' + e.message, false); });
}

renderConnGraph();


// ══════════════════════════════════════════
//  Power limits
// ══════════════════════════════════════════

var _powerLimits = Object.assign({}, POWER_LIMITS);

function setPowerLimit() {
  var nodeId = document.getElementById('plNode').value;
  var limit = parseFloat(document.getElementById('plLimit').value);
  if (isNaN(limit) || limit < 0) { alert('Enter a valid power limit.'); return; }
  _powerLimits[nodeId] = limit;
  _savePowerLimits();
}

function removePowerLimit(nodeId) {
  delete _powerLimits[nodeId];
  _savePowerLimits();
}

function _savePowerLimits() {
  fetch(BASE + '/changes/power-limits', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ power_limits: _powerLimits }),
  })
  .then(function(r) {
    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail ? JSON.stringify(d.detail) : 'Failed'); });
    return r.json();
  })
  .then(function() { location.reload(); })
  .catch(function(e) { setMsg('Error saving limits: ' + e.message, false); });
}


// ══════════════════════════════════════════
//  Static grid graph (topology overview)
// ══════════════════════════════════════════

(function() {
  if (typeof Plotly === 'undefined' || !GRAPH_DATA || !GRAPH_DATA.nodes || GRAPH_DATA.nodes.length === 0) return;

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
  var normalNodes = nodes.filter(function(n) { return n.type !== 'pt'; });

  Plotly.newPlot('scenarioGraph', [
    { x: edgeX, y: edgeY, mode: 'lines', line: { width: 2, color: '#94a3b8' }, hoverinfo: 'none', showlegend: false },
    {
      x: ptNodes.map(function(n) { return n.x; }), y: ptNodes.map(function(n) { return n.y; }),
      text: ptNodes.map(function(n) { return n.id; }),
      mode: 'markers+text', textposition: 'top center', textfont: { size: 10 },
      marker: { size: 14, color: '#dc2626', symbol: 'square', line: { width: 1, color: '#1f2937' } },
      name: 'PT', hoverinfo: 'text'
    },
    {
      x: normalNodes.map(function(n) { return n.x; }), y: normalNodes.map(function(n) { return n.y; }),
      text: normalNodes.map(function(n) { return n.id; }),
      mode: 'markers+text', textposition: 'top center', textfont: { size: 9 },
      marker: { size: 10, color: '#2563eb', symbol: 'circle', line: { width: 1, color: '#1f2937' } },
      name: 'Node', hoverinfo: 'text'
    }
  ], {
    showlegend: true, legend: { orientation: 'h', y: -0.05 },
    hovermode: 'closest',
    xaxis: { visible: false }, yaxis: { visible: false, scaleanchor: 'x' },
    margin: { l: 10, r: 10, t: 10, b: 40 },
    plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
  }, { responsive: true });
})();


// ══════════════════════════════════════════
//  Voltage time-series chart
// ══════════════════════════════════════════

function loadTimeSeriesCharts() {
  var nodeId = document.getElementById('voltageNodeSelect').value;
  var url = BASE + '/voltage-timeseries' + (nodeId ? '?node_id=' + encodeURIComponent(nodeId) : '');
  var vDiv = document.getElementById('voltageTimeChart');
  var pDiv = document.getElementById('powerTimeChart');
  var colors = ['#2563eb','#059669','#f59e0b','#ef4444','#7c3aed','#0ea5e9','#d946ef','#84cc16'];

  vDiv.innerHTML = '<p style="padding:20px; color:#6b7280; text-align:center;">Loading...</p>';
  pDiv.innerHTML = '<p style="padding:20px; color:#6b7280; text-align:center;">Loading...</p>';

  fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data || data.length === 0) {
        vDiv.innerHTML = '<p style="padding:20px; color:#6b7280; text-align:center;">No data. Run the simulation first.</p>';
        pDiv.innerHTML = '';
        return;
      }

      var vTraces = [], pTraces = [];

      if (nodeId) {
        var ts = data.map(function(d) { return d.timestamp; });
        vTraces.push({ x: ts, y: data.map(function(d) { return d.simulated_voltage; }), type: 'scatter', mode: 'lines+markers', name: nodeId + ' V', line: { width: 1.5, color: '#2563eb' }, marker: { size: 4 } });
        pTraces.push({ x: ts, y: data.map(function(d) { return d.power_active; }), type: 'scatter', mode: 'lines+markers', name: nodeId + ' P', line: { width: 1.5, color: '#2563eb' }, marker: { size: 4 } });
        var qVals = data.map(function(d) { return d.power_reactive; });
        if (qVals.some(function(v) { return v != null && v !== 0; })) {
          pTraces.push({ x: ts, y: qVals, type: 'scatter', mode: 'lines+markers', name: nodeId + ' Q', line: { width: 1.5, color: '#f59e0b', dash: 'dash' }, marker: { size: 4 } });
        }
      } else {
        var nodeMap = {};
        data.forEach(function(d) {
          if (d.nodes) Object.keys(d.nodes).forEach(function(nid) { nodeMap[nid] = true; });
        });
        var allNodes = Object.keys(nodeMap).sort();
        allNodes.forEach(function(nid, i) {
          if (nid === 'PT') return;
          var ts = [], vs = [], ps = [];
          data.forEach(function(d) {
            if (d.nodes && d.nodes[nid]) {
              ts.push(d.timestamp);
              vs.push(d.nodes[nid].simulated_voltage);
              ps.push(d.nodes[nid].power_active);
            }
          });
          var c = colors[i % colors.length];
          vTraces.push({ x: ts, y: vs, type: 'scatter', mode: 'lines+markers', name: nid, line: { width: 1.5, color: c }, marker: { size: 3 } });
          pTraces.push({ x: ts, y: ps, type: 'scatter', mode: 'lines+markers', name: nid, line: { width: 1.5, color: c }, marker: { size: 3 } });
        });
      }

      // Voltage reference bands
      if (vTraces.length > 0 && vTraces[0].x.length > 0) {
        var t0 = vTraces[0].x[0], t1 = vTraces[0].x[vTraces[0].x.length - 1];
        vTraces.push({ x: [t0, t1], y: [VOLTAGE_REF, VOLTAGE_REF], type: 'scatter', mode: 'lines', name: 'V ref', line: { color: '#dc2626', width: 1, dash: 'dash' } });
        vTraces.push({ x: [t0, t1], y: [VOLTAGE_REF * 0.9, VOLTAGE_REF * 0.9], type: 'scatter', mode: 'lines', name: '-10%', line: { color: '#f59e0b', width: 1, dash: 'dot' } });
        vTraces.push({ x: [t0, t1], y: [VOLTAGE_REF * 1.1, VOLTAGE_REF * 1.1], type: 'scatter', mode: 'lines', name: '+10%', line: { color: '#f59e0b', width: 1, dash: 'dot' } });
      }

      var sharedLayout = {
        margin: { t: 20, b: 40, l: 50, r: 20 },
        xaxis: { type: 'date' },
        legend: { orientation: 'h', y: 1.12, font: { size: 9 } },
        hovermode: 'x unified', font: { size: 10 },
      };

      Plotly.newPlot(vDiv, vTraces, Object.assign({}, sharedLayout, { yaxis: { title: 'Voltage (V)' } }), { responsive: true });
      Plotly.newPlot(pDiv, pTraces, Object.assign({}, sharedLayout, { yaxis: { title: 'Power (W)' } }), { responsive: true });
    })
    .catch(function(e) {
      vDiv.innerHTML = '<p style="padding:20px; color:#dc2626;">Failed to load: ' + e + '</p>';
      pDiv.innerHTML = '';
    });
}

loadTimeSeriesCharts();


// ══════════════════════════════════════════
//  Violations
// ══════════════════════════════════════════

(function() {
  fetch(BASE + '/violations')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      document.getElementById('violationsLoading').style.display = 'none';
      if (!data || data.length === 0) {
        document.getElementById('violationsEmpty').style.display = '';
        return;
      }
      var body = document.getElementById('violationsBody');
      data.slice(0, 100).forEach(function(v) {
        var tr = document.createElement('tr');
        tr.innerHTML =
          '<td>' + v.timestamp.substring(0, 19) + '</td>' +
          '<td><strong>' + v.node_id + '</strong></td>' +
          '<td>' + v.simulated_voltage.toFixed(2) + '</td>' +
          '<td>' + v.deviation_pct.toFixed(1) + '%</td>' +
          '<td><span class="status-badge status-badge--failed">' + v.type + '</span></td>';
        body.appendChild(tr);
      });
      document.getElementById('violationsTable').style.display = '';
      if (data.length > 100) {
        document.getElementById('violationsTable').insertAdjacentHTML('afterend',
          '<p class="muted" style="font-size:11px;">Showing first 100 of ' + data.length + ' violations.</p>');
      }
    })
    .catch(function() {
      document.getElementById('violationsLoading').textContent = 'No violations data available.';
    });
})();


// ══════════════════════════════════════════
//  Auto-refresh if running
// ══════════════════════════════════════════

(function() {
  var badges = document.querySelectorAll('.status-badge--running');
  if (badges.length > 0) {
    setTimeout(function() { location.reload(); }, 10000);
  }
})();
