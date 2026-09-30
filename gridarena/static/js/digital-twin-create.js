/* Digital Twin — creation wizard JS (per-node assignment mode) */

var currentStep = 1;
var totalSteps = 5;
var gridGraphData = null;
var nodeAssignments = {};
var selectedNodeId = null;

// ══════════════════════════════════════════
//  Step navigation
// ══════════════════════════════════════════

function goStep(n) {
  if (n < 1 || n > totalSteps) return;
  if (n > currentStep && !validateCurrentStep()) return;

  document.getElementById('step' + currentStep).style.display = 'none';
  document.getElementById('step' + n).style.display = '';
  currentStep = n;
  updateProgress();

  if (n === 3 && !gridGraphData) loadGridGraph();
  if (n === 5) updateReview();

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateProgress() {
  document.querySelectorAll('.dt-progress__step').forEach(function(el) {
    var s = parseInt(el.getAttribute('data-step'));
    el.classList.remove('dt-progress__step--active', 'dt-progress__step--done');
    if (s === currentStep) el.classList.add('dt-progress__step--active');
    else if (s < currentStep) el.classList.add('dt-progress__step--done');
  });
}

function validateCurrentStep() {
  if (currentStep === 1 && !document.getElementById('gridId').value) {
    alert('Please select a grid.'); return false;
  }
  if (currentStep === 2 && !document.getElementById('srcUrl').value.trim()) {
    alert('Please enter a source URL.'); return false;
  }
  if (currentStep === 2) {
    var auth = document.getElementById('srcAuth').value;
    if (auth !== 'none' && !document.getElementById('srcSecretRef').value.trim()) {
      alert('Please enter the environment variable name for the secret.'); return false;
    }
  }
  if (currentStep === 3 && Object.keys(nodeAssignments).length === 0) {
    alert('Please assign at least one node.'); return false;
  }
  return true;
}

// ══════════════════════════════════════════
//  Auth field toggle
// ══════════════════════════════════════════

function toggleAuthFields() {
  var show = document.getElementById('srcAuth').value !== 'none';
  document.getElementById('secretRefRow').style.display = show ? '' : 'none';
  document.getElementById('secretHeaderRow').style.display = show ? '' : 'none';
}

// ══════════════════════════════════════════
//  Grid graph
// ══════════════════════════════════════════

function loadGridGraph() {
  var gid = document.getElementById('gridId').value;
  if (!gid) return;

  fetch('/digital-twins/grid-graph/' + encodeURIComponent(gid))
    .then(function(r) {
      if (!r.ok) throw new Error('Failed to load grid');
      return r.json();
    })
    .then(function(data) {
      gridGraphData = data;
      renderGraph(data.graph);
    })
    .catch(function(e) {
      document.getElementById('gridGraph').innerHTML = '<p style="padding:20px; color:#dc2626;">Failed to load grid: ' + e.message + '</p>';
    });
}

function renderGraph(graph) {
  var nodeX = [], nodeY = [], nodeText = [], nodeColor = [];
  var edgeX = [], edgeY = [];

  var posMap = {};
  graph.nodes.forEach(function(n) { posMap[n.id] = { x: n.x, y: n.y }; });

  graph.edges.forEach(function(e) {
    var f = posMap[e.source], t = posMap[e.target];
    if (f && t) {
      edgeX.push(f.x, t.x, null);
      edgeY.push(f.y, t.y, null);
    }
  });

  graph.nodes.forEach(function(n) {
    nodeX.push(n.x);
    nodeY.push(n.y);
    var assigned = nodeAssignments[n.id];
    var label = n.id;
    if (assigned) label += ' [' + assigned.phase + ']';
    nodeText.push(label);
    if (n.type === 'pt') nodeColor.push('#dc2626');
    else if (assigned) nodeColor.push('#059669');
    else nodeColor.push('#3b82f6');
  });

  var edgeTrace = {
    x: edgeX, y: edgeY, mode: 'lines',
    line: { color: '#94a3b8', width: 2 },
    hoverinfo: 'none', type: 'scatter',
  };
  var nodeTrace = {
    x: nodeX, y: nodeY, mode: 'markers+text',
    marker: { size: 14, color: nodeColor, line: { width: 1, color: '#fff' } },
    text: nodeText, textposition: 'top center', textfont: { size: 10 },
    hoverinfo: 'text', type: 'scatter', customdata: graph.nodes.map(function(n) { return n.id; }),
  };

  var layout = {
    showlegend: false,
    xaxis: { showgrid: false, zeroline: false, showticklabels: false },
    yaxis: { showgrid: false, zeroline: false, showticklabels: false },
    margin: { t: 10, b: 10, l: 10, r: 10 },
    hovermode: 'closest',
  };

  Plotly.newPlot('gridGraph', [edgeTrace, nodeTrace], layout, { responsive: true, displayModeBar: false });

  document.getElementById('gridGraph').on('plotly_click', function(data) {
    if (data.points && data.points.length > 0) {
      var pt = data.points[0];
      if (pt.customdata) selectNode(pt.customdata);
    }
  });
}

// ══════════════════════════════════════════
//  Query parameter rows
// ══════════════════════════════════════════

function addParamRow(key, value) {
  var list = document.getElementById('nfParamsList');
  var row = document.createElement('div');
  row.className = 'field';
  row.style.marginBottom = '4px';
  row.innerHTML =
    '<input class="input nf-param-key" type="text" placeholder="key" value="' + (key || '') + '" style="width:100px;">' +
    '<span style="margin:0 4px; color:#6b7280;">=</span>' +
    '<input class="input nf-param-val" type="text" placeholder="value" value="' + (value || '') + '" style="width:130px;">' +
    '<button type="button" class="btn" style="height:26px; padding:0 8px; font-size:11px; margin-left:4px; color:#dc2626;" onclick="this.parentElement.remove()">&#x2715;</button>';
  list.appendChild(row);
}

function setParamRows(params) {
  var list = document.getElementById('nfParamsList');
  list.innerHTML = '';
  var keys = Object.keys(params || {});
  if (keys.length === 0) {
    addParamRow('', '');
  } else {
    keys.forEach(function(k) { addParamRow(k, params[k]); });
  }
}

function getParamRows() {
  var params = {};
  var keys = document.querySelectorAll('#nfParamsList .nf-param-key');
  var vals = document.querySelectorAll('#nfParamsList .nf-param-val');
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i].value.trim();
    var v = vals[i].value.trim();
    if (k) params[k] = v;
  }
  return params;
}


