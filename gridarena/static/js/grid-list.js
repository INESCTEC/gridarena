(function () {
  var drop = document.getElementById('drop');
  var input = document.getElementById('fileInput');
  var label = document.getElementById('fileLabel');
  var validateBtn = document.getElementById('validateBtn');
  var uploadBtn = document.getElementById('uploadBtn');
  var msg = document.getElementById('uploadMsg');
  var previewSection = document.getElementById('previewSection');
  var previewErrors = document.getElementById('previewErrors');
  var previewTable = document.getElementById('previewTable');
  var previewGraph = document.getElementById('previewGraph');
  var selectedFile = null;

  function setFileLabel(f) { label.textContent = f ? f.name : 'No file selected'; }

  drop.addEventListener('click', function (e) {
    e.stopPropagation();
    input.value = '';
    input.click();
  });
  drop.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.value = ''; input.click(); }
  });

  ['dragenter', 'dragover'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); e.stopPropagation(); drop.classList.add('is-over'); });
  });
  ['dragleave', 'dragend'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); e.stopPropagation(); drop.classList.remove('is-over'); });
  });
  drop.addEventListener('drop', function (e) {
    e.preventDefault(); e.stopPropagation(); drop.classList.remove('is-over');
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      selectedFile = input.files[0] || null;
      setFileLabel(selectedFile);
      validateBtn.disabled = !selectedFile;
      uploadBtn.style.display = 'none';
      previewSection.style.display = 'none';
      msg.textContent = '';
    }
  });
  input.addEventListener('change', function () {
    selectedFile = input.files[0] || null;
    setFileLabel(selectedFile);
    validateBtn.disabled = !selectedFile;
    uploadBtn.style.display = 'none';
    previewSection.style.display = 'none';
    msg.textContent = '';
  });

  // ── Validate ──
  validateBtn.addEventListener('click', async function () {
    if (!selectedFile) return;
    msg.textContent = 'Validating...';
    var data = new FormData();
    data.append('file', selectedFile);

    try {
      var res = await fetch('/grid/validate', { method: 'POST', body: data });
      var result = await res.json();
      if (!res.ok) throw new Error(result.detail ? JSON.stringify(result.detail) : 'Validation failed');

      previewSection.style.display = 'block';
      if (result.valid) {
        previewErrors.innerHTML = '';
        msg.textContent = 'Validation passed.';
        uploadBtn.style.display = 'inline-block';
        uploadBtn.disabled = false;
        var g = result.grid;
        previewTable.innerHTML =
          '<tr><th>Grid ID</th><td>' + g.grid_id + '</td></tr>'
          + '<tr><th>Nodes</th><td>' + g.nodes.length + '</td></tr>'
          + '<tr><th>Cables</th><td>' + (g.cables ? g.cables.length : 0) + '</td></tr>'
          + '<tr><th>Connections</th><td>' + (g.connections ? g.connections.length : 0) + '</td></tr>';

        if (result.graph && result.graph.nodes.length > 0) {
          renderLVGraph(previewGraph, result.graph);
        }
      } else {
        uploadBtn.style.display = 'none';
        previewGraph.innerHTML = '';
        msg.textContent = 'Validation failed.';
        previewErrors.innerHTML = '<ul>' + result.errors.map(function (e) { return '<li>' + e + '</li>'; }).join('') + '</ul>';
        previewTable.innerHTML = '';
      }
    } catch (err) {
      msg.textContent = 'Error: ' + err.message;
    }
  });

  // ── Save ──
  function mapChoiceToYesNo(choice) {
    switch (choice) {
      case 'TEST': return { test: 'YES', train: 'NO' };
      case 'TRAIN': return { test: 'NO', train: 'YES' };
      case 'TEST_TRAIN': return { test: 'YES', train: 'YES' };
      default: return { test: 'NO', train: 'NO' };
    }
  }

  function buildUsageQuery() {
    var phase = mapChoiceToYesNo(document.getElementById('sel_phase').value);
    var topo  = mapChoiceToYesNo(document.getElementById('sel_topology').value);
    var volt  = mapChoiceToYesNo(document.getElementById('sel_voltage').value);
    var state = mapChoiceToYesNo(document.getElementById('sel_state').value);

    var p = new URLSearchParams();
    p.set('phase_detection_test', phase.test);
    p.set('phase_detection_train', phase.train);
    p.set('topology_detection_test', topo.test);
    p.set('topology_detection_train', topo.train);
    p.set('voltage_control_test', volt.test);
    p.set('voltage_control_train', volt.train);
    p.set('state_estimation_test', state.test);
    p.set('state_estimation_train', state.train);
    return p.toString();
  }

  uploadBtn.addEventListener('click', async function () {
    if (!selectedFile) return;
    uploadBtn.disabled = true;
    msg.textContent = 'Uploading...';

    var data = new FormData();
    data.append('file', selectedFile);

    try {
      var qs = buildUsageQuery();
      var res = await fetch('/grid/?' + qs, { method: 'POST', body: data });
      var j = await res.json();
      if (!res.ok) throw new Error(j.detail ? JSON.stringify(j.detail) : JSON.stringify(j));
      msg.textContent = j.message || 'Uploaded.';
      setTimeout(function () { location.reload(); }, 1500);
    } catch (err) {
      msg.textContent = 'Error: ' + err.message;
    } finally {
      uploadBtn.disabled = false;
    }
  });

  // ── Delete ──
  window.deleteGrid = async function (gid) {
    if (!confirm('Delete grid "' + gid + '" and all associated data?')) return;
    try {
      var res = await fetch('/grid/' + encodeURIComponent(gid), { method: 'DELETE' });
      var j = await res.json();
      if (!res.ok) throw new Error(j.detail || JSON.stringify(j));
      alert(j.message || 'Deleted.');
      location.reload();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  // ── Graph rendering ──
  function renderLVGraph(container, graphData) {
    function go() {
      var nodes = graphData.nodes;
      var edges = graphData.edges;
      var posMap = {};
      nodes.forEach(function (n) { posMap[n.id] = { x: n.x, y: n.y }; });

      var edgeX = [], edgeY = [];
      edges.forEach(function (e) {
        var f = posMap[e.from], t = posMap[e.to];
        if (f && t) { edgeX.push(f.x, t.x, null); edgeY.push(f.y, t.y, null); }
      });

      var ptNodes = nodes.filter(function (n) { return n.type === 'pt'; });
      var normalNodes = nodes.filter(function (n) { return n.type !== 'pt'; });

      Plotly.newPlot(container, [
        { x: edgeX, y: edgeY, mode: 'lines', line: { width: 2, color: '#94a3b8' }, hoverinfo: 'none', showlegend: false },
        {
          x: ptNodes.map(function (n) { return n.x; }),
          y: ptNodes.map(function (n) { return n.y; }),
          text: ptNodes.map(function (n) { return n.id; }),
          mode: 'markers+text', textposition: 'top center', textfont: { size: 10 },
          marker: { size: 14, color: '#dc2626', symbol: 'square', line: { width: 1, color: '#1f2937' } },
          name: 'PT (Reference)', hoverinfo: 'text'
        },
        {
          x: normalNodes.map(function (n) { return n.x; }),
          y: normalNodes.map(function (n) { return n.y; }),
          text: normalNodes.map(function (n) { return n.id; }),
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
    }

    if (window.Plotly) { go(); }
    else {
      var s = document.createElement('script');
      s.src = 'https://cdn.plot.ly/plotly-2.26.0.min.js';
      s.onload = go;
      document.head.appendChild(s);
    }
  }
})();
