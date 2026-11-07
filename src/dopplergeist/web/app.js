'use strict';
const $ = id => document.getElementById(id);
const terminal = new Set(['needs_input', 'succeeded', 'inconclusive', 'failed', 'cancelled']);
let activeJob = null, renderedJob = null, timer = null, maxBytes = 100 * 1024 * 1024;
let artifactJob = null, artifactPaths = new Set(), mediaJob = null, mediaIndex = null;
let reviews = {schema_version: 1, labels: {}}, evidenceKey = '';
let hideFalsePositives = false, reanalysisPending = false;
try { hideFalsePositives = localStorage.getItem('dopplergeist-hide-false') === '1'; } catch (_) { /* optional */ }
const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
const artifactUrl = (id, path) => `/api/jobs/${id}/artifacts/${path.split('/').map(encodeURIComponent).join('/')}`;
const REVIEW_LABELS = {confirmed: 'Confirmed curve', false_positive: 'False positive', unreviewed: 'Unreviewed'};
const reviewLabel = event => reviews.labels?.[event.event_id]?.label || 'unreviewed';
const reviewNote = event => reviews.labels?.[event.event_id]?.note || '';
function resetEvidence() {
  artifactJob = null; artifactPaths = new Set(); mediaJob = null; mediaIndex = null;
  reviews = {schema_version: 1, labels: {}}; evidenceKey = '';
}
function hasArtifact(id, path) {
  return artifactJob === id && artifactPaths.has(path);
}
// Older services and unavailable capability responses expose only legacy CONUS.
const CONUS_PROFILE = {country: 'US', coverage: 'conus', name: 'Contiguous United States (CONUS)', bounds_wsen: [-125, 24, -66, 50]};
let countryProfiles = [CONUS_PROFILE], areaControl = null, countrySelectionSupported = false;
const BOUND_INPUTS = ['bbox-w', 'bbox-s', 'bbox-e', 'bbox-n'];

function selectedProfile() {
  const profile = countryProfiles.find(item => item.country === $('country').value);
  if (!profile) throw new Error('Choose a country supported by this service.');
  return profile;
}

function setCountryProfiles(values, defaultCountry = 'US') {
  const profiles = values === undefined ? [CONUS_PROFILE] : values;
  const countries = new Set();
  if (!Array.isArray(profiles) || !profiles.length || profiles.some(profile => {
    if (!profile || !/^[A-Z]{2}$/.test(profile.country) || typeof profile.coverage !== 'string' || !profile.coverage
        || typeof profile.name !== 'string' || !profile.name.trim() || countries.has(profile.country)) return true;
    countries.add(profile.country);
    const b = profile.bounds_wsen;
    return !Array.isArray(b) || b.length !== 4 || b.some(value => !Number.isFinite(value))
      || !(-180 <= b[0] && b[0] < b[2] && b[2] <= 180 && -90 <= b[1] && b[1] < b[3] && b[3] <= 90);
  })) throw new Error('The service returned an invalid country catalog.');
  const previous = countryProfiles.find(profile => profile.country === $('country').value);
  countryProfiles = profiles.map(profile => ({...profile, bounds_wsen: profile.bounds_wsen.slice()}));
  countrySelectionSupported = values !== undefined;
  // Newer services label each profile with a continent; group those options.
  const groups = new Map();
  for (const profile of countryProfiles) {
    const option = node('option', profile.name); option.value = profile.country;
    const label = typeof profile.continent === 'string' ? profile.continent : '';
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(option);
  }
  $('country').replaceChildren(...[...groups].flatMap(([label, options]) => {
    if (!label) return options;
    const group = document.createElement('optgroup'); group.label = label; group.append(...options); return [group];
  }));
  $('country').value = countries.has(previous?.country) ? previous.country
    : (countries.has(defaultCountry) ? defaultCountry : countryProfiles[0].country);
  const current = selectedProfile();
  const changed = !previous || previous.country !== current.country
    || previous.bounds_wsen.some((value, index) => value !== current.bounds_wsen[index]);
  if (areaControl) areaControl.refreshCountry(changed);
  $('supported-areas').textContent = countryProfiles.length > 10
    ? `${countryProfiles.length} countries and territories, grouped by continent in the country selector`
    : countryProfiles.map(profile => profile.name).join('; ');
  if (renderedJob) renderCoverage(renderedJob.coverage, renderedJob.status);
}

