'use strict';
const $ = id => document.getElementById(id);
const terminal = new Set(['needs_input', 'succeeded', 'inconclusive', 'failed', 'cancelled']);
let activeJob = null, timer = null, maxBytes = 100 * 1024 * 1024;
const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
async function api(path, options) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}
function remember(id) {
  try {
    const recent = JSON.parse(localStorage.getItem('dopplergeist-jobs') || '[]');
    localStorage.setItem('dopplergeist-jobs', JSON.stringify([id, ...recent.filter(x => x !== id)].slice(0, 8)));
    renderRecent();
  } catch (_) { /* Private browser storage may be disabled. */ }
}
function renderRecent() {
  try {
    const ids = JSON.parse(localStorage.getItem('dopplergeist-jobs') || '[]');
    $('recent').replaceChildren();
    for (const id of ids) {
      if (!/^[0-9a-f]{32}$/.test(id)) continue;
      const li = node('li'); const a = node('a', id.slice(0, 12)); a.href = `/?job=${id}`;
      li.append(a); $('recent').append(li);
    }
    $('recent-panel').hidden = !$('recent').children.length;
  } catch (_) { /* Optional recent-job links. */ }
}
async function artifacts(id) {
  const response = await api(`/api/jobs/${id}/artifacts`);
  if (id !== activeJob) return;
  $('resume').hidden = !['cancelled', 'failed', 'inconclusive'].includes($('status').textContent) || !response.artifacts.some(item => item.path === 'resume.json');
  $('artifacts').replaceChildren(); $('diagnostics').replaceChildren();
  for (const item of response.artifacts) {
    const href = `/api/jobs/${id}/artifacts/${item.path.split('/').map(encodeURIComponent).join('/')}`;
    const li = node('li'); const a = node('a', item.path); a.href = href; a.download = '';
    li.append(a, node('span', ` · ${(item.bytes / 1024).toFixed(1)} KB`, 'muted')); $('artifacts').append(li);
    if (/\.png$/i.test(item.path) && /event|spectro|discovery|model|location/i.test(item.path)) {
      const figure = node('figure', undefined, 'diagnostic'); const img = node('img');
      img.src = href; img.alt = `Analysis evidence: ${item.path}`; img.loading = 'lazy';
      figure.append(img, node('figcaption', item.path)); $('diagnostics').append(figure);
    }
  }
}
function render(value) {
  $('empty').hidden = true; $('job').hidden = false;
  $('job-id').textContent = `JOB ${value.job_id}`;
  $('status').textContent = value.status.replaceAll('_', ' ');
  $('stage').textContent = value.stage || '';
  $('progress').value = value.progress || (terminal.has(value.status) ? 1 : 0);
  $('cancel').hidden = terminal.has(value.status);
  $('resume').hidden = true;
  $('message').textContent = value.message || 'Analysis is running. You can return to this job using its saved link.';
  $('required').hidden = !value.required_fields?.length;
  $('required').textContent = value.required_fields?.length ? `Required input: ${value.required_fields.join(', ')}. Add the evidence to a new analysis; this run is preserved.` : '';
  $('coverage').replaceChildren();
  if (value.coverage) {
    const coverage = value.coverage;
    const card = node('div', undefined, 'candidate');
    card.append(node('strong', 'Search & data coverage'));
    const bounds = coverage.requested_area?.bounds_wsen;
    const isFullConus = bounds && bounds[0] === -125 && bounds[1] === 24 && bounds[2] === -66 && bounds[3] === 50;
    const boundsLabel = bounds
      ? (isFullConus ? 'Requested area: Contiguous United States (CONUS)' : `Requested search bounds (west, south, east, north): ${bounds.map(x => typeof x === 'number' ? x.toFixed(2) : x).join(', ')}`)
      : 'Requested area: Contiguous United States (CONUS)';
    card.append(node('p', boundsLabel));
    card.append(node('p', `Search ${coverage.search_complete ? 'complete' : 'incomplete'} · Data ${coverage.data_status}`));
    for (const limitation of coverage.limitations || []) card.append(node('p', limitation));
    if (coverage.missing_data?.length) card.append(node('p', `Missing: ${coverage.missing_data.join('; ')}`));
    $('coverage').append(card);
  }
  $('candidates').replaceChildren();
  if (value.candidates?.length) {
    $('candidates').append(node('h3', value.status === 'succeeded' ? 'Supported location & alternatives' : 'Location hypotheses · result remains inconclusive'));
    let additional = null;
    value.candidates.forEach((candidate, i) => {
      const card = node('div', undefined, 'candidate');
      card.append(node('strong', `${i + 1}. ${candidate.lat.toFixed(6)}, ${candidate.lon.toFixed(6)}`));
      if (candidate.uncertainty) {
        const u = candidate.uncertainty;
        card.append(node('p', `${u.kind === 'calibrated' ? 'Calibrated uncertainty' : 'Sensitivity radius'}: ${u.radius_m.toFixed(0)} m · ${u.method.replaceAll('_', ' ')}`));
        if (u.coverage_probability !== undefined) card.append(node('p', `Calibrated coverage: ${(100 * u.coverage_probability).toFixed(0)}% · ${u.calibration_reference}`));
      } else card.append(node('p', 'Location uncertainty was not established.'));
      card.append(node('p', `Score ${candidate.score.toPrecision(5)} (${candidate.score_kind.replaceAll('_', ' ')}); not a probability.`));
      card.append(node('p', `Flights: ${candidate.flight_ids.join(', ')} · Recording start: ${candidate.recording_start_utc}`));
      const map = node('a', 'View coordinate on OpenStreetMap');
      map.href = `https://www.openstreetmap.org/?mlat=${candidate.lat}&mlon=${candidate.lon}#map=14/${candidate.lat}/${candidate.lon}`;
      map.target = '_blank'; map.rel = 'noopener noreferrer'; card.append(map);
      if (i < 5) $('candidates').append(card);
      else {
        if (!additional) { additional = node('details'); additional.append(node('summary', `${value.candidates.length - 5} additional hypotheses`)); $('candidates').append(additional); }
        additional.append(card);
      }
    });
  }
  $('events').replaceChildren();
  if (value.events?.length) {
    const groups = new Set(value.events.map(event => event.harmonic_group_id || event.event_id)).size;
    $('events').append(node('h3', `${groups} independent acoustic proposals · ${value.events.length} ridge records`));
    for (const event of value.events) $('events').append(node('div', `${event.event_id} · ${event.start_s.toFixed(1)}–${event.end_s.toFixed(1)} s · ${event.band_hz.map(x => x.toFixed(0)).join('–')} Hz${event.harmonic_group_id ? ` · group ${event.harmonic_group_id}` : ''}`, 'event'));
  }
}
async function poll(id) {
  clearTimeout(timer);
  try {
    const value = await api(`/api/jobs/${id}`);
    if (id !== activeJob) return;
    $('connection').textContent = ''; render(value);
    if (terminal.has(value.status)) await artifacts(id);
    else timer = setTimeout(() => poll(id), 1000);
  } catch (error) {
    if (id !== activeJob) return;
    $('connection').textContent = `Could not read this job: ${error.message}. Start the service with the same jobs directory to reconnect.`;
    timer = setTimeout(() => poll(id), 5000);
  }
}
function selectJob(id) {
  activeJob = id;
  history.replaceState(null, '', `/?job=${encodeURIComponent(id)}`);
  remember(id); poll(id);
}
$('audio').addEventListener('change', () => { $('file-label').textContent = $('audio').files[0]?.name || 'Your original file is preserved with the job.'; });
$('upload-form').addEventListener('submit', async event => {
  event.preventDefault(); $('upload-error').textContent = '';
  const file = $('audio').files[0];
  if (!file || file.size <= 0 || file.size > maxBytes) { $('upload-error').textContent = `Choose a nonempty recording up to ${(maxBytes / 1024 / 1024).toFixed(0)} MB.`; return; }
  const start = $('start').value, end = $('end').value;
  if (end && !start) { $('upload-error').textContent = 'Enter the earliest recording start as well.'; return; }
  if (start && end && end < start) { $('upload-error').textContent = 'The latest start must be at or after the earliest start.'; return; }
  const w = parseFloat($('bbox-w')?.value || '-125.0');
  const s = parseFloat($('bbox-s')?.value || '24.0');
  const e = parseFloat($('bbox-e')?.value || '-66.0');
  const n = parseFloat($('bbox-n')?.value || '50.0');
  const isConus = (Math.abs(w - (-125.0)) < 0.01 && Math.abs(s - 24.0) < 0.01 && Math.abs(e - (-66.0)) < 0.01 && Math.abs(n - 50.0) < 0.01);
  const request = {
    schema_version: 1,
    search: {
      coverage: isConus ? 'conus' : 'custom',
      bounds_wsen: [w, s, e, n]
    }
  };
  if (start) {
    request.time_window = {start_utc: start + 'Z', end_utc: (end || start) + 'Z', source: 'user'};
    if ($('time-source').value.trim()) request.time_window.source_detail = $('time-source').value.trim();
  }
  // JSON escapes preserve Unicode notes in the ASCII-only HTTP metadata header.
  const requestMetadata = JSON.stringify(request).replace(/[^\x20-\x7e]/g, character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'));
  $('submit').disabled = true;
  try {
    const value = await api('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-Dopplergeist-Request': requestMetadata, 'X-Filename': 'input.' + (file.name.split('.').pop() || 'mp3').replace(/[^a-z0-9]/gi, '')}, body: file});
    render(value); selectJob(value.job_id);
  } catch (error) { $('upload-error').textContent = error.message; }
  finally { $('submit').disabled = false; }
});
$('cancel').addEventListener('click', async () => {
  try { const value = await api(`/api/jobs/${activeJob}/cancel`, {method: 'POST'}); render(value); await artifacts(activeJob); }
  catch (error) { $('connection').textContent = error.message; }
});
$('resume').addEventListener('click', async () => {
  try { const value = await api(`/api/jobs/${activeJob}/resume`, {method: 'POST'}); render(value); poll(activeJob); }
  catch (error) { $('connection').textContent = error.message; }
});
api('/api/capabilities').then(value => {
  maxBytes = value.max_upload_bytes;
  $('limits').textContent = `Up to ${(maxBytes / 1024 / 1024).toFixed(0)} MB per file. Analysis budget: ${(value.max_runtime_s / 60).toFixed(0)} minutes per job.`;
  if (value.provider_configured === false) {
    $('data-setup').textContent = 'Historical flight data is not configured. Restart the service with --online to download public data, or provide an offline configuration. Downloads and indexes can require tens of gigabytes or more and hours.';
    $('data-setup').hidden = false;
  } else if (value.online_enabled) {
    $('data-setup').textContent = 'Public flight and terrain data may be downloaded to the local cache. Archives and indexes can require tens of gigabytes or more and hours.';
    $('data-setup').hidden = false;
  }
}).catch(error => { $('upload-error').textContent = error.message; });
renderRecent();
const savedJob = new URLSearchParams(location.search).get('job');
if (savedJob && /^[0-9a-f]{32}$/.test(savedJob)) selectJob(savedJob);

