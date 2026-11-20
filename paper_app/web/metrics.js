"use strict";

function parseCSV(text) {
  const records = [];
  let row = [], field = "", quoted = false;
  for (let index = 0; index < text.length; index++) {
    const character = text[index];
    if (quoted) {
      if (character !== '"') field += character;
      else if (text[index + 1] === '"') { field += '"'; index++; }
      else quoted = false;
    } else if (character === '"' && field === "") {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\r" || character === "\n") {
      if (character === "\r" && text[index + 1] === "\n") index++;
      records.push([...row, field]);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }
  if (quoted) throw new Error("The CSV ends inside a quoted field.");
  if (row.length || field) records.push([...row, field]);
  return records;
}

const defaultRules = `source,target,multiplier
W,mW,1000
mW,mW,1
MW,mW,1e9
µW,mW,0.001
nW,mW,0.000001
TOPS/W,TOPS/W,1
GOPS/W,TOPS/W,0.001
MOPS/W,TOPS/W,0.000001
TOPS,TOPS,1
GOPS,TOPS,0.001
MOPS,TOPS,0.000001
s,ms,1000
second,ms,1000
seconds,ms,1000
ms,ms,1
Ms,ms,1e9
µs,ms,0.001
ns,ms,0.000001
mm²,mm²,1
mm2,mm²,1
mm^2,mm²,1
µm²,mm²,0.000001
µm2,mm²,0.000001
µm^2,mm²,0.000001
Hz,MHz,0.000001
kHz,MHz,0.001
MHz,MHz,1
mHz,MHz,1e-9
GHz,MHz,1000
J,pJ,1e12
mJ,pJ,1e9
µJ,pJ,1e6
nJ,pJ,1000
pJ,pJ,1
fJ,pJ,0.001
kB/s,GB/s,0.000001
MB/s,GB/s,0.001
GB/s,GB/s,1
TB/s,GB/s,1000
kb/s,GB/s,0.000000125
Mb/s,GB/s,0.000125
Gb/s,GB/s,0.125
Tb/s,GB/s,125
kbps,GB/s,0.000000125
Mbps,GB/s,0.000125
Gbps,GB/s,0.125
Tbps,GB/s,125
FPS,frames/s,1
frames/s,frames/s,1
%,%,1`;

function unitKey(unit) {
  return unit.trim().replace(/\s+/g, "")
    .replace(/^([TGMP]OPS)per(W|mm(?:²|\^?2))$/i, "$1/$2").split("/")
    .map(part => part.replace(/^[μu](?=[A-Za-z])/i, "µ")).join("/");
}

function readRules(text) {
  const [header = [], ...body] = parseCSV(text);
  if (header.join(",") !== "source,target,multiplier") {
    throw new Error("Use this header: source,target,multiplier");
  }
  const exact = new Map(), folded = new Map();
  for (const [index, row] of body.entries()) {
    if (row.every(cell => !cell.trim())) continue;
    const [source, target, multiplier] = row.map(cell => cell.trim());
    const factor = Number(multiplier);
    const key = unitKey(source || "");
    if (row.length !== 3 || !key || !target || !Number.isFinite(factor) || factor <= 0) {
      throw new Error(`Invalid unit rule on row ${index + 2}.`);
    }
    if (exact.has(key)) throw new Error(`Duplicate source unit on row ${index + 2}.`);
    const rule = { target, factor };
    exact.set(key, rule);
    const lower = key.toLowerCase();
    if (!folded.has(lower)) folded.set(lower, rule);
    else {
      const previous = folded.get(lower);
      if (!previous || previous.target !== target || previous.factor !== factor) {
        folded.set(lower, null);
      }
    }
  }
  return { exact, folded };
}

const displayNumber = new Intl.NumberFormat("en", { maximumSignificantDigits: 12, useGrouping: false });

function conversionRule(key, rules) {
  const direct = rules.exact.get(key) ?? rules.folded.get(key.toLowerCase());
  if (direct !== undefined) return direct;

  const parts = key.split("/");
  if (parts.length !== 2 || parts.some(part => !part)) return undefined;
  const [numerator, denominator] = parts.map(part =>
    rules.exact.get(part) ?? rules.folded.get(part.toLowerCase()));
  if (numerator === null || denominator === null) return null;
  if (!numerator && !denominator) return undefined;
  return {
    target: `${numerator?.target ?? parts[0]}/${denominator?.target ?? parts[1]}`,
    factor: (numerator?.factor ?? 1) / (denominator?.factor ?? 1),
  };
}

function convert(row, rules) {
  const key = unitKey(row.originalUnit);
  const rule = conversionRule(key, rules);
  const number = rule ? row.originalNumber * rule.factor : row.originalNumber;
  const applied = rule && rule.factor > 0 && Number.isFinite(number) && (number !== 0 || row.originalNumber === 0);
  const unit = applied ? rule.target : row.originalUnit;
  const groupUnit = applied ? unit : unitKey(unit).toLowerCase();
  const groupKind = applied ? "converted" : rule !== undefined ? "unresolved" : "unmapped";
  return {
    ...row,
    unit,
    number: applied ? number : row.originalNumber,
    value: applied && rule.factor !== 1 ? displayNumber.format(number) : row.originalValue,
    group: JSON.stringify([row.metric, groupKind === "unresolved" ? key : groupUnit, groupKind]),
  };
}

const element = id => document.getElementById(id);
const group = element("group");
const paper = element("paper");
const conditions = element("conditions");
const sort = element("sort");
const status = element("status");
const results = element("results");
const unitRules = element("unit-rules");
const unitStatus = element("unit-status");
const storageKey = "paper-metrics-unit-rules";
let rawMetrics = [], metrics = [], rules = readRules(defaultRules);
let libraryGroupMembers = null;
unitRules.value = defaultRules;
try {
  const saved = localStorage.getItem(storageKey);
  if (saved) {
    rules = readRules(saved);
    unitRules.value = saved;
  }
} catch {
  // Unit conversion still works when browser storage is unavailable.
}

function refreshGroups() {
  const selected = group.value;
  metrics = rawMetrics.map(row => convert(row, rules));
  group.replaceChildren();
  const groups = new Map(metrics.map(row => [
    row.group, row.unit ? `${row.metric} (${row.unit})` : row.metric,
  ]));
  for (const [key, label] of [...groups].sort((a, b) => a[1].localeCompare(b[1]))) {
    add(group, "option", label).value = key;
  }
  updateAxes(groups);
  if (groups.has(selected)) group.value = selected;
  else if (group.options.length) group.selectedIndex = 0;
  render();
}

function applyRules() {
  try {
    rules = readRules(unitRules.value);
    refreshGroups();
    try {
      localStorage.setItem(storageKey, unitRules.value);
      unitStatus.textContent = "Rules applied and saved in this browser.";
    } catch {
      unitStatus.textContent = "Rules applied for this session. Browser storage is unavailable.";
    }
  } catch (error) {
    unitStatus.textContent = error.message;
  }
}

element("apply-units").addEventListener("click", applyRules);
element("reset-units").addEventListener("click", () => {
  unitRules.value = defaultRules;
  applyRules();
});

function add(parent, tag, text, className) {
  const child = document.createElement(tag);
  if (className) child.className = className;
  if (text !== undefined) child.textContent = text;
  parent.append(child);
  return child;
}

function render() {
  const chart = element("chart");
  const table = element("rows");
  chart.replaceChildren();
  table.replaceChildren();
  if (!metrics.length) {
    renderPairs([]);
    return;
  }
  const paperQuery = paper.value.trim().toLowerCase();
  const conditionQuery = conditions.value.trim().toLowerCase();
  const filtered = metrics.filter(row =>
    (!libraryGroupMembers || libraryGroupMembers.has(row.paper_id))
    && [row.paper, row.title || ""].some(label => label.toLowerCase().includes(paperQuery))
    && row.conditions.toLowerCase().includes(conditionQuery));
  renderPairs(filtered);
  const rows = filtered.filter(row => row.group === group.value);
  rows.sort((first, second) => (sort.value === "asc" ? 1 : -1) * (first.number - second.number));
  status.textContent = `Showing ${rows.length} matching result(s) from ${new Set(rows.map(row => row.paper_id ?? row.paper)).size} paper(s).`;
  element("chart-title").textContent = group.selectedOptions[0].textContent;
  if (!rows.length) {
    add(chart, "p", "No results match these filters.");
    return;
  }

  let minimum = 0, maximum = 0;
  for (const row of rows) {
    minimum = Math.min(minimum, row.number);
    maximum = Math.max(maximum, row.number);
  }
  // Normalize first so even the difference between extreme values stays finite.
  const scale = Math.max(Math.abs(minimum), Math.abs(maximum)) || 1;
  const span = (maximum / scale - minimum / scale) || 1;
  const position = value => 100 * (value / scale - minimum / scale) / span;
  const zero = position(0);

  for (const row of rows) {
    const value = row.unit ? `${row.value} ${row.unit}` : row.value;
    const filename = row.title || row.paper.split(/[\\/]/).pop();
    const entry = add(chart, "div", undefined, "chart-row");
    add(entry, "span", `${filename} · p. ${row.page}`, "paper").title = row.paper;
    const track = add(entry, "div", undefined, "track");
    track.setAttribute("aria-hidden", "true");
    const endpoint = position(row.number);
    const bar = add(track, "div", undefined, "bar");
    bar.style.left = `${Math.min(zero, endpoint)}%`;
    bar.style.width = `${Math.abs(endpoint - zero)}%`;
    add(track, "div", undefined, "zero").style.left = `${zero}%`;
    add(entry, "span", value, "number");

    const line = add(table, "tr");
    addPaperLabel(add(line, "td", undefined, "paper"), row);
    const pageCell = add(line, "td");
    if (!addSourcePageLink(pageCell, row, row.page)) pageCell.textContent = row.page;
    add(line, "td", value, "number");
    add(line, "td", [row.originalValue, row.originalUnit].filter(Boolean).join(" "), "number");
    add(line, "td", row.conditions || "—");
    const details = add(add(line, "td"), "details");
    add(details, "summary", "Show source");
    add(details, "p", row.evidence || "No source text in this row.");
  }
}

const xMetric = element("x-metric");
const yMetric = element("y-metric");
const matchPaperOnly = element("match-paper-only");
const xPreference = element("x-preference");
const yPreference = element("y-preference");
const comparisonPanel = element("compare-2d");
const comparisonStorageKey = "paper-metrics-comparison-settings";
let comparisonSettings = {};
try {
  const saved = JSON.parse(localStorage.getItem(comparisonStorageKey));
  if (saved && typeof saved === "object") comparisonSettings = saved;
} catch {
  // Comparison works with session defaults if preferences cannot be read.
}
matchPaperOnly.checked = comparisonSettings.allowDifferentConditions === true;
comparisonPanel.open = comparisonSettings.open === true;

function saveComparisonSettings() {
  comparisonSettings = {
    x: xMetric.value || comparisonSettings.x,
    y: yMetric.value || comparisonSettings.y,
    allowDifferentConditions: matchPaperOnly.checked,
    open: comparisonPanel.open,
  };
  try {
    localStorage.setItem(comparisonStorageKey, JSON.stringify(comparisonSettings));
  } catch {
    // The current controls remain usable if browser storage is unavailable.
  }
}

comparisonPanel.addEventListener("toggle", saveComparisonSettings);
const pairChoices = new Map();
const exportPairsButton = element("export-pairs");
let plottedPairs = [];

function comparisonCSV(points) {
  const columns = ["metric", "value", "unit", "conditions", "page"];
  const header = ["paper", ...["x", "y"].flatMap(axis => columns.map(name => `${axis}_${name}`))];
  const rows = points.map(({x, y}) => [
    paperName(x), ...[x, y].flatMap(row => [
      row.metric, row.number, row.unit, row.conditions, Number(row.page),
    ]),
  ]);
  return [header, ...rows].map(row => row.map(value => {
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    let text = String(value);
    if (/^\s*[=+@-]|^[\t\r\n]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }).join(",")).join("\r\n") + "\r\n";
}

exportPairsButton.addEventListener("click", () => {
  if (!plottedPairs.length) return;
  const csv = new Blob(["\uFEFF", comparisonCSV(plottedPairs)], {type: "text/csv;charset=utf-8"});
  const url = URL.createObjectURL(csv);
  const link = document.createElement("a");
  link.href = url;
  link.download = "paper-comparison.csv";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

function updateAxes(groups) {
  const prior = [xMetric.value || comparisonSettings.x, yMetric.value || comparisonSettings.y];
  const options = [...groups].sort((a, b) => a[1].localeCompare(b[1]));
  const available = options.map(([key]) => key);
  const selected = prior.map(key => groups.has(key) ? key : undefined);
  for (let index = 0; index < selected.length; index++) {
    selected[index] ??= available.find(key => key !== selected[1 - index]) ?? available[0];
  }
  for (const [index, picker] of [xMetric, yMetric].entries()) {
    picker.replaceChildren();
    for (const [key, label] of options) add(picker, "option", label).value = key;
    if (selected[index] !== undefined) picker.value = selected[index];
  }
}

function paperName(row) {
  return row.title || row.paper.split(/[\\/]/).pop();
}

function addPaperLabel(parent, row) {
  if (row.paper_id === undefined) {
    parent.textContent = paperName(row);
  } else {
    add(parent, "a", paperName(row)).href = `/papers?paper=${encodeURIComponent(row.paper_id)}`;
  }
  parent.title = row.paper;
}

function pairLabel(row) {
  return [`${row.value} ${row.unit}`.trim(), `p. ${row.page}`, row.conditions].filter(Boolean).join(" · ");
}

function pairCandidates(rows, x, y, paperOnly) {
  const pairs = new Map();
  if (!x || !y || x === y) return [];
  for (const row of rows) {
    if (row.group !== x && row.group !== y) continue;
    const conditions = row.conditions.trim().toLowerCase();
    const key = JSON.stringify([row.paper_id ?? row.paper, paperOnly ? "" : conditions]);
    if (!pairs.has(key)) pairs.set(key, { key, paper: row, x: new Map(), y: new Map() });
    const axis = pairs.get(key)[row.group === x ? "x" : "y"];
    const candidate = JSON.stringify([
      row.originalValue, row.originalUnit, conditions, row.page, row.evidence,
    ]);
    if (!axis.has(candidate)) axis.set(candidate, row);
  }
  return [...pairs.values()].filter(pair => pair.x.size && pair.y.size);
}

function paperPDFURL(id) {
  return `/papers/${encodeURIComponent(id)}/source.pdf`;
}

function addSourcePageLink(parent, row, label) {
  const page = Number(row?.page);
  if (!row?.has_pdf || !Number.isSafeInteger(page) || page < 1) return false;
  const link = add(parent, "a", label);
  link.href = `/papers?paper=${encodeURIComponent(row.paper_id)}&page=${page}`;
  link.title = `View PDF page ${page} in the paper library`;
  return true;
}

function showPairSource(cell, row) {
  if (!row) return;
  if (row.evidence) {
    const detail = add(cell, "details");
    add(detail, "summary", "Show source");
    add(detail, "p", row.evidence);
  }
  addSourcePageLink(cell, row, `Open PDF page ${row.page}`);
}

function chooseValue(cell, pair, axis, rerender) {
  const options = pair[axis];
  if (options.size === 1) {
    const row = options.values().next().value;
    cell.textContent = pairLabel(row);
    showPairSource(cell, row);
    return row;
  }
  const key = JSON.stringify([xMetric.value, yMetric.value, matchPaperOnly.checked, pair.key, axis]);
  const picker = add(cell, "select", undefined, "pair-select");
  picker.setAttribute("aria-label", `${axis.toUpperCase()} value for ${paperName(pair.paper)}`);
  add(picker, "option", "Choose value").value = "";
  for (const [id, row] of options) {
    const source = row.evidence?.length > 65 ? row.evidence.slice(0, 62) + "…" : row.evidence;
    const option = add(picker, "option", [pairLabel(row), source].filter(Boolean).join(" · "));
    option.value = id;
    option.title = row.evidence;
  }
  const selected = pairChoices.get(key);
  picker.value = options.has(selected) ? selected : "";
  picker.addEventListener("change", () => {
    pairChoices.set(key, picker.value);
    rerender();
  });
  const row = options.get(picker.value);
  showPairSource(cell, row);
  return row;
}

function plotDomain(points, axis) {
  let min = Infinity, max = -Infinity;
  for (const point of points) {
    min = Math.min(min, point[axis].number);
    max = Math.max(max, point[axis].number);
  }
  const scale = Math.max(Math.abs(min), Math.abs(max)) || 1;
  const span = max / scale - min / scale;
  return {min, max, position: value => span ? 100 * (value / scale - min / scale) / span : 50};
}

function bestTradeoffs(points, xDirection, yDirection) {
  if (!xDirection || !yDirection) return new Set();
  const xWeight = xDirection === "low" ? -1 : 1;
  const yWeight = yDirection === "low" ? -1 : 1;
  const ranked = points.map(point => ({
    point, x: point.x.number * xWeight, y: point.y.number * yWeight,
  })).sort((first, second) => second.x - first.x || second.y - first.y);
  const frontier = new Set();
  let bestY = -Infinity;
  let xAtBestY = -Infinity;
  for (const {point, x, y} of ranked) {
    if (y > bestY) {
      bestY = y;
      xAtBestY = x;
    }
    if (y === bestY && x === xAtBestY) frontier.add(point);
  }
  return frontier;
}

function drawScatter(points, xLabel, yLabel, frontier) {
  const chart = element("scatter");
  const detail = element("point-detail");
  chart.replaceChildren();
  detail.textContent = "";
  if (!points.length) return;
  const x = plotDomain(points, "x");
  const y = plotDomain(points, "y");
  add(chart, "div", `${yLabel} · ${displayNumber.format(y.min)} to ${displayNumber.format(y.max)}`, "scatter-y");
  const area = add(add(chart, "div", undefined, "scatter-area"), "div", undefined, "scatter-points");
  for (const point of points) {
    const mark = frontier.has(point) ? " · Best trade-off" : "";
    const text = `${paperName(point.x)}${mark} · X: ${pairLabel(point.x)} · Y: ${pairLabel(point.y)}`;
    const marker = add(area, "button", undefined, "scatter-point");
    if (mark) marker.classList.add("tradeoff");
    marker.type = "button";
    marker.title = text;
    marker.setAttribute("aria-label", text);
    marker.style.left = `${x.position(point.x.number)}%`;
    marker.style.bottom = `${y.position(point.y.number)}%`;
    marker.addEventListener("click", () => { detail.textContent = text; });
  }
  const scale = add(chart, "div", undefined, "scatter-scale");
  add(scale, "span", displayNumber.format(x.min));
  add(scale, "strong", xLabel);
  add(scale, "span", displayNumber.format(x.max));
}

function renderPairs(rows) {
  const table = element("pair-rows");
  const message = element("pair-status");
  table.replaceChildren();
  const xLabel = xMetric.selectedOptions[0]?.textContent ?? "X";
  const yLabel = yMetric.selectedOptions[0]?.textContent ?? "Y";
  element("x-column").textContent = xLabel;
  element("y-column").textContent = yLabel;
  const pairs = pairCandidates(rows, xMetric.value, yMetric.value, matchPaperOnly.checked);
  const points = [];
  for (const pair of pairs) {
    const line = add(table, "tr");
    const heading = add(line, "th", undefined, "paper");
    heading.scope = "row";
    addPaperLabel(heading, pair.paper);
    add(line, "td", matchPaperOnly.checked ? "Shown with each value" : pair.paper.conditions || "Unspecified");
    const x = chooseValue(add(line, "td"), pair, "x", () => renderPairs(rows));
    const y = chooseValue(add(line, "td"), pair, "y", () => renderPairs(rows));
    if (x && y) points.push({ x, y, heading });
  }
  if (xMetric.value === yMetric.value) message.textContent = "Choose two different metrics.";
  else if (!pairs.length) message.textContent = matchPaperOnly.checked
    ? "No paper has both selected metrics under these filters."
    : "No paper has both metrics with matching conditions. Enable different conditions to compare across them.";
  else message.textContent = `Plotted ${points.length} of ${pairs.length} pair(s).${points.length < pairs.length ? " Choose values in the table for the remaining pairs." : ""}`;
  plottedPairs = points;
  exportPairsButton.disabled = points.length === 0;
  const frontier = bestTradeoffs(points, xPreference.value, yPreference.value);
  for (const point of frontier) add(point.heading, "span", "Best trade-off", "tradeoff-label");
  drawScatter(points, xLabel, yLabel, frontier);
}

for (const control of [xMetric, yMetric, matchPaperOnly]) {
  control.addEventListener("change", () => {
    saveComparisonSettings();
    render();
  });
}

for (const preference of [xPreference, yPreference]) preference.addEventListener("change", render);

for (const control of [group, paper, conditions, sort]) {
  control.addEventListener("input", render);
}
