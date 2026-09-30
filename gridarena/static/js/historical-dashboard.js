(function () {
  var data = window.HIST_DATA || [];
  if (!data.length) return;

  var PAGE_SIZE = 200;

  function groupByTime(records) {
    var map = {};
    records.forEach(function (r) {
      if (!map[r.datetime]) map[r.datetime] = [];
      map[r.datetime].push(r);
    });
    return map;
  }

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

  var seriesBaseUrl = '/historical/ui/' + window.DATABASE_ID + '/' + window.SERIES_ID;

  window.setQuickRange = function (range) {
    if (range === 'all') {
      window.location.href = seriesBaseUrl;
      return;
    }
    var timestamps = data.map(function (r) { return new Date(r.datetime).getTime(); });
    var maxTs = Math.max.apply(null, timestamps);
    var ms = { '1h': 3600000, '1d': 86400000, '7d': 604800000 };
    var startTs = new Date(maxTs - (ms[range] || 0));
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    var iso = startTs.getFullYear() + '-' + pad(startTs.getMonth() + 1) + '-' + pad(startTs.getDate()) + 'T' + pad(startTs.getHours()) + ':' + pad(startTs.getMinutes());
    window.location.href = seriesBaseUrl + '?start=' + iso;
  };

  // ── Plotly loader ──

  function withPlotly(fn) {
    if (window.Plotly) { fn(); return; }
    var s = document.createElement('script');
    s.src = 'https://cdn.plot.ly/plotly-2.26.0.min.js';
    s.onload = fn;
    document.head.appendChild(s);
  }

  // ── Overview: Power ──

  function renderPower() {
    var el = document.getElementById('chartPower');
    if (!el) return;

    var byTime = groupByTime(data);
    var times = Object.keys(byTime).sort();
    var phaseKeys = ['R', 'S', 'T'];
    var totals = { R: [], S: [], T: [], Total: [] };

    times.forEach(function (t) {
      var sums = { R: 0, S: 0, T: 0 };
      var anyPhase = false;
      byTime[t].forEach(function (r) {
        if (r.phase && sums.hasOwnProperty(r.phase)) { sums[r.phase] += (r.power_active || 0); anyPhase = true; }
      });
      phaseKeys.forEach(function (ph) { totals[ph].push(sums[ph]); });
      totals['Total'].push(anyPhase ? sums.R + sums.S + sums.T : (byTime[t][0].power_active || 0));
    });

    var traces = [
      { x: times, y: totals['Total'], mode: 'lines', name: 'Active Power', line: { color: '#1e3a5f', width: 2 } },
      { x: times, y: totals['R'], mode: 'lines', name: 'Phase R', line: { color: '#ef4444', width: 1 }, visible: 'legendonly' },
      { x: times, y: totals['S'], mode: 'lines', name: 'Phase S', line: { color: '#f59e0b', width: 1 }, visible: 'legendonly' },
      { x: times, y: totals['T'], mode: 'lines', name: 'Phase T', line: { color: '#2563eb', width: 1 }, visible: 'legendonly' }
    ];

    Plotly.newPlot('chartPower', traces, {
      margin: { l: 50, r: 20, t: 10, b: 40 }, legend: { orientation: 'h', y: -0.18 },
      yaxis: { title: 'Active Power (kW)' },
      plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
    }, { responsive: true });
  }

  // ── Overview: Voltage ──

  function renderVoltage() {
    var el = document.getElementById('chartVoltage');
    if (!el) return;

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

    Plotly.newPlot('chartVoltage', [
      { x: times, y: maxs, mode: 'lines', name: 'Max', line: { color: '#ef4444', width: 1 } },
      { x: times, y: avgs, mode: 'lines', name: 'Avg', line: { color: '#2563eb', width: 2 } },
      { x: times, y: mins, mode: 'lines', name: 'Min', line: { color: '#f59e0b', width: 1 }, fill: 'tonexty', fillcolor: 'rgba(37,99,235,0.06)' }
    ], {
      margin: { l: 50, r: 20, t: 10, b: 40 }, legend: { orientation: 'h', y: -0.18 },
      yaxis: { title: 'Voltage (V)' },
      plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff'
    }, { responsive: true });
  }

  // ── Raw Data tab ──

  var rawPage = 0;
  var filteredData = data;

  function renderRawTable() {
    var phaseFilter = document.getElementById('rawPhaseFilter').value;

    filteredData = data.filter(function (r) {
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
      tr.innerHTML = '<td>' + r.datetime + '</td><td>' + r.phase
        + '</td><td>' + (r.power_active != null ? r.power_active.toFixed(2) : '') + '</td><td>'
        + (r.power_reactive != null ? r.power_reactive.toFixed(2) : '') + '</td><td>'
        + (r.voltage_magnitude != null ? r.voltage_magnitude.toFixed(1) : '') + '</td><td>'
        + (r.voltage_angle != null ? r.voltage_angle.toFixed(2) : '') + '</td>';
      body.appendChild(tr);
    }

    rawPage++;
    document.getElementById('rawLoadMore').style.display = end < filteredData.length ? 'inline-block' : 'none';
  }

  document.getElementById('rawApply').addEventListener('click', renderRawTable);
  document.getElementById('rawLoadMore').addEventListener('click', function () { appendRawRows(false); });

  // ── Init charts ──

  withPlotly(function () {
    if (window.HAS_POWER) renderPower();
    if (window.HAS_VOLTAGE) renderVoltage();
    renderRawTable();
  });

})();
