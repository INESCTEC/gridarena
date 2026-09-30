(function () {
  var canvas = document.getElementById('gridBg');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');

  var nodes = [];
  var edges = [];
  var NODE_COUNT = 50;
  var CONNECT_DIST = 280;
  var PULSE_SPEED = 0.015;
  var DRIFT_SPEED = 0.25;

  function resize() {
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
  }

  function init() {
    resize();
    nodes = [];

    for (var i = 0; i < NODE_COUNT; i++) {
      nodes.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * DRIFT_SPEED,
        vy: (Math.random() - 0.5) * DRIFT_SPEED,
        r: 4 + Math.random() * 5,
        phase: Math.random() * Math.PI * 2
      });
    }

    rebuildEdges();
  }

  function rebuildEdges() {
    edges = [];
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var dx = nodes[i].x - nodes[j].x;
        var dy = nodes[i].y - nodes[j].y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < CONNECT_DIST) {
          edges.push({ a: i, b: j, dist: dist });
        }
      }
    }
  }

  var frame = 0;

  function draw() {
    frame++;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      n.x += n.vx;
      n.y += n.vy;
      if (n.x < 0 || n.x > canvas.width) n.vx *= -1;
      if (n.y < 0 || n.y > canvas.height) n.vy *= -1;
      n.phase += PULSE_SPEED;
    }

    if (frame % 40 === 0) rebuildEdges();

    // Edges
    for (var e = 0; e < edges.length; e++) {
      var edge = edges[e];
      var a = nodes[edge.a];
      var b = nodes[edge.b];
      var proximity = 1 - edge.dist / CONNECT_DIST;
      var alpha = 0.4 * proximity;

      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = 'rgba(37, 99, 235, ' + alpha + ')';
      ctx.lineWidth = 1.5 + 2 * proximity;
      ctx.stroke();

      // Pulse dot
      var t = (Math.sin(a.phase + frame * 0.03) + 1) / 2;
      var px = a.x + (b.x - a.x) * t;
      var py = a.y + (b.y - a.y) * t;

      ctx.beginPath();
      ctx.arc(px, py, 3 + proximity * 2, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(96, 165, 250, ' + (0.4 + 0.4 * proximity) + ')';
      ctx.fill();
    }

    // Nodes
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      var pulse = 0.5 + 0.4 * Math.sin(n.phase);

      // Outer glow
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r * 3, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(37, 99, 235, ' + (pulse * 0.12) + ')';
      ctx.fill();

      // Body
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(37, 99, 235, ' + pulse + ')';
      ctx.fill();

      // Core
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r * 0.4, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(191, 219, 254, ' + (pulse + 0.2) + ')';
      ctx.fill();
    }

    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', function () { resize(); rebuildEdges(); });
  init();
  draw();
})();
