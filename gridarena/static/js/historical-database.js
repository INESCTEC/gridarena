(function () {
  var deleteForm = document.getElementById('deleteForm');
  if (!deleteForm) return;

  var databaseId = deleteForm.getAttribute('data-database-id');
  var deleteBtn = document.getElementById('deleteBtn');
  var deleteMsg = document.getElementById('deleteMsg');
  var seriesIdInput = document.getElementById('seriesId');
  var phaseInput = document.getElementById('phase');
  var startInput = document.getElementById('start');
  var endInput = document.getElementById('end');

  deleteForm.addEventListener('submit', async function (e) {
    e.preventDefault();

    var seriesId = seriesIdInput.value;
    var phase = phaseInput.value.trim().toUpperCase();
    var start = startInput.value;
    var end = endInput.value;

    if (!seriesId) {
      deleteMsg.textContent = 'Error: series_id is required.';
      return;
    }

    var params = new URLSearchParams();
    if (phase) params.append('phase', phase);
    if (start) params.append('start', start);
    if (end) params.append('end', end);

    deleteBtn.disabled = true;
    deleteMsg.textContent = 'Deleting...';

    try {
      var url = '/historical/' + encodeURIComponent(databaseId) + '/' + encodeURIComponent(seriesId)
        + (params.toString() ? '?' + params.toString() : '');
      var res = await fetch(url, { method: 'DELETE' });
      var j = await res.json();
      if (!res.ok) throw new Error(j.detail || JSON.stringify(j));
      deleteMsg.textContent = j.message || 'Deleted successfully.';
    } catch (err) {
      deleteMsg.textContent = 'Error: ' + err.message;
    } finally {
      deleteBtn.disabled = false;
    }
  });
})();