// ══════════════════════════════════════════
//  Node assignment panel
// ══════════════════════════════════════════

function selectNode(nodeId) {
  selectedNodeId = nodeId;
  document.getElementById('nodePanelPlaceholder').style.display = 'none';
  document.getElementById('nodeForm').style.display = '';
  document.getElementById('nfNodeId').textContent = nodeId;

  var existing = nodeAssignments[nodeId];
  if (existing) {
    document.getElementById('nfPhase').value = existing.phase || 'R';
    setParamRows(existing.query_params || {});
    document.getElementById('nfInterval').value = existing.update_interval_seconds || 60;
    document.getElementById('nfTimeout').value = existing.timeout_seconds || 30;
    document.getElementById('nfTimestamp').value = existing.mapping.timestamp || 'data[0].datetime';
    document.getElementById('nfActivePower').value = existing.mapping.active_power || '';
    document.getElementById('nfActivePowerFactor').value = existing.mapping.active_power_factor != null ? existing.mapping.active_power_factor : 1;
    document.getElementById('nfReactivePower').value = existing.mapping.reactive_power || '';
    document.getElementById('nfReactivePowerFactor').value = existing.mapping.reactive_power_factor != null ? existing.mapping.reactive_power_factor : 1;
    document.getElementById('nfVoltageMag').value = existing.mapping.voltage_magnitude || '';
    document.getElementById('nfVoltageMagFactor').value = existing.mapping.voltage_magnitude_factor != null ? existing.mapping.voltage_magnitude_factor : 1;
  } else {
    document.getElementById('nfPhase').value = 'R';
    setParamRows({});
    document.getElementById('nfInterval').value = 60;
    document.getElementById('nfTimeout').value = 30;
    document.getElementById('nfTimestamp').value = 'data[0].datetime';
    document.getElementById('nfActivePower').value = '';
    document.getElementById('nfActivePowerFactor').value = 1;
    document.getElementById('nfReactivePower').value = '';
    document.getElementById('nfReactivePowerFactor').value = 1;
    document.getElementById('nfVoltageMag').value = '';
    document.getElementById('nfVoltageMagFactor').value = 1;
  }
}

