/* Engine of the agriculture dashboards that show ELSTAT surveys by region (farm structure, livestock).
 *
 * A page embeds two JSON blocks written by scripts/build_agriculture_data.py ("agri-data": statistics, "agri-geo": map
 * geometries) and calls AgriDashboard(config) with the texts and headline figures of that page. The page must contain the
 * elements whose ids are read below (filters, map, charts, table); the plant production page has its own, older script.
 * Values are shown in the unit of the source, at the geographic level the source publishes, and a dash of the source is
 * never turned into a zero.
 */
(function () {
'use strict';

window.AgriDashboard = function (cfg) {
const D = JSON.parse(document.getElementById('agri-data').textContent);
const G = JSON.parse(document.getElementById('agri-geo').textContent);
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const nf0 = new Intl.NumberFormat('el-GR', {maximumFractionDigits: 0});
const nf1 = new Intl.NumberFormat('el-GR', {maximumFractionDigits: 1});
const nf2 = new Intl.NumberFormat('el-GR', {maximumFractionDigits: 2});
const pf = new Intl.NumberFormat('el-GR', {maximumFractionDigits: 1, minimumFractionDigits: 0});
const pf2 = new Intl.NumberFormat('el-GR', {maximumFractionDigits: 2});
const collator = new Intl.Collator('el');

// ---- catalogue ------------------------------------------------------------------------------------------------
const geo = D.geo.map(([code, level, name, parent], i) => ({i, code, level, name, parent}));
const geoBy = Object.fromEntries(geo.map(g => [g.code, g]));
const COUNTRY = geoBy.EL;
const regions = geo.filter(g => g.level === 'region').sort((a, b) => collator.compare(a.name, b.name));
const zones = geo.filter(g => g.level === 'zone').sort((a, b) => collator.compare(a.name, b.name));
const SUB_LEVELS = ['unit', 'prefecture'].filter(l => geo.some(g => g.level === l));
const MAP_LEVELS = ['region', ...(zones.length ? ['zone'] : []), ...SUB_LEVELS];
const isTop = g => g.level === 'region' || g.level === 'zone';
const subs = geo.filter(g => SUB_LEVELS.includes(g.level));
const subsOf = (region, level) => subs.filter(u => u.parent === region && (!level || u.level === level)).sort((a, b) => collator.compare(a.name, b.name));
const gname = g => g.level === 'zone' ? 'Ζώνη ' + g.name : g.level === 'unit' ? 'Π.Ε. ' + g.name : g.level === 'prefecture' ? (/^Νομαρχία/.test(g.name) ? g.name : 'Νομός ' + g.name) : g.name;
const LEVEL = {country: 'Χώρα', region: 'Περιφέρεια', zone: 'Γεωγραφική ζώνη', unit: 'Περιφερειακή ενότητα', prefecture: 'Νομός'};
const MAP_LEVEL = {region: 'Περιφέρειες', zone: 'Γεωγραφικές ζώνες', unit: 'Περιφερειακές ενότητες', prefecture: 'Νομοί'};
const BTN_LEVEL = {region: 'Περιφέρειες', zone: 'Ζώνες', unit: 'Ενότητες', prefecture: 'Νομοί'};
const GEO_KEY = {region: 'regions', zone: 'zones', unit: 'units', prefecture: 'prefectures'};
const cats = D.cats.map(([key, name], i) => ({i, key, name}));
const prods = D.prods.map(([code, cat, name, sub, kind, cont, breaks, en], i) => ({i, code, cat, name, sub, kind, cont, breaks, en}));
const prodBy = Object.fromEntries(prods.map(p => [p.code, p]));
const sers = D.series.map(([p, v, q], s) => ({s, p, v, q, vr: D.vars[v], variable: D.vars[v][0]}));
const serByProd = prods.map(() => []);
sers.forEach(x => serByProd[x.p].push(x));
const years = D.years;
const yIdx = Object.fromEntries(years.map((y, i) => [y, i]));
const STAGE = {final: 'οριστικά', provisional: 'προσωρινά', unspecified: 'στάδιο μη δηλωμένο'};
const FLAG = {
  total_differs_from_parts: 'Το δημοσιευμένο σύνολο διαφέρει από το άθροισμα των μερών του',
  non_integer_count: 'Δεκαδική τιμή σε αριθμό',
  source_corrected: 'Πίνακας με διορθωμένο έτος ή επικεφαλίδα (βλ. μεθοδολογία)',
  combined: 'Η πηγή δίνει ενιαίο σύνολο για την περιοχή και γειτονική περιφέρεια',
  confidential: 'Η τιμή δεν δημοσιεύεται από την πηγή (εμπιστευτική, «x»)',
  blank: 'Κενό κελί στην πηγή', text: 'Μη αριθμητική τιμή στην πηγή'
};
const flagText = f => FLAG[f] || (f.startsWith('includes_') ? FLAG.combined : f);
const flagMap = new Map();
D.flags.forEach(([s, y, g, f]) => { const k = s + '|' + y + '|' + g; (flagMap.get(k) || flagMap.set(k, []).get(k)).push(f); });
const flagsOf = (s, yi, gi) => [...new Set(flagMap.get(s + '|' + yi + '|' + gi) || [])];

const cell = (s, yi, gi) => { const row = D.vals[s][yi]; return row ? row[gi] : null; };   // number >= 0, -1 for a dash, null without value
const hasValue = v => v !== null && v !== undefined && v >= 0;
const yearsOf = s => years.map((_, i) => i).filter(i => D.vals[s][i] && D.vals[s][i].some(hasValue));
const tableKey = s => D.prods[sers[s].p][0].split('.')[0];
const datasetOf = s => (D.meta.source_of || {})[tableKey(s)] || D.meta.datasets[0];
const srcLabel = s => (cfg.sources[datasetOf(s)] || {}).label || datasetOf(s);
const fmtDate = d => d ? d.split('-').reverse().map(Number).join('/') : '';
const provText = pr => pr ? `${STAGE[pr[2]]} · δημοσίευση ${pr[3] ? fmtDate(pr[3]) : '(ημερομηνία μη διαθέσιμη)'}` : '';
const provenance = (s, yi) => (D.tab[tableKey(s)] || {})[years[yi]];
const pageUrl = (s, edition) => `https://www.statistics.gr/el/statistics/-/publication/${datasetOf(s)}/${edition}`;

// ---- state ----------------------------------------------------------------------------------------------------
const state = {prod: 0, ser: 0, year: null, region: '', unit: '', cmp: '', level: 'region', mode: 'value', pick: 'main', search: '',
               scope: 'product', tyears: 'year', tlevel: 'all', sort: {k: 'value', dir: -1}, page: 0};
const focusGeo = () => state.unit ? geoBy[state.unit] : state.region ? geoBy[state.region] : COUNTRY;
const curSer = () => sers[state.ser];
const curProd = () => prods[state.prod];
const defaultProduct = () => (prods.find(p => p.code === cfg.defaultProduct) || prods[0]).i;
const preferred = variable => { const i = (cfg.preferredVariables || []).indexOf(variable); return i < 0 ? 99 : i; };
const byTotal = (a, b) => (a.kind === 1 && b.kind !== 1) ? -1 : (b.kind === 1 && a.kind !== 1) ? 1 : collator.compare(a.name, b.name);

function setProduct(p, keepVar) {
  state.prod = p;
  const options = serByProd[p];
  const cur = sers[state.ser];
  const same = cur && (options.find(x => x.variable === cur.variable && x.q === cur.q) || options.find(x => x.variable === cur.variable));
  state.ser = (keepVar && same ? same : options.slice().sort((a, b) => preferred(a.variable) - preferred(b.variable))[0]).s;
  fixYear();
}
function fixYear() {
  const avail = yearsOf(state.ser);
  const want = state.year == null ? null : yIdx[state.year];
  if (want == null || !avail.includes(want)) {
    const national = avail.filter(i => hasValue(cell(state.ser, i, COUNTRY.i)));
    state.year = years[(national.length ? national : avail).slice(-1)[0]];
  }
}
function levelHasData(level, s, yi) {
  const row = D.vals[s][yi];
  return !!row && geo.some(g => g.level === level && hasValue(row[g.i]));
}
const availLevels = () => MAP_LEVELS.filter(l => levelHasData(l, state.ser, yIdx[state.year]));
const subLevel = () => availLevels().find(l => l !== 'region') || null;
function fixLevel() {
  const have = availLevels();
  if (!have.includes(state.level)) state.level = have[0] || 'region';
  if (state.unit && !subs.some(u => u.code === state.unit && u.parent === state.region && levelHasData(u.level, state.ser, yIdx[state.year]))) state.unit = '';
}

// ---- formatting -----------------------------------------------------------------------------------------------
function fmt(v) {
  if (v == null) return '—';
  const a = Math.abs(v);
  return (a < 10 ? nf2 : a < 1000 ? nf1 : nf0).format(v);
}
const unitLabel = x => x.vr[3];
const fmtU = (v, x) => hasValue(v) ? fmt(v) : v === -1 ? '—' : 'χωρίς στοιχεία';
const pct = v => (Math.abs(v) < 1 && v !== 0 ? pf2 : pf).format(v) + '%';
const serLabel = x => x.vr[1] + (x.q ? ' – ' + x.q : '') + ' (' + unitLabel(x) + ')';
const nameOf = x => prods[x.p].name;
function share(v, total) { return hasValue(v) && hasValue(total) && total > 0 ? v / total * 100 : null; }
const seriesFor = (code, variable, q = '') => { const p = prodBy[code]; return p ? (serByProd[p.i].find(x => x.variable === variable && x.q === q) || serByProd[p.i].find(x => x.variable === variable)) : null; };
const seriesOfProduct = (p, variable, q = '') => serByProd[p].find(x => x.variable === variable && x.q === q) || serByProd[p].find(x => x.variable === variable);
const valueOf = (code, variable, g = focusGeo(), yi = yIdx[state.year]) => { const s = seriesFor(code, variable); return s ? cell(s.s, yi, g.i) : null; };
const yearRange = p => {
  const ys = new Set();
  serByProd[p].forEach(x => yearsOf(x.s).forEach(i => ys.add(years[i])));
  const a = [...ys].sort((x, y) => x - y);
  return a.length ? (a.length === 1 ? String(a[0]) : years.length <= 4 ? a.join(', ') : a[0] + '–' + a[a.length - 1]) : '';
};
const api = {state, D, geo, geoBy, COUNTRY, regions, prods, prodBy, sers, years, yIdx, cell, hasValue, fmt, pct, share, valueOf, seriesFor,
             seriesOfProduct, focusGeo, curSer, curProd, gname, unitLabel, esc, nf0, nf1, nf2};

// ---- filters --------------------------------------------------------------------------------------------------
function fillSelect(el, items, value) {
  el.innerHTML = items.map(([v, t, d]) => `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}${d ? ' disabled' : ''}>${esc(t)}</option>`).join('');
}
function renderFilters() {
  const p = curProd();
  fillSelect($('f-cat'), cats.map(c => [c.i, c.name]), p.cat);
  const inCat = prods.filter(x => x.cat === p.cat).sort(byTotal);
  fillSelect($('f-prod'), inCat.map(x => [x.i, x.name + (x.kind === 1 ? ' (σύνολο)' : '') + ' · ' + yearRange(x.i)]), state.prod);
  fillSelect($('f-ser'), serByProd[state.prod].map(x => [x.s, serLabel(x)]), state.ser);
  const avail = yearsOf(state.ser);
  fillSelect($('f-year'), [...avail].reverse().map(i => [years[i], years[i] + (hasValue(cell(state.ser, i, COUNTRY.i)) ? '' : ' (χωρίς σύνολο χώρας)')]), state.year);
  fillSelect($('f-region'), [['', 'Όλη η χώρα'], ...regions.map(r => [r.code, r.name]), ...zones.map(z => [z.code, gname(z)])], state.region);
  $('f-unit-field').hidden = !SUB_LEVELS.length;
  $('unitCard').hidden = !SUB_LEVELS.length;
  const lvl = subLevel();
  $('f-unit-label').textContent = lvl === 'prefecture' ? 'Νομός' : lvl === 'unit' ? 'Περιφερειακή ενότητα' : SUB_LEVELS.length > 1 ? 'Νομός / περιφερειακή ενότητα' : 'Περιφερειακή ενότητα';
  const us = state.region && lvl ? subsOf(state.region, lvl).filter(u => hasValue(cell(state.ser, yIdx[state.year], u.i)) || u.code === state.unit) : [];
  const allText = !lvl ? 'Δεν δημοσιεύονται στοιχεία κάτω από την περιφέρεια' : state.region ? (lvl === 'prefecture' ? 'Όλοι οι νομοί της περιφέρειας' : 'Όλες οι ενότητες της περιφέρειας') : 'Επιλέξτε πρώτα περιφέρεια';
  fillSelect($('f-unit'), [['', allText]].concat(us.map(u => [u.code, u.name])), state.unit);
  $('f-unit').disabled = !state.region || !lvl;
  const cmpItems = [['', 'Χωρίς σύγκριση'], ['EL', COUNTRY.name], ...regions.map(r => [r.code, r.name]), ...zones.map(z => [z.code, gname(z)]), ...subs.slice().sort((a, b) => collator.compare(a.name, b.name)).map(u => [u.code, gname(u)])];
  fillSelect($('f-cmp'), cmpItems, state.cmp);
  const have = availLevels();
  $('m-level').innerHTML = MAP_LEVELS.map(l => `<button type="button" data-v="${l}" aria-pressed="${l === state.level}"${have.includes(l) ? '' : ' disabled title="Η πηγή δεν δίνει στοιχεία σε αυτό το επίπεδο για το επιλεγμένο μέγεθος και έτος"'}>${BTN_LEVEL[l]}</button>`).join('');
  $('m-level').querySelectorAll('button').forEach(b => b.onclick = () => { state.level = b.dataset.v; update(false); });
}

// ---- KPIs -----------------------------------------------------------------------------------------------------
function renderKpis() {
  const g = focusGeo(), x = curSer(), yi = yIdx[state.year], p = curProd();
  const prov = provenance(x.s, yi);
  const v = cell(x.s, yi, g.i), nat = cell(x.s, yi, COUNTRY.i);
  const src = `${state.year} · ${srcLabel(x.s)}`;
  const items = [];
  for (const [label, code, variable, note] of cfg.headline || []) {
    const s = seriesFor(code, variable);
    const val = s ? cell(s.s, yIdx[state.year], g.i) : null;
    const fl = s && !hasValue(val) ? flagsOf(s.s, yIdx[state.year], g.i) : [];
    const shown = !s ? '—' : fl.includes('combined') || fl.some(f => f.startsWith('includes_')) ? 'ενιαίο σύνολο' : fl.includes('confidential') ? 'εμπιστευτικό' : fmtU(val, s);
    items.push([label, shown, `${state.year} · ${s ? (cfg.sources[datasetOf(s.s)] || {}).short || srcLabel(s.s) : ''}${s ? ' · ' + unitLabel(s) : ''}${note ? ' · ' + note : ''}`]);
  }
  if (cfg.extraKpis) items.push(...cfg.extraKpis(api, g));
  items.push([x.vr[1] + ': ' + p.name, fmtU(v, x), `${src} · ${unitLabel(x)}${x.q ? ' · ' + x.q : ''}`]);
  if (g.code !== 'EL') {
    items.push(['Μερίδιο στη χώρα', share(v, nat) == null ? '—' : pct(share(v, nat)), `${src} · ως προς την τιμή της χώρας (${hasValue(nat) ? fmt(nat) + ' ' + unitLabel(x) : 'δεν δημοσιεύεται'})`]);
    const ranked = regions.map(r => ({r, v: cell(x.s, yi, r.i)})).filter(o => hasValue(o.v)).sort((a, b) => b.v - a.v);
    if (g.level !== 'zone') {
      const reg = g.level === 'region' ? g : geoBy[g.parent];
      const pos = ranked.findIndex(o => o.r.code === reg.code);
      items.push([`Θέση της περιφέρειας ${reg.name}`, pos >= 0 ? (pos + 1) + 'η από ' + ranked.length : '—', `${src} · κατάταξη περιφερειών ως προς το επιλεγμένο μέγεθος`]);
    }
  } else {
    const top = regions.map(r => ({r, v: cell(x.s, yi, r.i)})).filter(o => hasValue(o.v)).sort((a, b) => b.v - a.v)[0];
    items.push(['Περιφέρεια με τη μεγαλύτερη τιμή', top ? top.r.name : '—', `${src} · ${unitLabel(x)}`]);
  }
  $('kpis').innerHTML = items.map(([l, val, sub]) => `<article class="card"><div class="kpi-label">${esc(l)}</div><div class="kpi-value${/^[\d—]/.test(val) ? '' : ' txt'}">${esc(val)}</div><div class="kpi-sub">${esc(sub)}</div></article>`).join('');
  const stage = provText(prov);
  $('scope').textContent = `${gname(g)} · ${p.name} · έτος αναφοράς ${state.year}${stage ? ' · ' + stage : ''}`;
  $('srcYear').innerHTML = prov ? `έτος αναφοράς ${state.year}: <a href="${pageUrl(x.s, prov[0])}" target="_blank" rel="noopener">έκδοση ${prov[0]} της ΕΛΣΤΑΤ</a>${prov[4] ? ', πίνακας ' + esc(prov[4]) : ''} · ${esc(provText(prov))}` : '';
}

// ---- colour scale and map -------------------------------------------------------------------------------------
const PALETTE = ['#e2ebdd', '#bdd2b6', '#8db08b', '#4f7f63', '#1d4636'];
function classify(values) {
  const pos = values.filter(v => v > 0).sort((a, b) => a - b);
  if (!pos.length) return {classes: [], color: () => PALETTE[0]};
  const n = Math.min(PALETTE.length, pos.length);
  const cuts = [...new Set(Array.from({length: n - 1}, (_, k) => pos[Math.floor(pos.length * (k + 1) / n)]))].filter(c => c > pos[0]);
  const count = cuts.length + 1;
  const shade = i => PALETTE[count === 1 ? PALETTE.length - 1 : Math.round(i * (PALETTE.length - 1) / (count - 1))];
  const classes = Array.from({length: count}, (_, i) => ({lo: i === 0 ? pos[0] : cuts[i - 1], hi: i < cuts.length ? cuts[i] : pos[pos.length - 1], color: shade(i)}));
  return {classes, color: v => classes[cuts.filter(c => v >= c).length].color};
}
function mapValues(level) {
  const x = curSer(), yi = yIdx[state.year], nat = cell(x.s, yi, COUNTRY.i);
  return geo.filter(g => g.level === level).map(g => {
    const raw = cell(x.s, yi, g.i);
    const v = state.mode === 'share' ? share(raw, nat) : raw;
    return {g, raw, v: state.mode === 'share' && !hasValue(raw) ? raw : v};
  });
}
function noValueText(s, yi, g, raw) {
  if (raw === -1) return '— (η πηγή δεν δημοσιεύει τιμή)';
  const fl = s != null ? flagsOf(s, yi, g.i) : [];
  return fl.length ? flagText(fl[0]) : 'Χωρίς στοιχεία';
}
function tipHtml(o) {
  const x = curSer(), yi = yIdx[state.year], prov = provenance(x.s, yi), nat = cell(x.s, yi, COUNTRY.i);
  const body = hasValue(o.raw) ? `${fmt(o.raw)} ${unitLabel(x)}` + (o.g.code !== 'EL' && share(o.raw, nat) != null ? `<br>${pct(share(o.raw, nat))} της χώρας` : '') : esc(noValueText(x.s, yi, o.g, o.raw));
  return `<strong>${esc(gname(o.g))}</strong>${esc(curProd().name)} · ${state.year}<br>${body}` +
    `<span class="src">${esc(srcLabel(x.s))}${prov ? ' · ' + esc(provText(prov)) : ''}</span>`;
}
function renderMap() {
  const x = curSer(), yi = yIdx[state.year];
  const level = state.level;
  const data = mapValues(level);
  const cls = classify(data.map(o => o.v).filter(v => v != null && v >= 0));
  const [, , W, H] = G.viewBox;
  const svg = $('map');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const list = G[GEO_KEY[level]] || {};
  const byCode = Object.fromEntries(data.map(o => [o.g.code, o]));
  const sel = state.unit || state.region;
  let paths = '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#f1f4ee"/><line x1="0" y1="0" x2="0" y2="6" stroke="#cfd8cb" stroke-width="2"/></pattern></defs>';
  const order = Object.keys(list).sort((a, b) => (a === state.cmp || a === sel ? 1 : 0) - (b === state.cmp || b === sel ? 1 : 0));
  for (const code of order) {
    const o = byCode[code];
    if (!o) continue;
    const fill = hasValue(o.v) ? (o.v === 0 ? '#f1f4ee' : cls.color(o.v)) : o.raw === -1 ? '#f4eddc' : 'url(#hatch)';
    const outside = SUB_LEVELS.includes(level) && state.region && o.g.parent !== state.region;
    const classes = ['area', code === sel ? 'sel' : '', code === state.cmp ? 'cmp' : '', outside ? 'dim' : ''].filter(Boolean).join(' ');
    paths += `<path class="${classes}" data-code="${code}" d="${list[code].path}" fill="${fill}" tabindex="0" role="button" aria-label="${esc(gname(o.g))}: ${esc(hasValue(o.raw) ? fmt(o.raw) + ' ' + unitLabel(x) : noValueText(x.s, yi, o.g, o.raw))}"/>`;
  }
  if (level !== 'region' && G.regions) for (const code in G.regions) paths += `<path class="outline" d="${G.regions[code].path}"/>`;
  svg.innerHTML = paths;
  const fmtV = v => state.mode === 'share' ? pct(v) : fmt(v);
  const ranges = cls.classes.map(c => `<span><i style="background:${c.color}"></i>${fmtV(c.lo)} – ${fmtV(c.hi)}</span>`);
  $('mapLegend').innerHTML = ranges.join('') +
    `<span><i style="background:#f4eddc"></i>— δεν δημοσιεύεται τιμή</span><span><i style="background:repeating-linear-gradient(45deg,#cfd8cb,#cfd8cb 2px,#f1f4ee 2px,#f1f4ee 5px)"></i>χωρίς στοιχεία</span>`;
  $('mapSub').textContent = `${curProd().name} · ${x.vr[1]}${x.q ? ' – ' + x.q : ''} · ${state.mode === 'share' ? '% της τιμής της χώρας' : unitLabel(x)} · ${state.year}. Επίπεδο: ${MAP_LEVEL[level].toLowerCase()}.`;
  const nat = cell(x.s, yi, COUNTRY.i);
  const top = data.filter(o => hasValue(o.raw)).sort((a, b) => b.raw - a.raw);
  const missing = data.length - top.length;
  $('mapInsight').textContent = top.length ? `Υψηλότερη τιμή: ${gname(top[0].g)} (${fmt(top[0].raw)} ${unitLabel(x)}${hasValue(nat) && nat > 0 ? ', ' + pct(top[0].raw / nat * 100) + ' της χώρας' : ''}).${missing ? ' Χωρίς τιμή: ' + missing + ' από ' + data.length + ' περιοχές.' : ''} Τα στοιχεία δίνονται μόνο στο επίπεδο που δημοσιεύει η πηγή.` : 'Δεν υπάρχουν τιμές για το επιλεγμένο επίπεδο και έτος.';
  const chips = [];
  chips.push(`<span class="chip">Επιλεγμένη περιοχή: <strong>${esc(gname(focusGeo()))}</strong>${sel ? '<button type="button" data-clear="main" aria-label="Αφαίρεση επιλογής">×</button>' : ''}</span>`);
  if (state.cmp) chips.push(`<span class="chip cmp">Σύγκριση με: <strong>${esc(gname(geoBy[state.cmp]))}</strong><button type="button" data-clear="cmp" aria-label="Αφαίρεση σύγκρισης">×</button></span>`);
  $('chips').innerHTML = chips.join('');
  $('chips').querySelectorAll('button').forEach(b => b.onclick = () => { if (b.dataset.clear === 'cmp') state.cmp = ''; else { state.region = ''; state.unit = ''; } update(); });
  svg.querySelectorAll('path.area').forEach(p => {
    const o = byCode[p.dataset.code];
    p.onmouseenter = ev => showTip(o, ev, p);
    p.onmousemove = ev => placeTip(ev);
    p.onmouseleave = hideTip;
    p.onfocus = () => showTip(o, null, p);
    p.onblur = hideTip;
    p.onclick = ev => chooseArea(o.g, ev.shiftKey || ev.altKey);
    p.onkeydown = ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); chooseArea(o.g, ev.shiftKey); } };
  });
}
function showTip(o, ev, node) {
  const tip = $('tip');
  tip.innerHTML = tipHtml(o); tip.hidden = false;
  if (ev) placeTip(ev); else { const r = node.getBoundingClientRect(), w = $('mapWrap').getBoundingClientRect(); tip.style.left = Math.max(4, r.left - w.left + r.width / 2) + 'px'; tip.style.top = Math.max(4, r.top - w.top) + 'px'; }
}
function placeTip(ev) {
  const tip = $('tip'), w = $('mapWrap').getBoundingClientRect();
  let left = ev.clientX - w.left + 14, top = ev.clientY - w.top + 14;
  if (left + tip.offsetWidth > w.width) left = ev.clientX - w.left - tip.offsetWidth - 14;
  if (top + tip.offsetHeight > w.height) top = ev.clientY - w.top - tip.offsetHeight - 14;
  tip.style.left = Math.max(0, left) + 'px'; tip.style.top = Math.max(0, top) + 'px';
}
function hideTip() { $('tip').hidden = true; }
function chooseArea(g, asCompare) {
  if (asCompare || state.pick === 'cmp') { state.cmp = state.cmp === g.code ? '' : g.code; }
  else if (!isTop(g)) { state.region = g.parent; state.unit = g.code; }
  else { state.region = state.region === g.code && !state.unit ? '' : g.code; state.unit = ''; }
  update();
}