function renderCoverage(coverage, status) {
  $('coverage').replaceChildren();
  const card = node('div', undefined, 'candidate');
  card.append(node('strong', 'Search & data coverage'));
  if (!coverage) {
    card.append(node('p', 'Search and data coverage are not established.'));
    $('coverage').append(card);
    return;
  }
  const area = coverage.requested_area;
  if (area) {
    const profile = countryProfiles.find(item => (!area.country || item.country === area.country)
      && (!area.coverage || item.coverage === area.coverage));
    const name = profile?.name || ({US: CONUS_PROFILE.name, DE: 'Germany'})[area.country]
      || ({conus: CONUS_PROFILE.name, germany: 'Germany'})[area.coverage] || area.country || area.coverage || 'unspecified';
    const bounds = area.bounds_wsen;
    const full = bounds && profile && bounds.every((value, index) => value === profile.bounds_wsen[index]);
    const label = bounds && !full
      ? `Requested ${name} bounds (west, south, east, north): ${bounds.map(value => typeof value === 'number' ? value.toFixed(6) : value).join(', ')}`
      : `Requested area: ${name}`;
    card.append(node('p', label));
  }
  if (status === 'queued' || status === 'running') {
    card.append(node('p', status === 'queued'
      ? 'Search queued · data coverage will be assessed after processing starts.'
      : 'Search in progress · final data coverage will be reported when processing finishes.'));
  } else {
    card.append(node('p', `Search ${coverage.search_complete ? 'complete' : 'incomplete'} · Data ${coverage.data_status}`));
    for (const limitation of coverage.limitations || []) card.append(node('p', limitation));
    if (coverage.missing_data?.length) card.append(node('p', `Missing: ${coverage.missing_data.join('; ')}`));
  }
  $('coverage').append(card);
}
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
function renderArtifacts(id, items, status) {
  artifactJob = id; artifactPaths = new Set(items.map(item => item.path));
  $('resume').hidden = !['cancelled', 'failed', 'inconclusive'].includes(status)
    || !artifactPaths.has('resume.json');
  $('artifacts').replaceChildren(); $('diagnostics').replaceChildren();
  for (const item of items) {
    const href = artifactUrl(id, item.path);
    const li = node('li'); const a = node('a', item.path); a.href = href; a.download = '';
    li.append(a, node('span', ` · ${(item.bytes / 1024).toFixed(1)} KB`, 'muted')); $('artifacts').append(li);
    if (/\.png$/i.test(item.path) && !/^discovery\/event-[^/]+\.png$/i.test(item.path)
        && /event|spectro|discovery|model|location/i.test(item.path)) {
      const figure = node('figure', undefined, 'diagnostic'); const img = node('img');
      img.src = href; img.alt = `Analysis evidence: ${item.path}`; img.loading = 'lazy';
      figure.append(img, node('figcaption', item.path)); $('diagnostics').append(figure);
    }
  }
}

async function loadMediaIndex(id) {
  if (mediaJob === id) return;
  mediaJob = id; mediaIndex = null;
  if (!hasArtifact(id, 'discovery/event-media.json')) return;
  try {
    const value = await api(artifactUrl(id, 'discovery/event-media.json'));
    if (mediaJob === id && value && typeof value === 'object') mediaIndex = value;
  } catch (_) { /* Older or partial jobs may not have a readable media index. */ }
}

async function refreshEvidence(id, value, force = false) {
  if (id !== activeJob || !value) return;
  const key = `${id}:${value.status}:${value.progress ?? ''}:${value.events?.length || 0}:${(value.review?.excluded_event_ids || []).join(',')}`;
  if (!force && key === evidenceKey) return;
  evidenceKey = key;
  try {
    const [reviewValue, artifactValue] = await Promise.all([
      api(`/api/jobs/${id}/reviews`),
      api(`/api/jobs/${id}/artifacts`),
    ]);
    if (id !== activeJob) return;
    reviews = reviewValue;
    renderArtifacts(id, artifactValue.artifacts, value.status);
    await loadMediaIndex(id);
    if (id !== activeJob) return;
    renderEvents(value);
  } catch (error) {
    evidenceKey = '';
    if (id === activeJob) $('connection').textContent = `Could not read curve evidence: ${error.message}`;
  }
}
function coordinateCopyControl(lat, lon) {
  const control = node('div', undefined, 'coordinate-copy');
  const button = node('button', 'Copy coordinates', 'secondary');
  const status = node('span', '', 'help');
  const coordinates = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
  let resetTimer = null;

  button.type = 'button';
  button.setAttribute('aria-label', `Copy coordinates ${coordinates}`);
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true');

  button.addEventListener('click', async () => {
    clearTimeout(resetTimer);
    status.textContent = '';
    button.disabled = true;
    try {
      if (!navigator.clipboard
          || typeof navigator.clipboard.writeText !== 'function') {
        throw new Error('Clipboard unavailable');
      }
      await navigator.clipboard.writeText(coordinates);
      status.textContent = 'Copied!';
      resetTimer = setTimeout(() => { status.textContent = ''; }, 2500);
    } catch (_) {
      status.textContent = 'Copy failed. Select and copy the coordinates above.';
    } finally {
      button.disabled = false;
    }
  });

  control.append(button, status);
  return control;
}

