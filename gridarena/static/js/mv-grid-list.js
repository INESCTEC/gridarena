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
  var graphHint = document.getElementById('graphHint');
  var selectedFile = null;

  drop.addEventListener('click', function () { input.click(); });
  ['dragenter', 'dragover'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('is-over'); });
  });
  ['dragleave', 'dragend'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('is-over'); });
  });
  drop.addEventListener('drop', function (e) {
    e.preventDefault(); drop.classList.remove('is-over');
    if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; fileChanged(); }
  });
  input.addEventListener('change', fileChanged);

  function fileChanged() {
    selectedFile = input.files[0];
    label.textContent = selectedFile ? selectedFile.name : 'No file selected';
    validateBtn.disabled = !selectedFile;
    uploadBtn.style.display = 'none';
    previewSection.style.display = 'none';
    msg.textContent = '';
  }

  validateBtn.addEventListener('click', async function () {
    if (!selectedFile) return;
    msg.textContent = 'Validating...';
    var data = new FormData();
    data.append('file', selectedFile);

    try {
      var res = await fetch('/mv_grid/validate', { method: 'POST', body: data });
      var result = await res.json();
      if (!res.ok) throw new Error(result.detail ? JSON.stringify(result.detail) : 'Validation failed');

      previewSection.style.display = 'block';
      if (result.valid) {
        previewErrors.innerHTML = '';
        msg.textContent = 'Validation passed.';
        uploadBtn.style.display = 'inline-block';
        uploadBtn.disabled = false;
        var g = result.mv_grid;
        previewTable.innerHTML =
          '<tr><th>MV Grid ID</th><td>' + g.mv_grid_id + '</td></tr>'
          + '<tr><th>Name</th><td>' + (g.name || '') + '</td></tr>'
          + '<tr><th>Voltage</th><td>' + g.nominal_voltage_kv + ' kV</td></tr>'
          + '<tr><th>Nodes</th><td>' + g.nodes.length + '</td></tr>'
          + '<tr><th>Connections</th><td>' + (g.connections ? g.connections.length : 0) + '</td></tr>'
          + '<tr><th>Connection Points</th><td>' + (g.connection_points ? g.connection_points.length : 0) + '</td></tr>'
          + '<tr><th>Transformers</th><td>' + (g.transformers ? g.transformers.length : 0) + '</td></tr>';

        if (result.graph) {
          graphHint.style.display = 'block';
          ensurePlotly(function () {
            renderMVGraph('previewGraph', result.graph, null);
          });
        }
      } else {
        uploadBtn.style.display = 'none';
        graphHint.style.display = 'none';
        previewGraph.innerHTML = '';
        msg.textContent = 'Validation failed.';
        previewErrors.innerHTML = '<ul>' + result.errors.map(function (e) { return '<li>' + e + '</li>'; }).join('') + '</ul>';
        previewTable.innerHTML = '';
      }
    } catch (err) {
      msg.textContent = 'Error: ' + err.message;
    }
  });

  uploadBtn.addEventListener('click', async function () {
    if (!selectedFile) return;
    msg.textContent = 'Saving...';
    uploadBtn.disabled = true;
    var data = new FormData();
    data.append('file', selectedFile);

    try {
      var res = await fetch('/mv_grid/', { method: 'POST', body: data });
      var result = await res.json();
      if (!res.ok) throw new Error(result.detail ? JSON.stringify(result.detail) : 'Save failed');
      msg.textContent = result.message;
      setTimeout(function () { location.reload(); }, 1500);
    } catch (err) {
      msg.textContent = 'Error: ' + err.message;
    } finally {
      uploadBtn.disabled = false;
    }
  });

  window.deleteMVGrid = async function (id) {
    if (!confirm('Delete MV grid "' + id + '" and all associated data?')) return;
    try {
      var res = await fetch('/mv_grid/' + encodeURIComponent(id), { method: 'DELETE' });
      var result = await res.json();
      if (!res.ok) throw new Error(result.detail || 'Delete failed');
      alert(result.message);
      location.reload();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };
})();