// Interactive World Map & Boundary Box Selector (Defaults to CONUS, Drag to draw)
const CONUS_BOUNDS = [-125.0, 24.0, -66.0, 50.0];

function wrapLng(lng) {
  return (((lng + 180) % 360 + 360) % 360) - 180;
}
function clampLat(lat) {
  return Math.max(-85.0, Math.min(85.0, lat));
}
function normalizeBounds(w, s, e, n) {
  let nw = wrapLng(w);
  let ne = wrapLng(e);
  if (nw > ne) [nw, ne] = [ne, nw];
  let ns = clampLat(Math.min(s, n));
  let nn = clampLat(Math.max(s, n));
  if (ne - nw < 0.05) ne = Math.min(180, nw + 0.1);
  if (nn - ns < 0.05) nn = Math.min(85, ns + 0.1);
  return [nw, ns, ne, nn];
}

let map, rectLayer;
let currentW = CONUS_BOUNDS[0], currentS = CONUS_BOUNDS[1], currentE = CONUS_BOUNDS[2], currentN = CONUS_BOUNDS[3];
let isDrawing = false, drawOrigin = null, tempRect = null;
let isPanning = false, panStart = null;

function initMap() {
  if (typeof L === 'undefined') {
    setTimeout(initMap, 50);
    return;
  }
  const mapElem = $('map');
  if (!mapElem) return;

  map = L.map('map', {
    center: [38.5, -96.0],
    zoom: 4,
    worldCopyJump: true,
    attributionControl: false
  });

  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18
  }).addTo(map);

  map.dragging.disable(); // Left-drag draws bounding box

  // Right-click drag (or Shift + Left-click drag) to pan the map
  const container = map.getContainer();
  container.addEventListener('contextmenu', e => e.preventDefault());

  container.addEventListener('mousedown', e => {
    if (e.button === 2 || (e.button === 0 && e.shiftKey)) {
      isPanning = true;
      panStart = { x: e.clientX, y: e.clientY };
      container.style.cursor = 'grab';
      e.preventDefault();
      e.stopPropagation();
    }
  });

  window.addEventListener('mousemove', e => {
    if (!isPanning || !panStart) return;
    const dx = e.clientX - panStart.x;
    const dy = e.clientY - panStart.y;
    panStart = { x: e.clientX, y: e.clientY };
    map.panBy([-dx, -dy], { animate: false });
  });

  window.addEventListener('mouseup', e => {
    if (isPanning) {
      isPanning = false;
      panStart = null;
      container.style.cursor = '';
    }
  });

  function updateInputs() {
    $('bbox-w').value = currentW.toFixed(2);
    $('bbox-s').value = currentS.toFixed(2);
    $('bbox-e').value = currentE.toFixed(2);
    $('bbox-n').value = currentN.toFixed(2);
  }

  function setBounds(w, s, e, n, fit) {
    [currentW, currentS, currentE, currentN] = normalizeBounds(w, s, e, n);
    updateInputs();
    const bounds = [[currentS, currentW], [currentN, currentE]];
    if (!rectLayer) {
      rectLayer = L.rectangle(bounds, {
        color: '#baf078',
        weight: 2,
        fillColor: '#baf078',
        fillOpacity: 0.18,
        interactive: false
      }).addTo(map);
    } else {
      rectLayer.setBounds(bounds);
    }
    if (fit) {
      map.fitBounds(bounds, { padding: [20, 20] });
    }
  }

  setBounds(...CONUS_BOUNDS, true);
  setTimeout(() => map.invalidateSize(), 150);

  // Coordinate input changes with auto-modulo normalization
  ['bbox-w', 'bbox-s', 'bbox-e', 'bbox-n'].forEach(id => {
    $(id).addEventListener('change', () => {
      const w = parseFloat($('bbox-w').value);
      const s = parseFloat($('bbox-s').value);
      const e = parseFloat($('bbox-e').value);
      const n = parseFloat($('bbox-n').value);
      if (!isNaN(w) && !isNaN(s) && !isNaN(e) && !isNaN(n)) {
        setBounds(w, s, e, n, false);
      }
    });
  });

  // Left-click drag anywhere on the map draws a new bounding box
  map.on('mousedown', e => {
    if (e.originalEvent.button !== 0 || e.originalEvent.shiftKey) return;
    isDrawing = true;
    drawOrigin = e.latlng.wrap();
    if (tempRect) map.removeLayer(tempRect);
    tempRect = L.rectangle([drawOrigin, drawOrigin], {
      color: '#baf078',
      weight: 2,
      dashArray: '4, 4',
      fillColor: '#baf078',
      fillOpacity: 0.25,
      interactive: false
    }).addTo(map);
  });

  map.on('mousemove', e => {
    if (!isDrawing || !drawOrigin || !tempRect) return;
    const current = e.latlng.wrap();
    tempRect.setBounds([drawOrigin, current]);
  });

  map.on('mouseup', e => {
    if (!isDrawing || !drawOrigin || !tempRect) return;
    const current = e.latlng.wrap();
    map.removeLayer(tempRect);
    tempRect = null;
    isDrawing = false;

    let s = clampLat(Math.min(drawOrigin.lat, current.lat));
    let n = clampLat(Math.max(drawOrigin.lat, current.lat));
    let w = wrapLng(Math.min(drawOrigin.lng, current.lng));
    let e_coord = wrapLng(Math.max(drawOrigin.lng, current.lng));
    if (w > e_coord) [w, e_coord] = [e_coord, w];
    drawOrigin = null;

    // Only update if dragged area is meaningful (> 0.05 deg)
    if (e_coord - w > 0.05 && n - s > 0.05) {
      setBounds(w, s, e_coord, n, false);
    }
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initMap);
} else {
  initMap();
}
