(function () {
  var drop = document.getElementById('drop');
  var input = document.getElementById('fileInput');
  var label = document.getElementById('fileLabel');
  var btn = document.getElementById('uploadBtn');
  var msg = document.getElementById('uploadMsg');
  var form = document.getElementById('uploadForm');

  var deleteForm = document.getElementById('deleteForm');
  var deleteBtn = document.getElementById('deleteBtn');
  var deleteMsg = document.getElementById('deleteMsg');
  var gridIdInput = document.getElementById('gridId');
  var nodeIdInput = document.getElementById('nodeId');
  var phaseInput = document.getElementById('phase');
  var startInput = document.getElementById('start');
  var endInput = document.getElementById('end');

  function setFileLabel(f) { label.textContent = f ? f.name : 'No file selected'; }
  function updateBtn() { btn.disabled = !input.files.length; }

  drop.addEventListener('click', function () { input.click(); });
  ['dragenter', 'dragover'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault();
      drop.classList.add('is-over');
    });
  });
  ['dragleave', 'dragend', 'drop'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault();
      drop.classList.remove('is-over');
    });
  });
  drop.addEventListener('drop', function (e) {
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      setFileLabel(input.files[0]);
      updateBtn();
    }
  });
  input.addEventListener('change', function () {
    setFileLabel(input.files[0]);
    updateBtn();
  });

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (!input.files.length) return;
    var data = new FormData();
    data.append('file', input.files[0]);
    btn.disabled = true;
    msg.textContent = 'Uploading...';
    try {
      var res = await fetch('/measurements/', { method: 'POST', body: data });
      var j = await res.json();
      if (!res.ok) throw new Error(j.detail || JSON.stringify(j));
      msg.textContent = j.message || 'Uploaded successfully.';
      location.reload();
    } catch (err) {
      msg.textContent = 'Error: ' + err.message;
    } finally {
      btn.disabled = false;
    }
  });

  deleteForm.addEventListener('submit', async function (e) {
    e.preventDefault();

    var gridId = gridIdInput.value.trim();
    var nodeId = nodeIdInput.value.trim();
    var phase = phaseInput.value.trim().toUpperCase();
    var start = startInput.value;
    var end = endInput.value;

    if (!gridId) {
      deleteMsg.textContent = 'Error: grid_id is required.';
      return;
    }

    var params = new URLSearchParams();
    if (nodeId) params.append('node_id', nodeId);
    if (phase) params.append('phase', phase);
    if (start) params.append('start', start);
    if (end) params.append('end', end);

    deleteBtn.disabled = true;
    deleteMsg.textContent = 'Deleting...';

    try {
      var url = '/measurements/' + encodeURIComponent(gridId) + (params.toString() ? '?' + params.toString() : '');
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