const STAGES = [
  ['intake', 'Audio intake'], ['discovery', 'Event discovery'], ['acquisition', 'Flight data'],
  ['search', 'Location search'], ['refinement', 'Refinement'], ['decision', 'Decision'],
];

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  if (h) return `${h} h ${m} min`;
  if (m) return `${m} min ${s} s`;
  return `${s} s`;
}

function stageLabel(value) {
  if (terminal.has(value.status)) return value.stage || '';
  if (value.status === 'queued') return 'Waiting in queue';
  const index = STAGES.findIndex(([name]) => name === value.stage);
  const label = index < 0 ? (value.stage || '').replaceAll('_', ' ')
    : `Step ${index + 1}/${STAGES.length}: ${STAGES[index][1]}`;
  const elapsed = Number.isFinite(value.elapsed_seconds) ? ` � ${formatDuration(value.elapsed_seconds)} elapsed` : '';
  return `${label}${elapsed}`;
}

function render(value) {
  renderedJob = value;
  $('empty').hidden = true; $('job').hidden = false;
  $('job-id').textContent = `JOB ${value.job_id}`;
  $('status').textContent = value.status.replaceAll('_', ' ');
  $('stage').textContent = stageLabel(value);
  const progress = $('progress');
  if (value.progress_stale) {
    progress.removeAttribute('value');
    progress.setAttribute('aria-label', 'Progress unavailable because the saved percentage is stale');
  } else {
    progress.value = Number.isFinite(value.progress) ? value.progress : (terminal.has(value.status) ? 1 : 0);
    progress.setAttribute('aria-label', 'Analysis progress');
  }
  $('cancel').hidden = terminal.has(value.status);
  $('resume').hidden = true;
  const staleAge = Number.isFinite(value.progress_age_seconds)
    ? ` Last progress update was ${formatDuration(value.progress_age_seconds)} ago; the worker may have stopped.` : '';
  $('message').textContent = value.progress_stale
    ? `${value.message || 'The saved percentage is stale and hidden.'}${staleAge}`
    : (value.message || 'Analysis is running. You can return to this job using its saved link.');
  $('required').hidden = !value.required_fields?.length;
  $('required').textContent = value.required_fields?.length ? `Required input: ${value.required_fields.join(', ')}. Add the evidence to a new analysis; this run is preserved.` : '';
  $('guidance').replaceChildren(); $('guidance').hidden = true;
  renderCoverage(value.coverage, value.status);
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
      if (Number.isFinite(candidate.lat) && Number.isFinite(candidate.lon)) {
        card.append(coordinateCopyControl(candidate.lat, candidate.lon));
      }
      if (i < 5) $('candidates').append(card);
      else {
        if (!additional) { additional = node('details'); additional.append(node('summary', `${value.candidates.length - 5} additional hypotheses`)); $('candidates').append(additional); }
        additional.append(card);
      }
    });
  }
  const assist = $('review-assist');
  if (value.review?.user_assisted) {
    const excluded = value.review.excluded_event_ids?.length || 0;
    const source = value.review.source_job_id ? ` from job ${value.review.source_job_id.slice(0, 12)}` : '';
    assist.textContent = `User-assisted re-analysis${source}: ${excluded} curve${excluded === 1 ? '' : 's'} marked false positive ${excluded === 1 ? 'was' : 'were'} excluded before search. This is not an automatic result.`;
    assist.hidden = false;
  } else {
    assist.textContent = ''; assist.hidden = true;
  }
  renderEvents(value);
}
const svgNode = (tag, attributes = {}) => {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
};

function formatEventSeconds(value) {
  return Number.isFinite(value) ? value.toFixed(1) : '—';
}

function formatQuality(value) {
  if (!Number.isFinite(value)) return String(value);
  return Math.abs(value) >= 1000 || (Math.abs(value) < 0.001 && value !== 0)
    ? value.toExponential(2) : String(Number(value.toPrecision(4)));
}

function eventGroups(value) {
  const groups = new Map();
  for (const event of value.events || []) {
    const key = event.harmonic_group_id || event.event_id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  }
  return groups;
}

