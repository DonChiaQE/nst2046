"use strict";
// Replay UI. Loads one recording's whole timeline, then scrubs through it locally; every decision about events and
// conflicts was made server-side, so this file only renders. Served by atcdb/api.py.

const PLAY_MS = 2000;
const ROLE = { controller: "CTL", pilot: "PLT", mixed: "MIX", unknown: "???" };
const $ = (id) => document.getElementById(id);
const ui = { timeline: null, k: 0, timer: null, wanted: new URLSearchParams(location.search).get("recording") };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function option(value, label) {
  const o = el("option", null, label);
  o.value = value;
  return o;
}

function mmss(seconds) {
  const t = Math.floor(seconds);
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

function setStatus(text) {
  $("status").textContent = text;
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(`${response.status} ${body.detail || response.statusText}`);
  }
  return response.json();
}

async function init() {
  const caps = await getJSON("/api/capabilities");
  for (const p of caps.parsers) $("parser").append(option(p.name, `${p.name} (${p.model} ${p.model_version})`));
  for (const c of caps.contexts) $("context").append(option(c, c));
  for (const kind of Object.keys(caps.transcripts)) $("transcript").append(option(kind, kind));
  $("context").value = "window";
  $("transcript").value = "gold";

  $("recording").addEventListener("change", loadReplay);
  $("parser").addEventListener("change", loadReplay);
  $("context").addEventListener("change", loadReplay);
  $("transcript").addEventListener("change", loadRecordings);
  $("first").addEventListener("click", () => jump(0));
  $("prev").addEventListener("click", () => jump(ui.k - 1));
  $("next").addEventListener("click", () => jump(ui.k + 1));
  $("last").addEventListener("click", () => jump(Infinity));
  $("play").addEventListener("click", togglePlay);
  $("scrub").addEventListener("input", () => jump(Number($("scrub").value)));
  document.addEventListener("keydown", (event) => {
    if (event.target instanceof Element && event.target.closest("select, input")) return;   // controls keep their arrows
    if (event.key === "ArrowRight") jump(ui.k + 1);
    else if (event.key === "ArrowLeft") jump(ui.k - 1);
    else return;
    event.preventDefault();
  });
  await loadRecordings();
}

async function loadRecordings() {
  let recordings;
  try {
    recordings = await getJSON(`/api/recordings?transcript=${encodeURIComponent($("transcript").value)}`);
  } catch (error) {
    $("recording").replaceChildren();
    await loadReplay();   // nothing selected: clears the board, feed and conflicts
    setStatus(`Could not load the recording list: ${error.message}`);
    return;
  }
  const select = $("recording");
  const previous = ui.wanted || select.value;
  ui.wanted = null;
  select.replaceChildren(...recordings.map((r) =>
    option(r.id, `${r.external_id} (${r.n_transmissions} tx)`)));
  if (recordings.some((r) => String(r.id) === previous)) select.value = previous;
  if (!recordings.length) setStatus("No replayable recordings for this transcript kind.");
  await loadReplay();
}

async function loadReplay() {
  stop();
  const id = $("recording").value;
  ui.timeline = null;
  ui.k = 0;
  if (id) {
    const query = new URLSearchParams({ parser: $("parser").value, context: $("context").value, transcript: $("transcript").value });
    setStatus("Loading…");
    try {
      ui.timeline = await getJSON(`/api/recordings/${id}/replay?${query}`);
      setStatus(ui.timeline.steps.length ? "" : "This recording has no transcripts of that kind.");
      history.replaceState(null, "", `?recording=${id}`);
    } catch (error) {
      setStatus(`Could not load the replay: ${error.message}`);
    }
  }
  render();
}

function jump(k) {
  stop();
  go(k);
}

function go(k) {
  const n = ui.timeline ? ui.timeline.steps.length : 0;
  if (!n) return;
  ui.k = Math.max(0, Math.min(n - 1, k));
  render();
}

function togglePlay() {
  if (ui.timer) return stop();
  const last = ui.timeline.steps.length - 1;
  if (ui.k >= last) go(0);
  ui.timer = setInterval(() => (ui.k >= ui.timeline.steps.length - 1 ? stop() : go(ui.k + 1)), PLAY_MS);
  $("play").textContent = "Pause";
}

function stop() {
  clearInterval(ui.timer);
  ui.timer = null;
  $("play").textContent = "Play";
}