// ---- comparison -----------------------------------------------------------------------------------------------
function renderCompare() {
  const a = focusGeo(), b = state.cmp ? geoBy[state.cmp] : null, yi = yIdx[state.year], x = curSer(), p = curProd();
  $('cmpSub').textContent = `${p.name} · ${state.year}. Ποσοστά ως προς την τιμή της χώρας για το ίδιο προϊόν και μέγεθος (κοινός παρονομαστής).`;
  const nat = cell(x.s, yi, COUNTRY.i);
  const geos = b ? [a, b] : [a];
  const val = g => { const v = cell(x.s, yi, g.i); return hasValue(v) ? fmt(v) + ' ' + unitLabel(x) : v === -1 ? '—' : 'χωρίς στοιχεία'; };
  const rows = [[`${x.vr[1]}${x.q ? ' – ' + x.q : ''} (${unitLabel(x)})`, g => val(g)]];
  rows.push(['Μερίδιο στη χώρα', g => { const s = share(cell(x.s, yi, g.i), nat); return g.code === 'EL' ? '100%' : s == null ? '—' : pct(s); }]);
  for (const other of serByProd[p.i].filter(y => y.s !== x.s && y.q === x.q)) {
    rows.push([`${other.vr[1]} (${unitLabel(other)})`, g => { const v = cell(other.s, yi, g.i); return hasValue(v) ? fmt(v) : '—'; }]);
  }
  for (const [label, fn] of (cfg.compareRows ? cfg.compareRows(api) : [])) rows.push([label, g => fn(g)]);
  const head = `<thead><tr><th></th>${geos.map(g => `<th>${esc(gname(g))}</th>`).join('')}</tr></thead>`;
  const body = rows.map(([l, f]) => `<tr><td>${esc(l)}</td>${geos.map((g, i) => `<td class="${i ? 'b' : 'a'}">${esc(f(g))}</td>`).join('')}</tr>`).join('');
  let diff = '';
  if (b && hasValue(cell(x.s, yi, a.i)) && hasValue(cell(x.s, yi, b.i)) && cell(x.s, yi, b.i) > 0) {
    const r = cell(x.s, yi, a.i) / cell(x.s, yi, b.i);
    diff = `<p class="cmp-note">Η τιμή της περιοχής «${esc(gname(a))}» είναι ${nf2.format(r)} φορές αυτή της «${esc(gname(b))}» για το ίδιο μέγεθος. Η σύγκριση συνολικών τιμών επηρεάζεται από το μέγεθος των περιοχών.</p>`;
  }
  $('cmpBody').innerHTML = `<table class="cmp-table">${head}<tbody>${body}</tbody></table>${b ? '' : '<p class="cmp-note">Επιλέξτε περιοχή σύγκρισης από τη λίστα ή από τον χάρτη (Shift + κλικ, ή «Κλικ στον χάρτη: περιοχή για → Σύγκριση»).</p>'}${diff}`;
}

