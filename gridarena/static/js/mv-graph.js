/**
 * Shared function to render an MV grid graph with Plotly.
 * Connection point nodes are green and clickable.
 *
 * @param {string} containerId  - DOM element ID for the chart
 * @param {object} graphData    - {nodes: [...], edges: [...]} from the server
 * @param {function} onClickCP  - callback(connection_point_id) when a CP node is clicked
 */
function renderMVGraph(containerId, graphData, onClickCP) {
  var nodes = graphData.nodes;
  var edges = graphData.edges;

  var posMap = {};
  nodes.forEach(function (n) { posMap[n.id] = { x: n.x, y: n.y }; });

  var edgeX = [], edgeY = [];
  edges.forEach(function (e) {
    var from = posMap[e.from], to = posMap[e.to];
    if (from && to) {
      edgeX.push(from.x, to.x, null);
      edgeY.push(from.y, to.y, null);
    }
  });

  var edgeTrace = {
    x: edgeX, y: edgeY,
    mode: 'lines',
    line: { width: 2, color: '#94a3b8' },
    hoverinfo: 'none',
    showlegend: false
  };

  var groups = { substation: [], junction: [], connection_point: [], connected_cp: [] };
  nodes.forEach(function (n) {
    if (n.type === 'connection_point' && n.connected_lv && n.connected_lv.length > 0) {
      groups.connected_cp.push(n);
    } else if (n.type === 'connection_point') {
      groups.connection_point.push(n);
    } else if (n.type === 'substation') {
      groups.substation.push(n);
    } else {
      groups.junction.push(n);
    }
  });

  function makeTrace(arr, color, symbol, size, name) {
    return {
      x: arr.map(function (n) { return n.x; }),
      y: arr.map(function (n) { return n.y; }),
      text: arr.map(function (n) {
        var label = n.id;
        if (n.connection_point_id) label += ' [' + n.connection_point_id + ']';
        if (n.connected_lv) label += ' → ' + n.connected_lv.join(', ');
        return label;
      }),
      customdata: arr.map(function (n) { return n.connection_point_id || null; }),
      mode: 'markers+text',
      marker: { size: size, color: color, symbol: symbol, line: { width: 1, color: '#1f2937' } },
      textposition: 'top center',
      textfont: { size: 10 },
      name: name,
      hoverinfo: 'text'
    };
  }

  var traces = [
    edgeTrace,
    makeTrace(groups.substation, '#dc2626', 'square', 16, 'Substation'),
    makeTrace(groups.junction, '#2563eb', 'circle', 10, 'Junction'),
    makeTrace(groups.connection_point, '#10b981', 'diamond', 14, 'Connection Point (free)'),
    makeTrace(groups.connected_cp, '#f59e0b', 'diamond', 14, 'Connection Point (connected)')
  ];

  var layout = {
    showlegend: true,
    legend: { orientation: 'h', y: -0.05 },
    hovermode: 'closest',
    xaxis: { visible: false },
    yaxis: { visible: false, scaleanchor: 'x' },
    margin: { l: 10, r: 10, t: 10, b: 40 },
    plot_bgcolor: '#ffffff',
    paper_bgcolor: '#ffffff'
  };

  Plotly.newPlot(containerId, traces, layout, { responsive: true });

  if (onClickCP) {
    document.getElementById(containerId).on('plotly_click', function (data) {
      if (data.points && data.points.length > 0) {
        var pt = data.points[0];
        var cpId = pt.customdata;
        if (cpId) {
          onClickCP(cpId);
        }
      }
    });
  }
}

function ensurePlotly(callback) {
  if (window.Plotly) {
    callback();
  } else {
    var s = document.createElement('script');
    s.src = 'https://cdn.plot.ly/plotly-2.26.0.min.js';
    s.onload = callback;
    document.head.appendChild(s);
  }
}
