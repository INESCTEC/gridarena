/* Digital Twin — overview / list page JS */

function filterTable() {
  var q = document.getElementById('dtSearch').value.toLowerCase();
  document.querySelectorAll('#twinsTable tbody tr').forEach(function(row) {
    var id = row.getAttribute('data-id') || '';
    var name = row.getAttribute('data-name') || '';
    var grid = row.getAttribute('data-grid') || '';
    var match = id.indexOf(q) !== -1 || name.indexOf(q) !== -1 || grid.indexOf(q) !== -1;
    row.style.display = match ? '' : 'none';
  });
}

function startTwin(id) {
  fetch('/digital-twins/' + id + '/start', { method: 'POST' })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
      return r.json();
    })
    .then(function() { location.reload(); })
    .catch(function(e) { alert('Error starting twin: ' + e.message); });
}

function stopTwin(id) {
  fetch('/digital-twins/' + id + '/stop', { method: 'POST' })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
      return r.json();
    })
    .then(function() { location.reload(); })
    .catch(function(e) { alert('Error stopping twin: ' + e.message); });
}

function tickTwin(id) {
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = '...';
  fetch('/digital-twins/' + id + '/tick', { method: 'POST' })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
      return r.json();
    })
    .then(function(d) {
      var m = d.metrics || {};
      btn.textContent = m.convergence_status === 'converged' ? 'OK' : 'Fail';
      setTimeout(function() { location.reload(); }, 1500);
    })
    .catch(function(e) {
      btn.textContent = 'Tick';
      btn.disabled = false;
      alert('Tick failed: ' + e.message);
    });
}

function deleteTwin(id) {
  if (!confirm('Delete digital twin "' + id + '" and all its data?')) return;
  fetch('/digital-twins/' + id, { method: 'DELETE' })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
      return r.json();
    })
    .then(function() { location.reload(); })
    .catch(function(e) { alert('Error deleting twin: ' + e.message); });
}
