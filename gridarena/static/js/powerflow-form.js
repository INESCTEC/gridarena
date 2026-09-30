(function () {
  var form = document.getElementById('pfForm');
  var msg = document.getElementById('msg');
  var resultCard = document.getElementById('resultCard');
  var resultMsg = document.getElementById('resultMsg');
  var resultLink = document.getElementById('resultLink');

  form.addEventListener('submit', async function (e) {
    e.preventDefault();

    var grid = document.getElementById('gridId').value;
    var phase = document.getElementById('phase').value;
    var start = document.getElementById('start').value;
    var end = document.getElementById('end').value;

    if (!grid) { msg.textContent = 'Please select a grid.'; return; }
    if (!phase) { msg.textContent = 'Please select a phase.'; return; }

    var url = new URL('/powerflow/' + grid + '/run', window.location.origin);
    url.searchParams.append('phase', phase);
    if (start) url.searchParams.append('start_time', start);
    if (end) url.searchParams.append('end_time', end);

    msg.textContent = 'Running power flow...';
    resultCard.style.display = 'none';
    document.getElementById('runBtn').disabled = true;

    try {
      var res = await fetch(url, { method: 'POST' });
      var j = await res.json();
      if (!res.ok) throw new Error(j.detail || JSON.stringify(j));

      msg.textContent = '';
      resultCard.style.display = 'block';
      resultMsg.textContent = 'Grid: ' + grid + ' | Phase: ' + phase
        + (start ? ' | From: ' + start : '') + (end ? ' | To: ' + end : '');
      resultLink.href = '/powerflow/ui/' + encodeURIComponent(grid) + '?phase=' + phase;
      resultLink.style.display = 'inline-block';
    } catch (err) {
      msg.textContent = 'Error: ' + err.message;
      resultCard.style.display = 'none';
    } finally {
      document.getElementById('runBtn').disabled = false;
    }
  });
})();