function ridgeChart(event) {
  if (!Array.isArray(event.ridge) || event.ridge.length < 2) return null;
  const width = 340, height = 128, left = 38, right = 8, top = 10, bottom = 22;
  const t0 = Math.min(event.start_s, event.ridge[0].time_s);
  const t1 = Math.max(event.end_s, event.ridge[event.ridge.length - 1].time_s);
  let f0 = event.band_hz[0], f1 = event.band_hz[1];
  const fpad = Math.max(1, (f1 - f0) * 0.05);
  f0 -= fpad; f1 += fpad;
  const dx = Math.max(1e-9, t1 - t0), df = Math.max(1e-9, f1 - f0);
  const x = value => left + ((value - t0) / dx) * (width - left - right);
  const y = value => height - bottom - ((value - f0) / df) * (height - top - bottom);
  const svg = svgNode('svg', {
    viewBox: `0 0 ${width} ${height}`, class: 'ridge-chart', role: 'img',
    'aria-label': `Measured ridge for ${event.event_id}: ${formatEventSeconds(t0)} to ${formatEventSeconds(t1)} seconds, ${Math.round(event.band_hz[0])} to ${Math.round(event.band_hz[1])} hertz`,
  });
  svg.append(svgNode('rect', {x: 0, y: 0, width, height, fill: '#0d1517'}));
  svg.append(svgNode('line', {x1: left, y1: top, x2: left, y2: height - bottom, stroke: '#334247'}));
  svg.append(svgNode('line', {x1: left, y1: height - bottom, x2: width - right, y2: height - bottom, stroke: '#334247'}));
  const segments = []; let current = [];
  for (const point of event.ridge) {
    if (current.length && point.time_s - current[current.length - 1].time_s > 2) {
      segments.push(current); current = [];
    }
    current.push(point);
  }
  if (current.length) segments.push(current);
  for (const segment of segments) {
    if (segment.length < 2) continue;
    svg.append(svgNode('polyline', {
      points: segment.map(point => `${x(point.time_s).toFixed(1)},${y(point.frequency_hz).toFixed(1)}`).join(' '),
      fill: 'none', stroke: '#baf078', 'stroke-width': '1.8',
      'stroke-linejoin': 'round', 'stroke-linecap': 'round',
    }));
  }
  const label = (attributes, text) => {
    const element = svgNode('text', {fill: '#a6b8bd', 'font-size': '9', ...attributes});
    element.textContent = text; svg.append(element);
  };
  label({x: left - 4, y: top + 4, 'text-anchor': 'end'}, String(Math.round(f1)));
  label({x: left - 4, y: height - bottom + 4, 'text-anchor': 'end'}, String(Math.round(f0)));
  label({x: left, y: height - 6}, `${formatEventSeconds(t0)} s`);
  label({x: width - right, y: height - 6, 'text-anchor': 'end'}, `${formatEventSeconds(t1)} s`);
  return svg;
}

async function submitReview(jobId, eventIds, label, note = '') {
  try {
    const saved = await api(`/api/jobs/${jobId}/reviews`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({label, event_ids: eventIds, note}),
    });
    if (jobId !== activeJob) return;
    reviews = saved;
    $('connection').textContent = '';
    renderEvents(renderedJob, true);
  } catch (error) {
    if (jobId !== activeJob) return;
    $('connection').textContent = `Could not save review labels: ${error.message}`;
    renderEvents(renderedJob, true);
  }
}

function reviewControl(event, jobId) {
  const wrapper = node('div', undefined, 'event-review');
  const row = node('div', undefined, 'review-row');
  row.append(node('label', 'Review', 'review-label'));
  const select = node('select', undefined, 'review-select');
  select.setAttribute('aria-label', `Review ${event.event_id}`);
  for (const [value, text] of Object.entries(REVIEW_LABELS)) {
    const option = node('option', text); option.value = value; select.append(option);
  }
  select.value = reviewLabel(event);
  const note = node('input', undefined, 'review-note');
  note.type = 'text'; note.maxLength = 1000;
  note.placeholder = 'Optional review note';
  note.value = reviewNote(event);
  let saveTimer = null;
  const save = (always = false) => {
    if (!always && select.value === 'unreviewed') return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => submitReview(jobId, [event.event_id], select.value, note.value.trim()), 250);
  };
  select.addEventListener('change', () => save(true));
  note.addEventListener('change', () => save(false));
  row.append(select);
  wrapper.append(row, note, node('p', 'Annotations do not change this job\'s scores, candidates or location.', 'help'));
  return wrapper;
}

function groupReviewControl(group, jobId) {
  const labels = new Set(group.map(reviewLabel));
  const select = node('select', undefined, 'review-select');
  select.setAttribute('aria-label', 'Review all curves in this harmonic group');
  select.title = 'Applies to every ridge in this group; per-curve notes are replaced.';
  const prompt = node('option', 'Group review…'); prompt.value = ''; select.append(prompt);
  for (const [value, text] of Object.entries(REVIEW_LABELS)) {
    const option = node('option', text); option.value = value; select.append(option);
  }
  select.value = labels.size === 1 ? [...labels][0] : '';
  select.addEventListener('change', () => {
    if (select.value) submitReview(jobId, group.map(event => event.event_id), select.value, '');
  });
  return select;
}

async function startReanalysis(count, button) {
  if (reanalysisPending) return;
  if (!confirm(`Start a new user-assisted analysis without ${count} curve${count === 1 ? '' : 's'} marked false positive? The current job and its result will not change.`)) return;
  reanalysisPending = true; button.disabled = true;
  try {
    const queued = await api(`/api/jobs/${activeJob}/reanalyze`, {method: 'POST'});
    selectJob(queued.job_id);
  } catch (error) {
    $('connection').textContent = `Could not start re-analysis: ${error.message}`;
    button.disabled = false;
  } finally {
    reanalysisPending = false;
  }
}