// ---- bar lists ------------------------------------------------------------------------------------------------
function barRows(el, rows, opts = {}) {
  const max = Math.max(1, ...rows.map(r => hasValue(r.v) ? r.v : 0));
  el.innerHTML = rows.length ? rows.map((r, i) => {
    const track = hasValue(r.v) ? `<span class="track"><span class="births" style="width:${Math.max(r.v / max * 100, r.v > 0 ? .8 : 0)}%"></span></span>` : '<span class="track"><span class="na"></span></span>';
    const val = hasValue(r.v) ? `${esc(r.text)}${r.sub ? `<small>${esc(r.sub)}</small>` : ''}` : (r.v === -1 ? '—' : 'χωρίς στοιχεία');
    const tag = r.code ? `button type="button" class="hrow${r.sel ? ' sel' : ''}" data-code="${r.code}"` : 'div class="hrow"';
    return `<${tag}><span class="name">${opts.rank ? `<span class="rank">${i + 1}.</span> ` : ''}${esc(r.name)}${r.note ? `<small>${esc(r.note)}</small>` : ''}</span>${track}<span class="val">${val}</span></${r.code ? 'button' : 'div'}>`;
  }).join('') : `<p class="empty">${esc(opts.empty || 'Δεν υπάρχουν στοιχεία για την επιλογή.')}</p>`;
  if (opts.onclick) el.querySelectorAll('button.hrow').forEach(b => b.onclick = () => opts.onclick(b.dataset.code));
}
const byValueDesc = (a, b) => (hasValue(b.raw) ? b.raw : -1e18) - (hasValue(a.raw) ? a.raw : -1e18) || collator.compare(a.g.name, b.g.name);
function renderRanking() {
  const x = curSer(), yi = yIdx[state.year], nat = cell(x.s, yi, COUNTRY.i);
  const rows = regions.map(r => ({g: r, raw: cell(x.s, yi, r.i)})).sort(byValueDesc);
  $('rankSub').textContent = `${curProd().name} · ${x.vr[1]}${x.q ? ' – ' + x.q : ''} (${unitLabel(x)}) · ${state.year}. Επιλέξτε περιφέρεια για να ενημερωθεί όλη η σελίδα.`;
  const sel = state.unit ? geoBy[state.unit].parent : state.region;
  barRows($('rankBars'), rows.map(o => ({code: o.g.code, name: o.g.name, v: o.raw, sel: o.g.code === sel, text: fmt(o.raw), sub: share(o.raw, nat) != null ? pct(share(o.raw, nat)) + ' της χώρας' : ''})), {rank: true,
    onclick: c => { state.region = state.region === c && !state.unit ? '' : c; state.unit = ''; update(); }});
  const have = rows.filter(o => hasValue(o.raw));
  const top3 = have.slice(0, 3).reduce((s, o) => s + o.raw, 0);
  $('rankInsight').textContent = have.length ? `Οι τρεις πρώτες περιφέρειες (${have.slice(0, 3).map(o => o.g.name).join(', ')}) συγκεντρώνουν ${hasValue(nat) && nat > 0 ? pct(top3 / nat * 100) + ' της τιμής της χώρας' : fmt(top3) + ' ' + unitLabel(x)}.${have.length < regions.length ? ' Για ' + (regions.length - have.length) + ' περιφέρειες δεν υπάρχει τιμή.' : ''}` : '';
}
function renderSubs() {
  const x = curSer(), yi = yIdx[state.year], nat = cell(x.s, yi, COUNTRY.i), lvl = subLevel();
  const title = $('unitTitle');
  title.textContent = lvl === 'prefecture' ? 'Κατανομή ανά νομό' : 'Κατανομή ανά περιφερειακή ενότητα';
  if (!lvl) {
    $('unitSub').textContent = `Για το έτος ${state.year} η πηγή δίνει στοιχεία μόνο σε επίπεδο χώρας και περιφέρειας· δεν υπάρχει ανάλυση ανά νομό ή περιφερειακή ενότητα και δεν γίνεται επιμερισμός.`;
    barRows($('unitBars'), [], {empty: 'Δεν υπάρχουν στοιχεία κάτω από το επίπεδο της περιφέρειας.'});
    return;
  }
  const pool = state.region ? subsOf(state.region, lvl) : subs.filter(u => u.level === lvl);
  let rows = pool.map(u => ({g: u, raw: cell(x.s, yi, u.i)})).sort(byValueDesc);
  const limit = state.region ? rows.length : 15;
  const word = lvl === 'prefecture' ? 'νομοί' : 'περιφερειακές ενότητες';
  $('unitSub').textContent = state.region ? `${lvl === 'prefecture' ? 'Νομοί' : 'Περιφερειακές ενότητες'} της Περιφέρειας ${geoBy[state.region].name} · ${unitLabel(x)} · ${state.year}.` : `Οι ${limit} ${word} με τη μεγαλύτερη τιμή στη χώρα · ${unitLabel(x)} · ${state.year}. Επιλέξτε περιφέρεια για να δείτε όλες.`;
  rows = rows.slice(0, limit);
  barRows($('unitBars'), rows.map(o => ({code: o.g.code, name: o.g.name, note: state.region ? '' : geoBy[o.g.parent].name, v: o.raw, sel: o.g.code === state.unit, text: fmt(o.raw), sub: share(o.raw, nat) != null ? pct(share(o.raw, nat)) + ' της χώρας' : ''})), {rank: true,
    onclick: c => { const g = geoBy[c]; state.region = g.parent; state.unit = state.unit === c ? '' : c; update(); }});
}
function renderProducts() {
  const x = curSer(), yi = yIdx[state.year], g = focusGeo(), cat = cats[curProd().cat];
  const rows = [];
  for (const p of prods.filter(p => p.cat === curProd().cat)) {
    const s = serByProd[p.i].find(y => y.variable === x.variable && y.q === x.q);
    if (s) rows.push({p, s, raw: cell(s.s, yi, g.i)});
  }
  const list = rows.filter(r => hasValue(r.raw)).sort((a, b) => b.raw - a.raw);
  const shown = list.slice(0, 18);
  const missing = rows.filter(r => !hasValue(r.raw)).length;
  $('prodSub').textContent = `Κατηγορία «${cat.name}» · ${gname(g)} · ${x.vr[1].toLowerCase()} (${unitLabel(x)}) · ${state.year}. ${cfg.notAdditive || 'Κάθε γραμμή είναι αυτοτελής τιμή της πηγής· οι γραμμές δεν αθροίζονται.'}`;
  barRows($('prodBars'), shown.map(r => ({code: '', name: r.p.name, v: r.raw, text: fmt(r.raw), sub: ''})), {empty: 'Δεν υπάρχουν τιμές για την κατηγορία, την περιοχή και το έτος.'});
  $('prodInsight').textContent = list.length ? `Μεγαλύτερη τιμή στην κατηγορία: ${list[0].p.name} (${fmt(list[0].raw)} ${unitLabel(x)}).${list.length > shown.length ? ' Εμφανίζονται οι ' + shown.length + ' από ' + list.length + ' γραμμές με τιμή.' : ''}${missing ? ' Χωρίς τιμή για την περιοχή και το έτος: ' + missing + '.' : ''}` : '';
}