function assignNode() {
  if (!selectedNodeId) return;

  var params = getParamRows();

  var ap = document.getElementById('nfActivePower').value.trim();
  var vm = document.getElementById('nfVoltageMag').value.trim();
  if (!ap && !vm) {
    alert('Specify at least an active power or voltage magnitude mapping path.'); return;
  }

  nodeAssignments[selectedNodeId] = {
    node_id: selectedNodeId,
    phase: document.getElementById('nfPhase').value,
    query_params: params,
    update_interval_seconds: parseInt(document.getElementById('nfInterval').value) || 60,
    timeout_seconds: parseInt(document.getElementById('nfTimeout').value) || 30,
    mapping: {
      timestamp: document.getElementById('nfTimestamp').value || 'data[0].datetime',
      active_power: ap || null,
      active_power_factor: parseFloat(document.getElementById('nfActivePowerFactor').value) || 1,
      reactive_power: document.getElementById('nfReactivePower').value.trim() || null,
      reactive_power_factor: parseFloat(document.getElementById('nfReactivePowerFactor').value) || 1,
      voltage_magnitude: vm || null,
      voltage_magnitude_factor: parseFloat(document.getElementById('nfVoltageMagFactor').value) || 1,
    },
  };

  refreshAssignTable();
  if (gridGraphData) renderGraph(gridGraphData.graph);
}

function removeAssignment() {
  if (!selectedNodeId) return;
  delete nodeAssignments[selectedNodeId];
  refreshAssignTable();
  if (gridGraphData) renderGraph(gridGraphData.graph);

  document.getElementById('nodeForm').style.display = 'none';
  document.getElementById('nodePanelPlaceholder').style.display = '';
  selectedNodeId = null;
}

function removeAssignmentById(nodeId) {
  delete nodeAssignments[nodeId];
  refreshAssignTable();
  if (gridGraphData) renderGraph(gridGraphData.graph);
  if (selectedNodeId === nodeId) {
    document.getElementById('nodeForm').style.display = 'none';
    document.getElementById('nodePanelPlaceholder').style.display = '';
    selectedNodeId = null;
  }
}

function refreshAssignTable() {
  var keys = Object.keys(nodeAssignments);
  document.getElementById('assignCount').textContent = keys.length;
  var body = document.getElementById('assignBody');
  body.innerHTML = '';
  if (keys.length === 0) {
    body.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:16px; color:#6b7280;">No nodes assigned yet.</td></tr>';
    return;
  }
  keys.forEach(function(nid) {
    var a = nodeAssignments[nid];
    var tr = document.createElement('tr');
    tr.style.cursor = 'pointer';
    tr.onclick = function() { selectNode(nid); };
    tr.innerHTML =
      '<td><strong>' + nid + '</strong></td>' +
      '<td>' + a.phase + '</td>' +
      '<td style="font-size:11px; font-family:monospace;">' + JSON.stringify(a.query_params) + '</td>' +
      '<td>' + a.update_interval_seconds + 's</td>' +
      '<td style="font-size:11px; font-family:monospace;">' + (a.mapping.active_power || '—') + '</td>' +
      '<td style="font-size:11px; font-family:monospace;">' + (a.mapping.voltage_magnitude || '—') + '</td>' +
      '<td><button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10px; color:#dc2626;" onclick="event.stopPropagation(); removeAssignmentById(\'' + nid + '\')">Remove</button></td>';
    body.appendChild(tr);
  });
}