function eventCard(value, event) {
  const id = event.event_id;
  const label = reviewLabel(event);
  const card = node('article', undefined, `event-card ${label}`);
  const head = node('div', undefined, 'event-card-head');
  head.append(node('strong', id), node('span', REVIEW_LABELS[label], `badge ${label}`));
  card.append(head);
  card.append(node('p', `${formatEventSeconds(event.start_s)}–${formatEventSeconds(event.end_s)} s · ${Math.round(event.band_hz[0])}–${Math.round(event.band_hz[1])} Hz${event.harmonic_group_id ? ` · ${event.harmonic_group_id}` : ''}`, 'mono'));
  const chart = ridgeChart(event);
  if (chart) card.append(chart);
  const media = mediaJob === value.job_id ? mediaIndex?.events?.[id] || null : null;
  const imagePath = media?.image ? `discovery/${media.image}` : `discovery/${id}.png`;
  if (hasArtifact(value.job_id, imagePath)) {
    const figure = node('figure', undefined, 'event-figure');
    const link = node('a');
    link.href = artifactUrl(value.job_id, imagePath);
    link.target = '_blank'; link.rel = 'noopener noreferrer';
    const image = node('img');
    image.src = link.href;
    image.alt = `Spectrogram crop with the measured ridge for ${id}`;
    image.loading = 'lazy';
    link.append(image);
    figure.append(link, node('figcaption', 'Spectrogram crop with measured ridge. Open full image.', 'help'));
    card.append(figure);
  }
  const audio = media?.audio || null;
  const rawPath = audio?.raw ? `discovery/${audio.raw}` : `discovery/${id}-audio.wav`;
  if (hasArtifact(value.job_id, rawPath)) {
    const box = node('div', undefined, 'event-audio');
    const bounds = audio
      ? `${formatEventSeconds(audio.start_s)}–${formatEventSeconds(audio.end_s)} s${audio.truncated ? ' · centered excerpt' : ''}`
      : 'event excerpt';
    box.append(node('span', `Raw audio · ${bounds}`, 'help'));
    const raw = document.createElement('audio');
    raw.controls = true; raw.preload = 'none';
    raw.src = artifactUrl(value.job_id, rawPath);
    raw.setAttribute('aria-label', `Raw recording excerpt for ${id}`);
    box.append(raw);
    const bandPath = audio?.band_limited ? `discovery/${audio.band_limited}` : null;
    if (bandPath && hasArtifact(value.job_id, bandPath)) {
      box.append(node('span', 'Band-limited excerpt · illustrative, not used for detection or scoring', 'help'));
      const band = document.createElement('audio');
      band.controls = true; band.preload = 'none';
      band.src = artifactUrl(value.job_id, bandPath);
      band.setAttribute('aria-label', `Band-limited recording excerpt for ${id}`);
      box.append(band);
    }
    card.append(box);
  }
  const csvPath = media?.ridge_csv ? `discovery/${media.ridge_csv}` : `discovery/${id}.csv`;
  if (hasArtifact(value.job_id, csvPath)) {
    const line = node('p', undefined, 'event-link');
    const link = node('a', 'Measured ridge CSV');
    link.href = artifactUrl(value.job_id, csvPath); link.download = '';
    line.append(link); card.append(line);
  }
  const quality = Object.entries(event.quality || {});
  if (quality.length) {
    const details = node('details');
    details.append(node('summary', 'Measured ridge & quality'));
    const list = node('ul');
    for (const [key, number] of quality) {
      list.append(node('li', `${key.replaceAll('_', ' ')}: ${formatQuality(number)}`));
    }
    details.append(list); card.append(details);
  }
  if (media?.errors?.length) {
    const details = node('details');
    details.append(node('summary', 'Media generation notes'));
    const list = node('ul');
    for (const error of media.errors) list.append(node('li', error));
    details.append(list); card.append(details);
  }
  card.append(reviewControl(event, value.job_id));
  return card;
}

let eventsSignature = '';

