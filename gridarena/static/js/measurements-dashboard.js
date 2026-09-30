(function () {
  var data = window.HIST_DATA || [];
  if (!data.length) return;

  var NOMINAL_V = 230;
  var PAGE_SIZE = 200;

  // ── Helpers ──

  function unique(arr, key) {
    var s = new Set();
    arr.forEach(function (r) { if (r[key] != null) s.add(r[key]); });
    return Array.from(s).sort();
  }

  function groupByTime(records) {
    var map = {};
    records.forEach(function (r) {
      if (!map[r.datetime]) map[r.datetime] = [];
      map[r.datetime].push(r);
    });
    return map;
  }

  // ── Summary cards ──

  var voltages = data.map(function (r) { return r.voltage_magnitude; }).filter(function (v) { return v != null; });
  var powers = data.map(function (r) { return r.power_active; }).filter(function (v) { return v != null; });

  document.getElementById('scAvgV').textContent = voltages.length ? (voltages.reduce(function (a, b) { return a + b; }, 0) / voltages.length).toFixed(1) : '—';
  document.getElementById('scMinV').textContent = voltages.length ? Math.min.apply(null, voltages).toFixed(1) : '—';
  document.getElementById('scMaxV').textContent = voltages.length ? Math.max.apply(null, voltages).toFixed(1) : '—';
  document.getElementById('scMaxP').textContent = powers.length ? Math.max.apply(null, powers).toFixed(2) : '—';
  document.getElementById('scCount').textContent = data.length;

  // ── Tabs ──

  document.querySelectorAll('.dash-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      document.querySelectorAll('.dash-tab').forEach(function (t) { t.classList.remove('active'); });
      document.querySelectorAll('.dash-pane').forEach(function (p) { p.classList.remove('active'); });
      tab.classList.add('active');
      document.getElementById('pane-' + tab.dataset.tab).classList.add('active');
    });
  });

  // ── Quick range ──

  window.setQuickRange = function (range) {
    if (range === 'all') {
      window.location.href = '/measurements/ui/' + window.GRID_ID;
      return;
    }
    var timestamps = data.map(function (r) { return new Date(r.datetime).getTime(); });
    var maxTs = Math.max.apply(null, timestamps);
    var ms = { '1h': 3600000, '1d': 86400000, '7d': 604800000 };
    var startTs = new Date(maxTs - (ms[range] || 0));
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    var iso = startTs.getFullYear() + '-' + pad(startTs.getMonth() + 1) + '-' + pad(startTs.getDate()) + 'T' + pad(startTs.getHours()) + ':' + pad(startTs.getMinutes());
    window.location.href = '/measurements/ui/' + window.GRID_ID + '?start=' + iso;
  };

  // ── Plotly loader ──

  function withPlotly(fn) {
    if (window.Plotly) { fn(); return; }
    var s = document.createElement('script');
    s.src = 'https://cdn.plot.ly/plotly-2.26.0.min.js';
    s.onload = fn;
    document.head.appendChild(s);
  }

  // ── Overview: Voltage Envelope ──

  function renderVoltageEnvelope() {
    var byTime = groupByTime(data);
    var times = Object.keys(byTime).sort();
    var mins = [], avgs = [], maxs = [];

    times.forEach(function (t) {
      var vs = byTime[t].map(function (r) { return r.voltage_magnitude; }).filter(function (v) { return v != null; });
      if (vs.length) {
        mins.push(Math.min.apply(null, vs));
        avgs.push(vs.reduce(function (a, b) { return a + b; }, 0) / vs.length);
        maxs.push(Math.max.apply(null, vs));
      } else {
        mins.push(null); avgs.push(null); maxs.push(null);
      }
    });

    Plotly.newPlot('chartVoltageEnvelope', [
      { x: times, y: maxs, mode: 'lines', name: 'Max', line: { color: '#ef4444', width: 1 }, fill: 'none' },
      { x: times, y: avgs, mode: 'lines', name: 'Avg', line: { color: '#2563eb', width: 2 } },
      { x: times, y: mins, mode: 'lines', name: 'Min', line: { color: '#f59e0b', width: 1 }, fill: 'tonexty', fillcolor: 'rgba(37,99,235,0.06)' },
      { x: [times[0], times[times.length - 1]], y: [NOMINAL_V, NOMINAL_V], mode: 'lines', name: 'Nominal (230V)', line: { color: '#10b981', dash: 'dash', width: 1 } }
    ], {
      margin: { l: 50, r: 20, t: 10, b: 40 }, legend: { orientation: 'h', y: -0.18 },
      yaxis: { title: 'Voltage (V)' }, xaxis: { title: '' },
      plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
    }, { responsive: true });
  }

  // ── Overview: Power Total ──

  function renderPowerTotal() {
    var byTime = groupByTime(data);
    var times = Object.keys(byTime).sort();
    var totals = {}, phaseKeys = ['R', 'S', 'T'];

    phaseKeys.forEach(function (ph) { totals[ph] = []; });
    totals['Total'] = [];

    times.forEach(function (t) {
      var sums = { R: 0, S: 0, T: 0 };
      byTime[t].forEach(function (r) {
        if (r.phase && sums.hasOwnProperty(r.phase)) sums[r.phase] += (r.power_active || 0);
      });
      phaseKeys.forEach(function (ph) { totals[ph].push(sums[ph]); });
      totals['Total'].push(sums.R + sums.S + sums.T);
    });

    var traces = [
      { x: times, y: totals['Total'], mode: 'lines', name: 'Total', line: { color: '#1e3a5f', width: 2 } },
      { x: times, y: totals['R'], mode: 'lines', name: 'Phase R', line: { color: '#ef4444', width: 1 }, visible: 'legendonly' },
      { x: times, y: totals['S'], mode: 'lines', name: 'Phase S', line: { color: '#f59e0b', width: 1 }, visible: 'legendonly' },
      { x: times, y: totals['T'], mode: 'lines', name: 'Phase T', line: { color: '#2563eb', width: 1 }, visible: 'legendonly' }
    ];

    Plotly.newPlot('chartPowerTotal', traces, {
      margin: { l: 50, r: 20, t: 10, b: 40 }, legend: { orientation: 'h', y: -0.18 },
      yaxis: { title: 'Active Power (kW)' },
      plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
    }, { responsive: true });
  }

  // ── Overview: Heatmap ──

  function renderHeatmap(metric) {
    var field = metric === 'power' ? 'power_active' : 'voltage_magnitude';
    var label = metric === 'power' ? 'Active Power (kW)' : 'Voltage (V)';

    var allNodes = unique(data, 'node_id');
    var allPhases = unique(data, 'phase').filter(function (p) { return p !== 'N/A'; });
    var rows = [];
    allNodes.forEach(function (n) {
      allPhases.forEach(function (p) { rows.push(n + ' (' + p + ')'); });
    });

    var times = unique(data, 'datetime');
    var timeIdx = {};
    times.forEach(function (t, i) { timeIdx[t] = i; });
    var rowIdx = {};
    rows.forEach(function (r, i) { rowIdx[r] = i; });

    var z = rows.map(function () { return times.map(function () { return null; }); });

    data.forEach(function (r) {
      var key = r.node_id + ' (' + r.phase + ')';
      if (rowIdx[key] !== undefined && timeIdx[r.datetime] !== undefined) {
        z[rowIdx[key]][timeIdx[r.datetime]] = r[field];
      }
    });

    Plotly.newPlot('chartHeatmap', [{
      z: z, x: times, y: rows, type: 'heatmap',
      colorscale: metric === 'power' ? 'RdBu' : 'YlOrRd', reversescale: metric !== 'power',
      colorbar: { title: label }
    }], {
      margin: { l: 120, r: 20, t: 10, b: 50 },
      xaxis: { title: 'Datetime', tickangle: -45 },
      yaxis: { title: '', autorange: 'reversed' },
      plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
    }, { responsive: true });
  }

  document.getElementById('heatmapMetric').addEventListener('change', function () {
    withPlotly(function () { renderHeatmap(document.getElementById('heatmapMetric').value); });
  });

  // ── Time Series tab ──

  function renderTimeSeries() {
    var selNodes = Array.from(document.getElementById('tsNodeSelect').selectedOptions).map(function (o) { return o.value; });
    var selPhases = [];
    document.querySelectorAll('.tsPhase:checked').forEach(function (cb) { selPhases.push(cb.value); });
    var metric = document.getElementById('tsMetric').value;
    var label = { voltage_magnitude: 'Voltage (V)', power_active: 'Active Power (kW)', power_reactive: 'Reactive Power (kVAr)' }[metric];

    var traces = [];
    selNodes.forEach(function (node) {
      selPhases.forEach(function (ph) {
        var subset = data.filter(function (r) { return r.node_id === node && r.phase === ph; });
        if (!subset.length) return;
        traces.push({
          x: subset.map(function (r) { return r.datetime; }),
          y: subset.map(function (r) { return r[metric]; }),
          mode: 'lines', name: node + ' (' + ph + ')'
        });
      });
    });

    Plotly.newPlot('chartTimeSeries', traces, {
      margin: { l: 50, r: 20, t: 10, b: 40 }, legend: { orientation: 'h', y: -0.15 },
      yaxis: { title: label },
      plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
    }, { responsive: true });
  }

  document.getElementById('tsUpdate').addEventListener('click', function () {
    withPlotly(renderTimeSeries);
  });

  // ── Node Comparison tab ──

  function renderNodeComparison() {
    var nodeMap = {};
    data.forEach(function (r) {
      if (!nodeMap[r.node_id]) nodeMap[r.node_id] = { vSum: 0, vCount: 0, pMax: 0 };
      if (r.voltage_magnitude != null) { nodeMap[r.node_id].vSum += r.voltage_magnitude; nodeMap[r.node_id].vCount++; }
      if (r.power_active != null) { nodeMap[r.node_id].pMax = Math.max(nodeMap[r.node_id].pMax, Math.abs(r.power_active)); }
    });

    var nodes = Object.keys(nodeMap).sort();
    var avgVs = nodes.map(function (n) { return nodeMap[n].vCount ? (nodeMap[n].vSum / nodeMap[n].vCount) : 0; });
    var maxPs = nodes.map(function (n) { return nodeMap[n].pMax; });

    Plotly.newPlot('chartNodeAvgV', [{
      x: nodes, y: avgVs, type: 'bar',
      marker: { color: '#2563eb' }
    }, {
      x: [nodes[0], nodes[nodes.length - 1]], y: [NOMINAL_V, NOMINAL_V],
      mode: 'lines', name: 'Nominal', line: { color: '#10b981', dash: 'dash' }
    }], {
      margin: { l: 50, r: 20, t: 10, b: 60 }, showlegend: false,
      yaxis: { title: 'Avg Voltage (V)' }, xaxis: { tickangle: -45 },
      plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
    }, { responsive: true });

    Plotly.newPlot('chartNodeMaxP', [{
      x: nodes, y: maxPs, type: 'bar',
      marker: { color: '#f59e0b' }
    }], {
      margin: { l: 50, r: 20, t: 10, b: 60 }, showlegend: false,
      yaxis: { title: 'Max |Active Power| (kW)' }, xaxis: { tickangle: -45 },
      plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
    }, { responsive: true });
  }

  // ── Raw Data tab ──

  var rawPage = 0;
  var filteredData = data;

  function renderRawTable() {
    var nodeFilter = document.getElementById('rawNodeFilter').value;
    var phaseFilter = document.getElementById('rawPhaseFilter').value;

    filteredData = data.filter(function (r) {
      if (nodeFilter && r.node_id !== nodeFilter) return false;
      if (phaseFilter && r.phase !== phaseFilter) return false;
      return true;
    });

    rawPage = 0;
    document.getElementById('rawCount').textContent = filteredData.length + ' records';
    appendRawRows(true);
  }

  function appendRawRows(reset) {
    var body = document.getElementById('rawBody');
    if (reset) body.innerHTML = '';

    var start = rawPage * PAGE_SIZE;
    var end = Math.min(start + PAGE_SIZE, filteredData.length);

    for (var i = start; i < end; i++) {
      var r = filteredData[i];
      var tr = document.createElement('tr');
      tr.innerHTML = '<td>' + r.datetime + '</td><td>' + r.node_id + '</td><td>' + r.phase
        + '</td><td>' + (r.power_active != null ? r.power_active.toFixed(2) : '') + '</td><td>'
        + (r.power_reactive != null ? r.power_reactive.toFixed(2) : '') + '</td><td>'
        + (r.voltage_magnitude != null ? r.voltage_magnitude.toFixed(1) : '') + '</td>';
      body.appendChild(tr);
    }

    rawPage++;
    document.getElementById('rawLoadMore').style.display = end < filteredData.length ? 'inline-block' : 'none';
  }

  document.getElementById('rawApply').addEventListener('click', renderRawTable);
  document.getElementById('rawLoadMore').addEventListener('click', function () { appendRawRows(false); });

  // ── Init all charts ──

  withPlotly(function () {
    renderVoltageEnvelope();
    renderPowerTotal();
    renderHeatmap('voltage');
    renderTimeSeries();
    renderNodeComparison();
    renderRawTable();
  });

})();