// ---- line charts ----------------------------------------------------------------------------------------------
function niceStep(range, ticks) { const raw = range / ticks, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * mag; }
function lineChart(el, lines, opts = {}) {
  const breaks = opts.breaks || [];
  const pts = lines.map(l => ({...l, points: years.map((y, i) => [y, l.values[i]]).filter(([, v]) => hasValue(v))}));
  const all = pts.flatMap(l => l.points);
  if (!all.length) { el.innerHTML = '<p class="empty">Δεν υπάρχουν στοιχεία για τα επιλεγμένα φίλτρα.</p>'; return; }
  const W = 900, H = 300, L = 70, R = 24, T = 14, B = 30;
  const vmax = Math.max(...all.map(p => p[1])), vmin = Math.min(0, ...all.map(p => p[1]));
  const step = niceStep((vmax - vmin) || 1, 5), lo = Math.floor(vmin / step) * step, hi = Math.ceil(vmax / step) * step || step;
  const y0 = years[0], y1 = years[years.length - 1];
  const x = yr => L + 12 + (yr - y0) / (y1 - y0 || 1) * (W - L - R - 24);
  const y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  let g = '';
  for (let v = lo; v <= hi + step / 1000; v += step) g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#e2e7dd"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${esc(fmt(v))}</text>`;
  years.forEach(yr => { if (years.length <= 8 || yr % 2 === 1 || yr === y1) g += `<text x="${x(yr)}" y="${H - 8}" text-anchor="middle">${yr}</text>`; });
  for (const yr of breaks) g += `<line x1="${x(yr - .5)}" x2="${x(yr - .5)}" y1="${T}" y2="${H - B}" stroke="#8a5f22" stroke-dasharray="3 4"/><text x="${x(yr - .5) + 3}" y="${T + 10}" style="fill:#8a5f22">διακοπή σειράς</text>`;
  for (const l of pts) {
    let path = '', prev = null;
    for (const [yr, v] of l.points) {
      const gap = prev == null || (!opts.connect && yr - prev > 1) || breaks.some(b => prev < b && yr >= b);
      path += `${gap ? 'M' : 'L'}${x(yr).toFixed(1)} ${y(v).toFixed(1)}`;
      prev = yr;
    }
    g += `<path d="${path}" fill="none" stroke="${l.color}" stroke-width="${opts.connect ? 1.6 : 2.4}" stroke-linejoin="round"${opts.connect || l.dash ? ' stroke-dasharray="6 4"' : ''}/>`;
    for (const [yr, v] of l.points) g += `<circle cx="${x(yr).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.4" fill="${l.color}"><title>${yr} · ${esc(l.label)}: ${fmt(v)} ${esc(opts.unit || '')}</title></circle>`;
  }
  el.innerHTML = `<svg class="line" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label || 'Εξέλιξη')}">${g}</svg>`;
}
const COLORS = ['#315b46', '#c58b3d', '#527961', '#8a5f22', '#95ad78', '#b9c4b2'];
const seriesValues = (s, gi) => years.map((_, i) => { const v = cell(s, i, gi); return hasValue(v) ? v : null; });
function renderTrends() {
  const p = curProd(), x = curSer(), geos = [focusGeo()].concat(state.cmp ? [geoBy[state.cmp]] : []);
  const connect = !!cfg.periodic;
  const where = `${gname(geos[0])}${geos[1] ? ' και ' + gname(geos[1]) : ''}`;
  const draw = (prefix, s, label) => {
    const lines = geos.map((g, k) => ({label: gname(g), values: seriesValues(s.s, g.i), color: COLORS[k], dash: k === 1}));
    $(prefix + 'Sub').textContent = `${p.name} · ${s.vr[1]}${s.q ? ' – ' + s.q : ''} (${unitLabel(s)}) · ${where}. ${cfg.periodic ? 'Η έρευνα δεν είναι ετήσια: τα σημεία είναι οι εκδόσεις της, η διακεκομμένη γραμμή μόνο τα ενώνει και δεν δείχνει τις ενδιάμεσες χρονιές.' : 'Τα έτη με «—» ή χωρίς τιμή δεν σχεδιάζονται· δεν θεωρούνται μηδενικά.'}`;
    $(prefix + 'Legend').innerHTML = lines.map(l => `<span><i style="background:${l.color}"></i>${esc(l.label)}</span>`).join('');
    lineChart($(prefix + 'Chart'), lines, {unit: unitLabel(s), label: label + ' ' + s.vr[1], connect, breaks: p.breaks});
    const first = lines[0].values.map((v, i) => [years[i], v]).filter(([, v]) => v != null);
    $(prefix + 'Insight').textContent = first.length > 1 ? `${gname(geos[0])}: ${fmt(first[0][1])} ${unitLabel(s)} το ${first[0][0]} και ${fmt(first[first.length - 1][1])} ${unitLabel(s)} το ${first[first.length - 1][0]}.` : first.length === 1 ? `Μία μόνο τιμή για την περιοχή: ${fmt(first[0][1])} ${unitLabel(s)} το ${first[0][0]}.` : '';
  };
  draw('trend', x, 'Εξέλιξη');
  const other = serByProd[p.i].filter(y => y.s !== x.s && y.q === x.q && yearsOf(y.s).length)[0] || serByProd[p.i].filter(y => y.s !== x.s && yearsOf(y.s).length)[0];
  $('otherCard').hidden = !other;
  if (other) draw('other', other, 'Εξέλιξη');
}