function playClip(transmissionId) {
  const audio = $("audio");
  audio.src = `/api/clips/${transmissionId}`;
  audio.play().catch(() => setStatus("No audio clip for that transmission."));
}

function render() {
  const steps = ui.timeline ? ui.timeline.steps : [];
  const n = steps.length;
  $("scrub").max = Math.max(n - 1, 0);
  $("scrub").value = ui.k;
  $("position").textContent = n ? `${ui.k + 1} / ${n}` : "0 / 0";
  for (const id of ["first", "prev", "play", "next", "last", "scrub"]) $(id).disabled = n === 0;
  if (!n) {
    for (const id of ["board", "feed", "conflicts"]) $(id).replaceChildren();
    $("banner").hidden = true;
    return;
  }
  const step = steps[ui.k];
  renderBanner(step);   // before the feed: the banner changes the feed's height, and the feed scrolls to the current step
  renderBoard(ui.timeline.runways, step);
  renderConflicts(steps);
  renderFeed(steps);
}

function worstSeverity(conflicts) {
  const severities = conflicts.map((c) => c.severity);
  return severities.includes("alert") ? "alert" : severities.includes("warning") ? "warning" : "";
}

function renderBoard(runways, step) {
  const cards = runways.map((runway) => {
    const card = el("div", `card ${worstSeverity(step.conflicts.filter((c) => c.runway === runway))}`.trim());
    card.append(el("h3", null, `Runway ${runway}`));
    const list = el("ul");
    for (const r of step.board[runway] || []) {
      list.append(el("li", `res ${r.kind.toLowerCase()}`, `${r.callsign || "unidentified"} · ${r.kind}`));
    }
    for (const a of step.aircraft.filter((a) => a.holding_short === runway)) {
      list.append(el("li", "hold", `${a.callsign} · holding short`));
    }
    if (!list.children.length) list.append(el("li", "idle", "clear"));
    card.append(list);
    return card;
  });
  $("board").replaceChildren(...cards);
  if (!cards.length) $("board").append(el("p", "idle", "No runway is named in this recording."));
}

function eventLabel(e) {
  return [e.kind, e.callsign || "?", e.runway || e.to || ""].join(" ").trim();
}

function renderFeed(steps) {
  const items = steps.slice(0, ui.k + 1).map((s, i) => {
    const item = el("li", i === ui.k ? "tx current" : "tx");
    const head = el("div", "tx-head");
    const clip = el("button", "clip", "♪");
    clip.type = "button";
    clip.title = "Play clip";
    clip.addEventListener("click", (event) => {
      event.stopPropagation();
      playClip(s.transmission.id);
    });
    head.append(el("span", "time", mmss(s.transmission.start_s)),
      el("span", `role ${s.transmission.role}`, ROLE[s.transmission.role] || "???"),
      el("span", "text", s.transmission.text), clip);
    item.append(head);
    const chips = el("div", "chips");
    for (const e of s.events) if (e.kind !== "NOOP") chips.append(el("span", `chip ${e.kind.toLowerCase()}`, eventLabel(e)));
    for (const c of s.conflicts) chips.append(el("span", `chip flag ${c.severity}`, `${c.severity} · ${c.type.toLowerCase()}`));
    if (s.error) chips.append(el("span", "chip failed", `parse error: ${s.error}`));
    if (chips.children.length) item.append(chips);
    item.addEventListener("click", () => jump(i));
    return item;
  });
  $("feed").replaceChildren(...items);
  items[items.length - 1].scrollIntoView({ block: "nearest" });
}

function renderConflicts(steps) {
  const items = [];
  steps.slice(0, ui.k + 1).forEach((s, i) => {
    for (const c of s.conflicts) {
      const item = el("li", `conflict ${c.severity}`);
      item.append(el("span", "time", mmss(s.transmission.start_s)), el("span", "sev", c.severity), el("span", null, c.explanation));
      item.addEventListener("click", () => jump(i));
      items.push(item);
    }
  });
  $("conflicts").replaceChildren(...items);
  if (!items.length) $("conflicts").append(el("li", "idle", "None yet."));
}

function renderBanner(step) {
  const banner = $("banner");
  banner.hidden = !step.conflicts.length;
  if (banner.hidden) return;
  banner.className = `banner ${worstSeverity(step.conflicts)}`;
  banner.replaceChildren(...step.conflicts.map((c) => el("p", null, `${c.severity.toUpperCase()} · ${c.type}: ${c.explanation}`)));
}

init().catch((error) => setStatus(`Could not start: ${error.message}`));