// ══════════════════════════════════════════
//  Review
// ══════════════════════════════════════════

function updateReview() {
  var grid = document.getElementById('reviewGrid');
  grid.innerHTML = '';
  var items = [
    ['Grid', document.getElementById('gridId').value],
    ['Name', document.getElementById('dtName').value || '(unnamed)'],
    ['Source URL', document.getElementById('srcUrl').value],
    ['Auth Type', document.getElementById('srcAuth').value],
    ['Nodes Assigned', Object.keys(nodeAssignments).length],
    ['PF Phase', document.getElementById('pfPhase').value],
    ['Voltage Ref', document.getElementById('pfVoltRef').value + ' V'],
  ];
  items.forEach(function(pair) {
    grid.innerHTML += '<dt>' + pair[0] + '</dt><dd>' + pair[1] + '</dd>';
  });

  var count = Object.keys(nodeAssignments).length;
  document.getElementById('reviewAssignCount').textContent = count;
  document.getElementById('reviewAssignments').textContent = JSON.stringify(
    Object.values(nodeAssignments), null, 2
  );
}

// ══════════════════════════════════════════
//  Build payload & submit
// ══════════════════════════════════════════

function buildSourceConfig() {
  var headers = {};
  try { headers = JSON.parse(document.getElementById('srcHeaders').value || '{}'); } catch(e) {}
  var cfg = {
    source_type: 'http',
    url: document.getElementById('srcUrl').value,
    method: document.getElementById('srcMethod').value,
    headers: headers,
    query_params: {},
    auth_type: document.getElementById('srcAuth').value,
    timeout_seconds: 30,
    retry_count: 3,
  };
  var ref = document.getElementById('srcSecretRef').value.trim();
  if (ref) cfg.secret_ref = ref;
  var hdr = document.getElementById('srcSecretHeader').value.trim();
  if (hdr) cfg.secret_header = hdr;
  return cfg;
}

document.getElementById('createForm').addEventListener('submit', function(e) {
  e.preventDefault();
  var msg = document.getElementById('createMsg');
  var btn = document.getElementById('createBtn');
  msg.textContent = 'Creating digital twin...';
  msg.style.color = '#475569';
  btn.disabled = true;

  var assignments = Object.values(nodeAssignments);

  var body = {
    grid_id: document.getElementById('gridId').value,
    name: document.getElementById('dtName').value,
    description: document.getElementById('dtDesc').value,
    update_interval_seconds: assignments.length > 0 ? assignments[0].update_interval_seconds : 60,
    broker_type: 'redis',
    source_config: buildSourceConfig(),
    node_assignments: assignments,
    powerflow_config: {
      phase: document.getElementById('pfPhase').value,
      voltage_ref: parseFloat(document.getElementById('pfVoltRef').value) || 230,
    },
  };
  var topic = document.getElementById('brokerTopic').value.trim();
  if (topic) body.broker_topic = topic;

  fetch('/digital-twins/', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  })
  .then(function(r) {
    if (!r.ok) return r.json().then(function(d) { throw new Error(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail)); });
    return r.json();
  })
  .then(function(data) {
    msg.textContent = 'Digital twin created! Redirecting...';
    msg.style.color = '#059669';
    setTimeout(function() { window.location.href = '/digital-twins/ui/' + data.digital_twin_id; }, 1200);
  })
  .catch(function(e) {
    msg.textContent = 'Error: ' + e.message;
    msg.style.color = '#dc2626';
    btn.disabled = false;
  });
});

// Reset graph when grid changes
document.getElementById('gridId').addEventListener('change', function() {
  gridGraphData = null;
  nodeAssignments = {};
  selectedNodeId = null;
  refreshAssignTable();
});

updateProgress();