// ---- data table -----------------------------------------------------------------------------------------------
const PAGE = 25;
const COLS = [
  ['year', 'Έτος αναφοράς', 'num'], ['geo', 'Περιοχή', ''], ['level', 'Επίπεδο', ''], ['product', 'Προϊόν / είδος', ''], ['measure', 'Μέγεθος', ''],
  ['value', 'Τιμή', 'num'], ['unit', 'Μονάδα', ''], ['status', 'Κατάσταση', ''], ['source', 'Πηγή και δημοσίευση', ''], ['flags', 'Παρατηρήσεις', 'flag']
];
function tableRows() {
  const p = curProd();
  const prodList = state.scope === 'category' ? prods.filter(q => q.cat === p.cat) : [p];
  const yis = state.tyears === 'all' ? years.map((_, i) => i) : [yIdx[state.year]];
  const geoList = state.unit ? [geoBy[state.unit]] : state.region ? [geoBy[state.region], ...subsOf(state.region)] : geo;
  const rows = [];
  for (const q of prodList) for (const x of serByProd[q.i]) for (const yi of yis) {
    if (!D.vals[x.s][yi]) continue;
    const prov = provenance(x.s, yi);
    for (const g of geoList) {
      if (state.tlevel !== 'all' && g.level !== state.tlevel) continue;
      const v = cell(x.s, yi, g.i);
      const fl = flagsOf(x.s, yi, g.i);
      if (v === null && !fl.length) continue;
      rows.push({year: years[yi], geo: gname(g), level: LEVEL[g.level], code: g.code, product: q.name, category: cats[q.cat].name, measure: x.vr[1] + (x.q ? ' – ' + x.q : ''),
        value: hasValue(v) ? v : null, unit: x.vr[3], status: hasValue(v) ? 'Δημοσιευμένη τιμή' : v === -1 ? 'Δεν δημοσιεύεται («—»)' : fl.includes('confidential') ? 'Εμπιστευτική τιμή («x»)' : 'Χωρίς τιμή στην πηγή',
        source: prov ? `${srcLabel(x.s)} · ${provText(prov)}` : srcLabel(x.s), dataset: datasetOf(x.s), edition: prov ? prov[0] : '', pub: prov && prov[3] ? prov[3].slice(0, 4) : '', stage: prov ? prov[2] : '', pubdate: prov ? prov[3] : '', table: prov ? prov[4] : '',
        updated: prov ? prov[5] : '', doc: prov ? prov[1] : '', flags: fl.map(flagText).join('; ')});
    }
  }
  const needle = state.search.trim().toLocaleLowerCase('el');
  const filtered = needle ? rows.filter(r => (r.year + ' ' + r.geo + ' ' + r.level + ' ' + r.product + ' ' + r.measure + ' ' + r.source + ' ' + r.flags + ' ' + (r.value == null ? '' : fmt(r.value))).toLocaleLowerCase('el').includes(needle)) : rows;
  const {k, dir} = state.sort;
  filtered.sort((a, b) => {
    const av = a[k], bv = b[k];
    const c = typeof av === 'number' || av === null && typeof bv === 'number' ? (av ?? -Infinity) - (bv ?? -Infinity) : collator.compare(String(av ?? ''), String(bv ?? ''));
    return (c || a.year - b.year || collator.compare(a.geo, b.geo)) * dir;
  });
  return filtered;
}
function renderTable() {
  const rows = tableRows();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  state.page = Math.min(state.page, pages - 1);
  $('dataTable').tHead.innerHTML = '<tr>' + COLS.map(([k, t, c]) => `<th data-k="${k}" class="${c}" scope="col" aria-sort="${state.sort.k === k ? (state.sort.dir > 0 ? 'ascending' : 'descending') : 'none'}" tabindex="0">${t}<span class="arrow">${state.sort.k === k ? (state.sort.dir > 0 ? '▲' : '▼') : ''}</span></th>`).join('') + '</tr>';
  const slice = rows.slice(state.page * PAGE, state.page * PAGE + PAGE);
  $('dataTable').tBodies[0].innerHTML = slice.length ? slice.map(r => '<tr>' + COLS.map(([k, , c]) =>
    `<td class="${c}">${esc(k === 'value' ? (r.value == null ? '—' : fmt(r.value)) : r[k])}</td>`).join('') + '</tr>').join('') : `<tr><td colspan="${COLS.length}" class="empty">Δεν υπάρχουν εγγραφές για τα επιλεγμένα φίλτρα.</td></tr>`;
  $('t-info').textContent = `${nf0.format(rows.length)} εγγραφές · τιμές στη μονάδα της πηγής`;
  $('t-page').textContent = `Σελίδα ${state.page + 1} από ${pages}`;
  $('t-prev').disabled = state.page === 0; $('t-next').disabled = state.page >= pages - 1;
  $('tableSub').textContent = `${state.scope === 'category' ? 'Κατηγορία «' + cats[curProd().cat].name + '»' : curProd().name} · ${state.tyears === 'all' ? 'όλα τα έτη' : state.year} · ${gname(focusGeo())}${state.region && !state.unit ? ' και οι υποδιαιρέσεις της' : ''}. Η εξαγωγή CSV περιλαμβάνει όλες τις εγγραφές των φίλτρων, όχι μόνο την τρέχουσα σελίδα.`;
  document.querySelectorAll('#dataTable th[data-k]').forEach(th => {
    const sort = () => { const k = th.dataset.k; state.sort = {k, dir: state.sort.k === k ? -state.sort.dir : (k === 'value' || k === 'year' ? -1 : 1)}; state.page = 0; renderTable(); };
    th.onclick = sort; th.onkeydown = ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); sort(); } };
  });
}
function csvCell(v) { const s = v == null ? '' : String(v); return /[",;\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
function exportCsv() {
  const rows = tableRows();
  const head = ['Έτος αναφοράς', 'Έτος δημοσίευσης', 'Έκδοση ΕΛΣΤΑΤ (έτος σελίδας)', 'Στάδιο στοιχείων', 'Επίπεδο', 'Κωδικός περιοχής', 'Περιοχή', 'Κατηγορία', 'Προϊόν / είδος', 'Μέγεθος', 'Τιμή', 'Μονάδα μέτρησης', 'Κατάσταση', 'Παρατηρήσεις', 'Πηγή', 'Δημοσίευση ΕΛΣΤΑΤ (κωδικός)', 'Πίνακας πηγής', 'Ημερομηνία δημοσίευσης', 'Τελευταία ενημέρωση', 'Κωδικός εγγράφου πηγής'];
  const lines = [head.map(csvCell).join(',')].concat(rows.map(r => [r.year, r.pub, r.edition, STAGE[r.stage] || '', r.level, r.code, r.geo, r.category, r.product, r.measure, r.value, r.unit, r.status, r.flags, r.source, r.dataset, r.table, r.pubdate, r.updated, r.doc].map(csvCell).join(',')));
  const blob = new Blob(['﻿' + lines.join('\r\n') + '\r\n'], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `${cfg.csvPrefix}-${curProd().code.replace(/[^a-z0-9._-]/gi, '_')}-${state.tyears === 'all' ? 'ola-eti' : state.year}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ---- notes for the selected table and year ----------------------------------------------------------------------
function renderNotes() {
  const key = tableKey(state.ser), yr = state.year;
  const list = D.issues.filter(i => i[0] === key && i[1] === yr && ['warning', 'info'].includes(i[2]) && !['stale_sheet', 'continuation_sheet'].includes(i[3]));
  const prov = provenance(state.ser, yIdx[yr]);
  const lines = list.map(i => `<li>${esc(i[4])}</li>`);
  const own = (cfg.tableNotes ? cfg.tableNotes(api, key, yr) : []).concat(curProd().breaks.length ? [cfg.breakNote ? cfg.breakNote(curProd().breaks) : 'Η σειρά έχει διακοπή το ' + curProd().breaks.join(', ') + ': οι τιμές πριν και μετά δεν είναι συγκρίσιμες.'] : []);
  const extra = own.map(t => `<li>${esc(t)}</li>`);
  $('tableNotes').innerHTML = (lines.length || extra.length) ? `<div class="notice-box"><p><strong>Παρατηρήσεις για τον πίνακα της πηγής (${esc(key)}, έτος αναφοράς ${yr}${prov ? ', ' + provText(prov) : ''}):</strong></p><ul>${extra.join('')}${lines.join('')}</ul></div>` : '';
}

// ---- state <-> address ----------------------------------------------------------------------------------------
function writeHash() {
  const p = new URLSearchParams({p: curProd().code, s: curSer().variable + (curSer().q ? '|' + curSer().q : ''), y: state.year, r: state.region, u: state.unit, c: state.cmp, l: state.level, m: state.mode});
  try { history.replaceState(null, '', '#' + p.toString()); } catch (e) { /* file:// or sandboxed */ }
}
function readHash() {
  try {
    const p = new URLSearchParams(location.hash.slice(1));
    const prod = prods.find(x => x.code === p.get('p'));
    if (prod) {
      state.prod = prod.i;
      const [variable, q = ''] = (p.get('s') || '').split('|');
      state.ser = (serByProd[prod.i].find(x => x.variable === variable && x.q === q) || serByProd[prod.i][0]).s;
    }
    const y = +p.get('y'); if (yIdx[y] != null) state.year = y;
    if (geoBy[p.get('r')] && isTop(geoBy[p.get('r')])) state.region = p.get('r');
    const u = geoBy[p.get('u')];
    if (u && SUB_LEVELS.includes(u.level) && u.parent === state.region) state.unit = u.code;
    if (geoBy[p.get('c')]) state.cmp = p.get('c');
    if (MAP_LEVELS.includes(p.get('l'))) state.level = p.get('l');
    if (['value', 'share'].includes(p.get('m'))) state.mode = p.get('m');
  } catch (e) { /* ignore a malformed address */ }
}

// ---- wiring ---------------------------------------------------------------------------------------------------
function syncSegments() {
  for (const [id, key] of [['m-mode', 'mode'], ['m-pick', 'pick']]) document.querySelectorAll(`#${id} button`).forEach(b => b.setAttribute('aria-pressed', b.dataset.v === state[key]));
  $('t-scope').value = state.scope; $('t-years').value = state.tyears; $('t-level').value = state.tlevel; $('t-search').value = state.search;
}
function update(resetPage = true) {
  fixYear(); fixLevel();
  if (resetPage) state.page = 0;
  renderFilters(); syncSegments(); renderKpis(); renderMap(); renderCompare(); renderRanking(); renderSubs(); renderTrends(); renderProducts(); renderTable(); renderNotes(); writeHash();
}
$('f-cat').onchange = e => { const first = prods.filter(p => p.cat === +e.target.value).sort(byTotal)[0]; setProduct(first.i, true); update(); };
$('f-prod').onchange = e => { setProduct(+e.target.value, true); update(); };
$('f-ser').onchange = e => { state.ser = +e.target.value; update(); };
$('f-year').onchange = e => { state.year = +e.target.value; update(); };
$('f-region').onchange = e => { state.region = e.target.value; state.unit = ''; update(); };
$('f-unit').onchange = e => { state.unit = e.target.value; update(); };
$('f-cmp').onchange = e => { state.cmp = e.target.value; update(); };
for (const [id, key] of [['m-mode', 'mode'], ['m-pick', 'pick']]) document.querySelectorAll(`#${id} button`).forEach(b => b.onclick = () => { state[key] = b.dataset.v; update(false); });
$('t-search').oninput = e => { state.search = e.target.value; state.page = 0; renderTable(); };
$('t-scope').onchange = e => { state.scope = e.target.value; state.page = 0; renderTable(); };
$('t-years').onchange = e => { state.tyears = e.target.value; state.page = 0; renderTable(); };
$('t-level').onchange = e => { state.tlevel = e.target.value; state.page = 0; renderTable(); };
$('t-prev').onclick = () => { state.page--; renderTable(); };
$('t-next').onclick = () => { state.page++; renderTable(); };
$('t-export').onclick = exportCsv;
$('reset').onclick = () => {
  Object.assign(state, {region: '', unit: '', cmp: '', level: 'region', mode: 'value', pick: 'main', search: '', scope: 'product', tyears: 'year', tlevel: 'all', year: null, sort: {k: 'value', dir: -1}});
  setProduct(defaultProduct(), false);
  update();
};
window.addEventListener('hashchange', () => { readHash(); update(); });
setProduct(defaultProduct(), false);
readHash();
update();
};
})();