function renderEvents(value, force = false) {
  if (!value) return;
  const signature = `${value.job_id}|${value.events?.length || 0}|${Object.keys(reviews.labels || {}).sort().map(id => `${id}:${reviews.labels[id].label}:${reviews.labels[id].note || ''}`).join(',')}|${artifactJob}|${artifactPaths.size}|${mediaJob}|${mediaIndex ? Object.keys(mediaIndex.events || {}).length : 0}|${hideFalsePositives}`;
  if (!force && signature === eventsSignature) return;
  eventsSignature = signature;
  const container = $('events');
  container.replaceChildren();
  if (!value.events?.length) return;
  const groups = eventGroups(value);
  const all = value.events;
  const falseCount = all.filter(event => reviewLabel(event) === 'false_positive').length;
  const confirmedCount = all.filter(event => reviewLabel(event) === 'confirmed').length;
  const header = node('div', undefined, 'section-row event-section-head');
  const title = node('div');
  title.append(node('h3', `${groups.size} acoustic proposal groups · ${all.length} ridge records`));
  title.append(node('p', `${confirmedCount} confirmed · ${falseCount} false positive · ${all.length - confirmedCount - falseCount} unreviewed. Review labels do not change this job's result.`, 'help'));
  header.append(title);
  const actions = node('div', undefined, 'event-actions');
  const filterLabel = node('label', undefined, 'inline-control');
  const filter = document.createElement('input');
  filter.type = 'checkbox'; filter.checked = hideFalsePositives;
  filter.addEventListener('change', () => {
    hideFalsePositives = filter.checked;
    try { localStorage.setItem('dopplergeist-hide-false', hideFalsePositives ? '1' : '0'); } catch (_) { /* optional */ }
    renderEvents(renderedJob, true);
  });
  filterLabel.append(filter, document.createTextNode(' Hide false positives'));
  actions.append(filterLabel);
  if (falseCount) {
    const button = node('button', `Re-analyze without ${falseCount} false positive${falseCount === 1 ? '' : 's'}`, 'secondary');
    button.type = 'button';
    button.addEventListener('click', () => startReanalysis(falseCount, button));
    actions.append(button);
  }
  header.append(actions); container.append(header);
  if (artifactJob === value.job_id && !hasArtifact(value.job_id, 'discovery/event-media.json')) {
    container.append(node('p', 'This job has no per-curve media index; it was analyzed before images and audio excerpts were generated. The measured ridge chart and data are still available. Re-run the analysis to add media.', 'help'));
  }
  for (const [groupId, group] of groups) {
    const section = node('section', undefined, 'event-group');
    const groupHead = node('div', undefined, 'event-group-head');
    const groupTitle = node('div');
    const start = Math.min(...group.map(event => event.start_s));
    const end = Math.max(...group.map(event => event.end_s));
    const low = Math.min(...group.map(event => event.band_hz[0]));
    const high = Math.max(...group.map(event => event.band_hz[1]));
    groupTitle.append(node('h4', groupId));
    groupTitle.append(node('span', `${group.length} ridge${group.length === 1 ? '' : 's'} · ${formatEventSeconds(start)}–${formatEventSeconds(end)} s · ${Math.round(low)}–${Math.round(high)} Hz`, 'help'));
    groupHead.append(groupTitle);
    if (group.length > 1) groupHead.append(groupReviewControl(group, value.job_id));
    section.append(groupHead);
    const visible = group.filter(event => !hideFalsePositives || reviewLabel(event) !== 'false_positive');
    if (!visible.length) {
      section.append(node('p', 'All curves in this group are marked false positive and hidden.', 'help'));
    } else {
      const grid = node('div', undefined, 'event-grid');
      for (const event of visible) grid.append(eventCard(value, event));
      section.append(grid);
    }
    container.append(section);
  }
}

async function readGuidance(value) {
  const id = value.job_id;
  try {
    const advice = await api(`/api/jobs/${id}/guidance`);
    if (id !== activeJob || renderedJob !== value || advice.status !== value.status || advice.reason_code !== (value.reason_code || null)) return;
    if (!advice.items?.length) return;
    const panel = $('guidance');
    panel.replaceChildren(node('h3', 'Next steps'));
    panel.append(node('p', 'These suggestions are not ranked. Their benefit has not been measured.', 'help'));
    for (const item of advice.items) {
      const card = node('div', undefined, 'candidate');
      card.append(node('p', item.observation), node('p', item.suggestion));
      const detail = node('details'); detail.append(node('summary', 'Evidence behind this suggestion'));
      const list = node('ul');
      for (const reference of item.evidence || []) {
        const li = node('li');
        const [artifact] = reference.split('#');
        // Only link the two local artifacts emitted by the guidance producer.
        if (artifact === 'result.json' || artifact === 'decision.json') {
          const link = node('a', reference);
          link.href = `/api/jobs/${id}/artifacts/${artifact}`; link.download = '';
          li.append(link);
        } else li.textContent = reference;
        list.append(li);
      }
      detail.append(list); card.append(detail); panel.append(card);
    }
    panel.hidden = false;
  } catch (_) {
    if (id !== activeJob || renderedJob !== value) return;
    $('guidance').replaceChildren(node('p', 'Next steps could not be read. The saved result and artifacts remain available.', 'help'));
    $('guidance').hidden = false;
  }
}
async function poll(id) {
  clearTimeout(timer);
  try {
    const value = await api(`/api/jobs/${id}`);
    if (id !== activeJob) return;
    $('connection').textContent = ''; render(value);
    if (terminal.has(value.status)) {
      await Promise.all([refreshEvidence(id, value, true), readGuidance(value)]);
    } else {
      if (value.events?.length) void refreshEvidence(id, value);
      timer = setTimeout(() => poll(id), 1000);
    }
  } catch (error) {
    if (id !== activeJob) return;
    $('connection').textContent = `Could not read this job: ${error.message}. Start the service with the same jobs directory to reconnect.`;
    timer = setTimeout(() => poll(id), 5000);
  }
}
function selectJob(id) {
  activeJob = id;
  resetEvidence();
  eventsSignature = '';
  history.replaceState(null, '', `/?job=${encodeURIComponent(id)}`);
  remember(id); poll(id);
}
const defaultFileLabel = $('file-label').textContent;
$('audio').addEventListener('change', () => {
  $('file-label').textContent = $('audio').files[0]?.name || defaultFileLabel;
});
$('upload-form').addEventListener('submit', async event => {
  event.preventDefault(); $('upload-error').textContent = '';
  const file = $('audio').files[0];
  if (!file || file.size <= 0 || file.size > maxBytes) { $('upload-error').textContent = `Choose a nonempty recording up to ${(maxBytes / 1024 / 1024).toFixed(0)} MB.`; return; }
  const start = $('start').value, end = $('end').value;
  if (end && !start) { $('upload-error').textContent = 'Enter the earliest recording start as well.'; return; }
  if (start && end && end < start) { $('upload-error').textContent = 'The latest start must be at or after the earliest start.'; return; }
  let bounds;
  try { bounds = readSearchBounds(); }
  catch (error) { $('upload-error').textContent = error.message; return; }
  const profile = selectedProfile();
  const request = {schema_version: 1, search: {coverage: profile.coverage, bounds_wsen: bounds}};
  if (countrySelectionSupported) request.search.country = profile.country;
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
  try { const value = await api(`/api/jobs/${activeJob}/cancel`, {method: 'POST'}); render(value); await refreshEvidence(activeJob, value, true); }
  catch (error) { $('connection').textContent = error.message; }
});
$('resume').addEventListener('click', async () => {
  try { const value = await api(`/api/jobs/${activeJob}/resume`, {method: 'POST'}); render(value); poll(activeJob); }
  catch (error) { $('connection').textContent = error.message; }
});
api('/api/capabilities').then(value => {
  setCountryProfiles(value.countries, value.default_country);
  maxBytes = value.max_upload_bytes;
  $('limits').textContent = `Up to ${(maxBytes / 1024 / 1024).toFixed(0)} MB per file. Analysis budget: ${(value.max_runtime_s / 60).toFixed(0)} minutes per job.`;
  if (value.provider_configured === false) {
    $('data-setup').textContent = 'Historical flight data is not configured. Restart the service with --online to download public data, or provide an offline configuration. Downloads and indexes can require tens of gigabytes or more and hours.';
    $('data-setup').hidden = false;
  } else if (value.online_enabled) {
    $('data-setup').textContent = 'Public flight and terrain data may be downloaded to the local cache. Archives and indexes can require tens of gigabytes or more and hours.';
    $('data-setup').hidden = false;
  }
}).catch(error => {
  setCountryProfiles(undefined);
  $('upload-error').textContent = `Could not read service settings: ${error.message}. Only CONUS is available.`;
});
renderRecent();
const savedJob = new URLSearchParams(location.search).get('job');
if (savedJob && /^[0-9a-f]{32}$/.test(savedJob)) selectJob(savedJob);

function validateSearchBounds(bounds) {
  if (bounds.length !== 4 || bounds.some(value => !Number.isFinite(value))) {
    throw new Error('Enter all four search coordinates as finite numbers.');
  }
  const [w, s, e, n] = bounds;
  if (w >= e || s >= n) {
    throw new Error('West must be less than east and south less than north. Antimeridian crossing is unsupported.');
  }
  const profile = selectedProfile();
  const [west, south, east, north] = profile.bounds_wsen;
  if (w < west || s < south || e > east || n > north) {
    throw new Error(`Choose an area within ${profile.name}: west ${west}°, south ${south}°, east ${east}°, north ${north}°.`);
  }
  return bounds;
}

function readSearchBounds() {
  const values = BOUND_INPUTS.map(id => $(id).value.trim());
  if (values.some(value => value === '')) throw new Error('Enter all four search coordinates.');
  return validateSearchBounds(values.map(Number));
}

function boundsMessage(message = '') {
  $('bounds-error').textContent = message;
  $('bounds-error').hidden = !message;
}

function initMap() {
  let map, rectangle, preview, drawOrigin, panStart;
  let selectedBounds = selectedProfile().bounds_wsen.slice();

  function setBounds(bounds, fit = false, updateInputs = true) {
    selectedBounds = validateSearchBounds(bounds.slice());
    if (updateInputs) BOUND_INPUTS.forEach((id, index) => { $(id).value = String(selectedBounds[index]); });
    if (map) {
      const [w, s, e, n] = selectedBounds;
      const corners = [[s, w], [n, e]];
      if (rectangle) rectangle.setBounds(corners);
      else rectangle = L.rectangle(corners, {
        color: '#baf078', weight: 2, fillColor: '#baf078', fillOpacity: 0.18, interactive: false
      }).addTo(map);
      if (fit) map.fitBounds(corners, {padding: [20, 20]});
    }
    boundsMessage();
  }

  function refreshCountry(reset = true) {
    const profile = selectedProfile();
    const [w, s, e, n] = profile.bounds_wsen;
    BOUND_INPUTS.forEach((id, index) => {
      $(id).min = String(index % 2 === 0 ? w : s);
      $(id).max = String(index % 2 === 0 ? e : n);
    });
    $('country-help').textContent = `Choose the full ${profile.name} area or a smaller rectangle.`
      + (profile.country === 'DE' ? ' Only locations within Germany are searched; nearby aircraft across its borders remain eligible.' : '');
    if (profile.country === 'DE') {
      const source = node('a', '© BKG 2026'); source.href = 'https://www.bkg.bund.de';
      const license = node('a', 'dl-de/by-2-0'); license.href = 'https://www.govdata.de/dl-de/by-2-0';
      for (const link of [source, license]) { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      $('country-help').append(' Boundary data: ', source, ', ', license, '.');
    }
    if (map) {
      const dx = Math.max(1, (e - w) * 0.1), dy = Math.max(1, (n - s) * 0.15);
      map.setMaxBounds([[Math.max(-90, s - dy), Math.max(-180, w - dx)],
        [Math.min(90, n + dy), Math.min(180, e + dx)]]);
    }
    if (reset) {
      panStart = null;
      clearDrawing();
      setBounds(profile.bounds_wsen, true);
    }
  }
  areaControl = {refreshCountry};
  $('country').addEventListener('change', () => refreshCountry(true));
  BOUND_INPUTS.forEach(id => {
    $(id).addEventListener('input', () => {
      try { setBounds(readSearchBounds(), false, false); }
      catch (error) { boundsMessage(error.message); }
    });
  });
  $('reset-bounds').addEventListener('click', () => setBounds(selectedProfile().bounds_wsen, true));
  refreshCountry(true);

  if (typeof L === 'undefined') {
    $('map-container').hidden = true;
    $('map-status').textContent = 'The map could not load. Enter search coordinates below.';
    return;
  }
  map = L.map('map', {maxBoundsViscosity: 1});
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, noWrap: true,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).on('tileerror', () => {
    $('map-status').textContent = 'Map tiles are unavailable. Coordinates and the selection rectangle still work.';
  }).addTo(map);
  map.dragging.disable(); // Left-drag draws; right-drag or Shift-drag pans.
  refreshCountry(true);

  const container = map.getContainer();
  container.addEventListener('contextmenu', event => event.preventDefault());
  container.addEventListener('mousedown', event => {
    if (event.button === 2 || (event.button === 0 && event.shiftKey)) {
      panStart = {x: event.clientX, y: event.clientY};
      container.style.cursor = 'grabbing';
      event.preventDefault();
      event.stopPropagation();
    }
  });
  window.addEventListener('mousemove', event => {
    if (!panStart) return;
    map.panBy([panStart.x - event.clientX, panStart.y - event.clientY], {animate: false});
    panStart = {x: event.clientX, y: event.clientY};
  });

  function clearDrawing() {
    if (preview) map.removeLayer(preview);
    preview = null;
    drawOrigin = null;
  }
  window.addEventListener('mouseup', () => {
    panStart = null;
    container.style.cursor = '';
    // Releasing outside the map cancels an unfinished selection.
    clearDrawing();
  });
  window.addEventListener('blur', () => {
    panStart = null;
    container.style.cursor = '';
    clearDrawing();
  });

  map.on('mousedown', event => {
    if (event.originalEvent.button !== 0 || event.originalEvent.shiftKey) return;
    drawOrigin = event.latlng;
    preview = L.rectangle([drawOrigin, drawOrigin], {
      color: '#baf078', weight: 2, dashArray: '4, 4', fillOpacity: 0.25, interactive: false
    }).addTo(map);
  });
  map.on('mousemove', event => {
    if (preview && drawOrigin) preview.setBounds([drawOrigin, event.latlng]);
  });
  map.on('mouseup', event => {
    if (!drawOrigin || !preview) return;
    const origin = drawOrigin;
    clearDrawing();
    if (origin.equals(event.latlng)) return;
    const bounds = [Math.min(origin.lng, event.latlng.lng), Math.min(origin.lat, event.latlng.lat),
      Math.max(origin.lng, event.latlng.lng), Math.max(origin.lat, event.latlng.lat)]
      .map(value => Number(value.toFixed(6)));
    try { setBounds(bounds); }
    catch (error) { boundsMessage('Search area was not changed. ' + error.message); }
  });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initMap);
else initMap();
