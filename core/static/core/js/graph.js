/*
 * CivicVault — relationship graph.
 *
 * A dependency-free force-directed layout in SVG. No d3, no CDN: a civic tool
 * shouldn't phone home to render the public record. The dataset is small (tens
 * of nodes), so an O(n^2) charge pass is comfortably fast and the code stays
 * legible. Progressive enhancement: the server ships an accessible list; this
 * script reveals the interactive stage and wires up pan/zoom/select.
 */
(() => {
  "use strict";

  const dataEl = document.getElementById("graph-data");
  const stage = document.querySelector("[data-graph-stage]");
  if (!dataEl || !stage) return;

  let DATA;
  try {
    DATA = JSON.parse(dataEl.textContent);
  } catch (_) {
    return; // leave the static fallback in place
  }
  if (!DATA.nodes || !DATA.nodes.length) return;

  const SVGNS = "http://www.w3.org/2000/svg";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Visual vocabulary (mirrors GRAPH_TYPES in views.py) -----------------
  const TYPE = {
    jurisdiction: { label: "Jurisdiction", shape: "hexagon", hue: 90, r: 26 },
    body: { label: "Body", shape: "square", hue: 305, r: 22 },
    vendor: { label: "Vendor", shape: "square", hue: 245, r: 17 },
    person: { label: "Person", shape: "circle", hue: 25, r: 13 },
  };
  const typeOf = (n) => TYPE[n.type] || { label: n.type, shape: "circle", hue: 0, r: 12 };

  // ---- Simulation tunables -------------------------------------------------
  const REPEL = 11000; // charge: pairwise repulsion magnitude
  const SPRING = 0.045; // link stiffness
  const CENTER = 0.015; // gravity toward origin (keeps it from drifting)
  const FRICTION = 0.62; // velocity retained per tick (1 - velocityDecay)
  const ALPHA_DECAY = 0.02;
  const ALPHA_MIN = 0.004;

  // ---- Model ---------------------------------------------------------------
  const nodes = DATA.nodes.map((n, i) => {
    const t = typeOf(n);
    // seed on a ring so the first frame isn't a singularity
    const a = (i / DATA.nodes.length) * Math.PI * 2;
    return {
      ...n,
      r: t.r,
      x: Math.cos(a) * 240 + (i % 3) * 8,
      y: Math.sin(a) * 240 + (i % 2) * 8,
      vx: 0,
      vy: 0,
      fx: null,
      fy: null,
    };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = DATA.edges
    .map((e) => ({ ...e, source: byId.get(e.source), target: byId.get(e.target) }))
    .filter((e) => e.source && e.target);

  // adjacency for the rail's "connections" list
  const neighbors = new Map(nodes.map((n) => [n.id, []]));
  links.forEach((l) => {
    neighbors.get(l.source.id).push({ node: l.target, label: l.label, dir: "out", edge: l });
    neighbors.get(l.target.id).push({ node: l.source, label: l.label, dir: "in", edge: l });
  });

  // ---- SVG scaffold --------------------------------------------------------
  const svg = stage.querySelector("[data-graph-canvas]");

  // arrowhead marker; fill: context-stroke makes it match each edge's own colour
  // (including cyan when active), so direction reads without a second legend.
  const defs = document.createElementNS(SVGNS, "defs");
  const marker = document.createElementNS(SVGNS, "marker");
  marker.setAttribute("id", "gv-arrow");
  marker.setAttribute("viewBox", "0 0 10 10");
  marker.setAttribute("refX", "9");
  marker.setAttribute("refY", "5");
  marker.setAttribute("markerWidth", "6");
  marker.setAttribute("markerHeight", "6");
  marker.setAttribute("orient", "auto-start-reverse");
  const arrow = document.createElementNS(SVGNS, "path");
  arrow.setAttribute("d", "M0,0 L10,5 L0,10 z");
  arrow.setAttribute("fill", "context-stroke");
  marker.appendChild(arrow);
  defs.appendChild(marker);
  svg.appendChild(defs);

  const gEdges = document.createElementNS(SVGNS, "g");
  const gEdgeHit = document.createElementNS(SVGNS, "g"); // fat transparent click targets
  const gEdgeLabels = document.createElementNS(SVGNS, "g");
  const gNodes = document.createElementNS(SVGNS, "g");
  gEdges.setAttribute("class", "g-edges");
  gEdgeHit.setAttribute("class", "g-edgehits");
  gEdgeLabels.setAttribute("class", "g-edgelabels");
  gNodes.setAttribute("class", "g-nodes");
  svg.append(gEdges, gEdgeHit, gEdgeLabels, gNodes);

  function shapeEl(type, r) {
    const t = TYPE[type] || {};
    switch (t.shape) {
      case "square": {
        const el = document.createElementNS(SVGNS, "rect");
        el.setAttribute("x", -r);
        el.setAttribute("y", -r);
        el.setAttribute("width", r * 2);
        el.setAttribute("height", r * 2);
        el.setAttribute("rx", 3);
        return el;
      }
      case "diamond": {
        const el = document.createElementNS(SVGNS, "polygon");
        el.setAttribute("points", `0,${-r} ${r},0 0,${r} ${-r},0`);
        return el;
      }
      case "hexagon": {
        const pts = [];
        for (let k = 0; k < 6; k++) {
          const ang = (Math.PI / 3) * k - Math.PI / 6;
          pts.push(`${(Math.cos(ang) * r).toFixed(1)},${(Math.sin(ang) * r).toFixed(1)}`);
        }
        const el = document.createElementNS(SVGNS, "polygon");
        el.setAttribute("points", pts.join(" "));
        return el;
      }
      default: {
        const el = document.createElementNS(SVGNS, "circle");
        el.setAttribute("r", r);
        return el;
      }
    }
  }

  // Build edge DOM: a thin visible line + a fat transparent line for easy clicking.
  links.forEach((l) => {
    const line = document.createElementNS(SVGNS, "line");
    line.setAttribute("class", `g-edge g-edge--${l.kind}`);
    line.setAttribute("marker-end", "url(#gv-arrow)");
    gEdges.appendChild(line);
    l.el = line;

    const hit = document.createElementNS(SVGNS, "line");
    hit.setAttribute("class", "g-edge-hit");
    hit.__link = l;
    gEdgeHit.appendChild(hit);
    l.hit = hit;
  });

  nodes.forEach((n) => {
    const t = typeOf(n);
    const g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", `gnode gnode--${n.type}`);
    g.dataset.id = n.id;
    g.setAttribute("tabindex", "0");
    g.setAttribute("role", "button");
    g.setAttribute(
      "aria-label",
      `${t.label}: ${n.label}. ${neighbors.get(n.id).length} connections. Activate to open details.`
    );
    g.style.setProperty("--c", `oklch(74% 0.135 ${t.hue})`);
    g.style.setProperty("--c-soft", `oklch(74% 0.135 ${t.hue} / 0.16)`);

    const shape = shapeEl(n.type, n.r);
    shape.setAttribute("class", "gnode__shape");

    const label = document.createElementNS(SVGNS, "text");
    label.setAttribute("class", "gnode__label");
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("y", n.r + 15);
    label.textContent = n.label;

    g.append(shape, label);
    gNodes.appendChild(g);
    n.el = g;

    g.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        select(n, true);
      }
    });
    g.addEventListener("focus", () => hover(n));
    g.addEventListener("blur", () => hover(null));
  });

  // ---- Force tick ----------------------------------------------------------
  let alpha = reduceMotion ? 0 : 1;

  function tick() {
    // charge (pairwise repulsion)
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) {
          dx = (Math.random() - 0.5) * 0.1;
          dy = (Math.random() - 0.5) * 0.1;
          d2 = dx * dx + dy * dy + 0.01;
        }
        const f = (REPEL * alpha) / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        a.vx -= fx;
        a.vy -= fy;
        b.vx += fx;
        b.vy += fy;
      }
    }
    // links (springs) + soft collision built into target distance
    links.forEach((l) => {
      const dx = l.target.x - l.source.x;
      const dy = l.target.y - l.source.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const want = l.source.r + l.target.r + 78;
      const f = (d - want) * SPRING * alpha;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      l.source.vx += fx;
      l.source.vy += fy;
      l.target.vx -= fx;
      l.target.vy -= fy;
    });
    // gravity toward origin + integrate
    nodes.forEach((n) => {
      if (n.fx != null) {
        n.x = n.fx;
        n.y = n.fy;
        n.vx = n.vy = 0;
        return;
      }
      n.vx -= n.x * CENTER * alpha;
      n.vy -= n.y * CENTER * alpha;
      n.vx *= FRICTION;
      n.vy *= FRICTION;
      n.x += n.vx;
      n.y += n.vy;
    });
    alpha *= 1 - ALPHA_DECAY;
  }

  function render() {
    links.forEach((l) => {
      // hit-line spans the full centre-to-centre length (easy to click)
      l.hit.setAttribute("x1", l.source.x);
      l.hit.setAttribute("y1", l.source.y);
      l.hit.setAttribute("x2", l.target.x);
      l.hit.setAttribute("y2", l.target.y);
      // visible line stops at the target's edge so its arrowhead is visible
      const dx = l.target.x - l.source.x;
      const dy = l.target.y - l.source.y;
      const dist = Math.hypot(dx, dy) || 1;
      l.el.setAttribute("x1", l.source.x);
      l.el.setAttribute("y1", l.source.y);
      l.el.setAttribute("x2", l.target.x - (dx / dist) * (l.target.r + 7));
      l.el.setAttribute("y2", l.target.y - (dy / dist) * (l.target.r + 7));
    });
    nodes.forEach((n) => {
      n.el.setAttribute("transform", `translate(${n.x.toFixed(2)} ${n.y.toFixed(2)})`);
    });
    positionActiveEdgeLabels();
  }

  // ---- Viewport (viewBox pan/zoom) ----------------------------------------
  const view = { x: -400, y: -300, w: 800, h: 600 };
  function applyView() {
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  }
  function fitView() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach((n) => {
      minX = Math.min(minX, n.x - n.r);
      minY = Math.min(minY, n.y - n.r);
      maxX = Math.max(maxX, n.x + n.r);
      maxY = Math.max(maxY, n.y + n.r);
    });
    const pad = 70;
    const w = Math.max(maxX - minX + pad * 2, 320);
    const h = Math.max(maxY - minY + pad * 2, 240);
    const rect = svg.getBoundingClientRect();
    const aspect = rect.width / rect.height || 1.4;
    // expand the shorter axis so the graph isn't distorted
    let vw = w, vh = h;
    if (w / h > aspect) vh = w / aspect;
    else vw = h * aspect;
    view.w = vw;
    view.h = vh;
    view.x = (minX + maxX) / 2 - vw / 2;
    view.y = (minY + maxY) / 2 - vh / 2;
    applyView();
  }

  function clientToWorld(clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    return {
      x: view.x + ((clientX - rect.left) / rect.width) * view.w,
      y: view.y + ((clientY - rect.top) / rect.height) * view.h,
    };
  }

  // wheel zoom toward cursor
  svg.addEventListener(
    "wheel",
    (ev) => {
      ev.preventDefault();
      const before = clientToWorld(ev.clientX, ev.clientY);
      const k = ev.deltaY > 0 ? 1.12 : 1 / 1.12;
      view.w = Math.min(Math.max(view.w * k, 120), 6000);
      view.h = Math.min(Math.max(view.h * k, 90), 4500);
      const after = clientToWorld(ev.clientX, ev.clientY);
      view.x += before.x - after.x;
      view.y += before.y - after.y;
      applyView();
    },
    { passive: false }
  );

  // ---- Pointer: pan background, drag nodes, click edges -------------------
  let drag = null; // {node|edge|null, sx, sy, moved, mod}
  svg.addEventListener("pointerdown", (ev) => {
    const nodeG = ev.target.closest(".gnode");
    if (nodeG) {
      const n = byId.get(nodeG.dataset.id) || nodes.find((x) => x.el === nodeG);
      const mod = ev.shiftKey || ev.metaKey || ev.ctrlKey;
      drag = { node: n, sx: ev.clientX, sy: ev.clientY, moved: false, mod };
      n.fx = n.x;
      n.fy = n.y;
    } else {
      const hitEl = ev.target.closest(".g-edge-hit");
      if (hitEl && hitEl.__link) {
        drag = { edge: hitEl.__link, sx: ev.clientX, sy: ev.clientY, moved: false };
      } else {
        drag = { node: null, sx: ev.clientX, sy: ev.clientY, vx: view.x, vy: view.y, moved: false };
      }
    }
    svg.setPointerCapture(ev.pointerId);
    svg.classList.add("is-grabbing");
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    if (Math.abs(ev.clientX - drag.sx) + Math.abs(ev.clientY - drag.sy) > 3) drag.moved = true;
    if (drag.node) {
      const w = clientToWorld(ev.clientX, ev.clientY);
      drag.node.fx = w.x;
      drag.node.fy = w.y;
      reheat(0.3);
    } else if (!drag.edge) {
      const rect = svg.getBoundingClientRect();
      view.x = drag.vx - ((ev.clientX - drag.sx) / rect.width) * view.w;
      view.y = drag.vy - ((ev.clientY - drag.sy) / rect.height) * view.h;
      applyView();
    }
  });
  function endDrag(ev) {
    if (!drag) return;
    svg.classList.remove("is-grabbing");
    if (drag.node) {
      drag.node.fx = null;
      drag.node.fy = null;
      if (!drag.moved) {
        const n = drag.node;
        // modifier-click a second node: open the relationship if one exists
        if (drag.mod && selected && selected.id !== n.id) {
          const e = edgeBetween(selected, n);
          if (e) selectEdge(e);
          else select(n, false);
        } else {
          select(n, false);
        }
      }
    } else if (drag.edge && !drag.moved) {
      selectEdge(drag.edge);
    }
    drag = null;
    if (ev && ev.pointerId != null) {
      try {
        svg.releasePointerCapture(ev.pointerId);
      } catch (_) {}
    }
  }
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  // ---- Selection + hover + the detail rail --------------------------------
  const rail = stage.querySelector("[data-graph-rail]");
  const railEmptyHTML = rail.innerHTML; // restored when a selection is cleared
  let selected = null; // selected node (single-entity view)
  let selectedEdge = null; // selected edge (person<->body relationship view)
  let hovered = null;

  const edgeBetween = (a, b) =>
    links.find(
      (l) =>
        (l.source.id === a.id && l.target.id === b.id) ||
        (l.source.id === b.id && l.target.id === a.id)
    );

  // Interaction state shared by selection, type filters, and search. One
  // refresh() owns every is-* class so the three inputs never stomp each other.
  let searchQuery = "";
  const hiddenTypes = new Set();
  let selectedYear = null; // int year, or null for "All"
  const neighborIdSet = (n) => new Set(neighbors.get(n.id).map((x) => x.node.id));
  const nodeMatches = (n, q) => !q || n.label.toLowerCase().includes(q);

  // ---- Year filter ---------------------------------------------------------
  // Edges split by their relationship to time: PERSON<->BODY and BODY<->VENDOR
  // ties carry the years they happened ("dated"); BODY<->JURISDICTION ("sits in")
  // is structural scaffolding with no year of its own.
  const isStructural = (l) => l.kind === "in";

  // Which nodes survive the selected year. People and vendors stay only if a
  // dated edge of theirs is active that year; bodies/jurisdictions are scaffolding
  // that stays if anything *below* them is active (a body keeps its jurisdiction).
  // Returns null when no year is selected (= everything visible).
  function liveNodeIds() {
    if (selectedYear == null) return null;
    const live = new Set();
    links.forEach((l) => {
      if (!isStructural(l) && l.years && l.years.includes(selectedYear)) {
        live.add(l.source.id);
        live.add(l.target.id);
      }
    });
    // Flow scaffolding upward only (body -> jurisdiction), to a fixpoint. A live
    // jurisdiction never resurrects a body that had no activity that year.
    let changed = true;
    while (changed) {
      changed = false;
      links.forEach((l) => {
        if (isStructural(l) && live.has(l.source.id) && !live.has(l.target.id)) {
          live.add(l.target.id);
          changed = true;
        }
      });
    }
    return live;
  }

  const nodeYearVisible = (n, live) => live == null || live.has(n.id);
  function edgeYearVisible(l, live) {
    if (live == null) return true;
    if (isStructural(l)) return live.has(l.source.id) && live.has(l.target.id);
    return !!(l.years && l.years.includes(selectedYear));
  }

  // The edge re-scoped to the selected year: rows trimmed to that year, and the
  // label / summary / dollar total recomputed so the rail never shows "3 meetings"
  // while displaying only the one that fell in the chosen year.
  function edgeView(l) {
    const rows = l.rows || [];
    if (selectedYear == null || isStructural(l) || !l.years) {
      return { rows, label: l.label, summary: l.summary, count: rows.length };
    }
    const scoped = rows.filter((r) => r.year === selectedYear);
    const n = scoped.length;
    if (l.kind === "contracts_with") {
      const total = scoped.reduce((s, r) => s + (r.amt || 0), 0);
      const money = total ? "$" + Math.round(total).toLocaleString("en-US") : "";
      let summary = `${n} contract${n === 1 ? "" : "s"}`;
      if (money) summary += ` · ${money}`;
      return { rows: scoped, label: money || summary, summary, count: n };
    }
    const label = l.kind === "board_member" ? "board member" : `${n} meeting${n === 1 ? "" : "s"}`;
    return { rows: scoped, label, summary: `${n} shared meeting${n === 1 ? "" : "s"}`, count: n };
  }

  function refresh() {
    const q = searchQuery.trim().toLowerCase();
    const live = liveNodeIds();
    let visibleMatches = 0;

    // Which nodes/edges stay bright is driven by the current selection context:
    // an edge selection lights its two endpoints; a node selection lights it +
    // its neighbours; search overrides both with match dimming.
    const highlight = selectedEdge
      ? new Set([selectedEdge.source.id, selectedEdge.target.id])
      : selected
        ? new Set([selected.id, ...neighborIdSet(selected)])
        : null;

    nodes.forEach((n) => {
      const vis = !hiddenTypes.has(n.type) && nodeYearVisible(n, live);
      const match = nodeMatches(n, q);
      const isSel =
        (!!selected && n.id === selected.id) ||
        (!!selectedEdge && (n.id === selectedEdge.source.id || n.id === selectedEdge.target.id));
      n.el.classList.toggle("is-filtered", !vis);
      let dim = false;
      if (q) dim = vis && !match;
      else if (highlight) dim = !highlight.has(n.id);
      n.el.classList.toggle("is-dim", dim && !isSel);
      n.el.classList.toggle("is-selected", isSel);
      n.el.classList.toggle("is-match", !!(q && match && vis && !isSel));
      if (vis && match) visibleMatches++;
    });

    links.forEach((l) => {
      const vis =
        !hiddenTypes.has(l.source.type) &&
        !hiddenTypes.has(l.target.type) &&
        edgeYearVisible(l, live);
      l.el.classList.toggle("is-filtered", !vis);
      if (l.hit) l.hit.classList.toggle("is-filtered", !vis);
      let active = false;
      let dim = false;
      if (q) {
        dim = !(nodeMatches(l.source, q) && nodeMatches(l.target, q));
      } else if (selectedEdge) {
        active = l === selectedEdge;
        dim = !active;
      } else if (selected) {
        active = l.source.id === selected.id || l.target.id === selected.id;
        dim = !active;
      }
      l.el.classList.toggle("is-active", active);
      l.el.classList.toggle("is-dim", dim);
    });

    renderActiveEdgeLabels(q);
    updateSearchFeedback(q, visibleMatches);
    refreshList(q, live);
  }

  // Show the "N meetings" label on whichever edges are active (the selected edge,
  // or every edge touching a selected node) — never while searching.
  function renderActiveEdgeLabels(q) {
    gEdgeLabels.replaceChildren();
    links.forEach((l) => {
      l.labelEl = null;
    });
    if (q) return;
    let active = [];
    if (selectedEdge) active = [selectedEdge];
    else if (selected)
      active = links.filter((l) => l.source.id === selected.id || l.target.id === selected.id);
    active.forEach((l) => {
      const text = edgeView(l).label;
      if (!text) return;
      const t = document.createElementNS(SVGNS, "text");
      t.setAttribute("class", "g-edgelabel");
      t.setAttribute("text-anchor", "middle");
      t.textContent = text;
      gEdgeLabels.appendChild(t);
      l.labelEl = t;
    });
    positionActiveEdgeLabels();
  }
  function positionActiveEdgeLabels() {
    links.forEach((l) => {
      if (!l.labelEl) return;
      l.labelEl.setAttribute("x", (l.source.x + l.target.x) / 2);
      l.labelEl.setAttribute("y", (l.source.y + l.target.y) / 2 - 5);
    });
  }

  function hover(n) {
    if (hovered === n) return;
    if (hovered) hovered.el.classList.remove("is-hover");
    hovered = n;
    if (hovered) hovered.el.classList.add("is-hover");
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function railHTML(n) {
    const t = typeOf(n);
    const conns = neighbors.get(n.id);
    const stats = (n.stats || [])
      .map(
        (s) =>
          `<div class="gr-stat"><dt>${esc(s[0])}</dt><dd class="mono">${esc(s[1])}</dd></div>`
      )
      .join("");
    const docs = (n.docs || [])
      .map((d) =>
        d.href
          ? `<li><a href="${esc(d.href)}" target="_blank" rel="noopener">${esc(d.title)} <span aria-hidden="true">↗</span></a></li>`
          : `<li><span>${esc(d.title)}</span></li>`
      )
      .join("");
    // Under a year filter, hide connections that fall outside it, and relabel the
    // rest to that year ("2 meetings", not the all-time count).
    const live = liveNodeIds();
    const visConns = conns.filter((c) => {
      if (!nodeYearVisible(c.node, live)) return false;
      if (selectedYear != null && c.edge && !isStructural(c.edge)) {
        return edgeView(c.edge).count > 0;
      }
      return true;
    });
    // A connection whose edge carries meetings opens the relationship view; a
    // structural one (body -> jurisdiction) just navigates to the neighbour.
    const connItems = visConns
      .map((c) => {
        const ev = c.edge ? edgeView(c.edge) : null;
        const hasDetail = ev && ev.rows.length;
        return `<li><button type="button" class="gr-conn" data-conn="${esc(c.node.id)}">
             <span class="gr-conn__rel mono">${esc(ev ? ev.label : c.label)}</span>
             <span class="gr-conn__name">${esc(c.node.label)}</span>
             ${hasDetail ? '<span class="gr-conn__go" aria-hidden="true">→</span>' : ""}
           </button></li>`;
      })
      .join("");
    const connTitle = n.type === "person" ? "Bodies" : "Connections";

    return `
      <div class="gr-head" style="--c: oklch(74% 0.135 ${t.hue});">
        <span class="gr-type"><span class="gr-type__dot gfilter__swatch--${t.shape}"></span>${esc(t.label)}</span>
        <h2 class="gr-name">${esc(n.label)}</h2>
        ${n.sublabel && n.sublabel !== t.label ? `<p class="gr-sub">${esc(n.sublabel)}</p>` : ""}
      </div>
      ${stats ? `<dl class="gr-stats">${stats}</dl>` : ""}
      ${docs ? `<div class="gr-block"><h3 class="gr-block__title">Source documents</h3><ul class="gr-docs">${docs}</ul></div>` : ""}
      ${connItems ? `<div class="gr-block"><h3 class="gr-block__title">${connTitle} <span class="mono">${visConns.length}</span></h3><ul class="gr-conns">${connItems}</ul></div>` : ""}
      ${n.href ? `<a class="gr-cta" href="${esc(n.href)}">Follow to the record <span aria-hidden="true">↗</span></a>` : ""}
    `;
  }

  // The relationship view: the evidence (meetings or contracts) that ties two
  // entities together — driven by the edge's generic summary + rows payload.
  function relationshipHTML(edge) {
    const a = edge.source;
    const b = edge.target;
    const view = edgeView(edge);
    const data = view.rows;
    const scope = selectedYear != null && !isStructural(edge) ? ` in ${selectedYear}` : "";
    const rows = data
      .map(
        (m) =>
          `<li class="gr-mt">
             <span class="gr-mt__date mono">${esc(m.label)}</span>
             ${m.sub ? `<span class="gr-mt__sub">${esc(m.sub)}</span>` : ""}
             <span class="gr-mt__note">${esc(m.note)}</span>
           </li>`
      )
      .join("");
    const body = data.length
      ? `<div class="gr-block">
           <h3 class="gr-block__title">${esc((view.summary || `${data.length} items`) + scope)}</h3>
           <ul class="gr-mts">${rows}</ul>
         </div>`
      : `<p class="gr-sub">${esc(view.label || "Connected")}.</p>`;
    return `
      <div class="gr-head gr-head--rel">
        <span class="gr-type">Relationship</span>
        <h2 class="gr-rel">
          <span class="gr-rel__a">${esc(a.label)}</span>
          <span class="gr-rel__x" aria-hidden="true">⇄</span>
          <span class="gr-rel__b">${esc(b.label)}</span>
        </h2>
      </div>
      ${body}
      <div class="gr-rel__actions">
        <button type="button" class="gr-pill" data-goto="${esc(a.id)}">Open ${esc(a.label)}</button>
        <button type="button" class="gr-pill" data-goto="${esc(b.id)}">Open ${esc(b.label)}</button>
      </div>
    `;
  }

  // Wire the rail's buttons after each (re)render: data-goto selects a node,
  // data-conn opens the relationship if it has meetings, else navigates.
  function wireRailButtons() {
    rail.querySelectorAll("[data-goto]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const t = byId.get(btn.dataset.goto);
        if (t) {
          select(t, true);
          centerOn(t);
          t.el.focus();
        }
      });
    });
    rail.querySelectorAll("[data-conn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const neighbor = byId.get(btn.dataset.conn);
        if (!neighbor || !selected) return;
        const edge = edgeBetween(selected, neighbor);
        if (edge && edge.rows && edge.rows.length) {
          selectEdge(edge);
        } else {
          select(neighbor, true);
          centerOn(neighbor);
          neighbor.el.focus();
        }
      });
    });
  }

  function select(n, fromKeyboard) {
    selected = n;
    selectedEdge = null;
    rail.innerHTML = railHTML(n);
    rail.classList.add("is-filled");
    refresh();
    wireRailButtons();
    if (fromKeyboard) {
      const h = rail.querySelector(".gr-name");
      if (h) h.setAttribute("tabindex", "-1");
    }
  }

  function selectEdge(edge) {
    selected = null;
    selectedEdge = edge;
    rail.innerHTML = relationshipHTML(edge);
    rail.classList.add("is-filled");
    refresh();
    wireRailButtons();
  }

  function clearSelection() {
    selected = null;
    selectedEdge = null;
    rail.innerHTML = railEmptyHTML;
    rail.classList.remove("is-filled");
  }

  function centerOn(n) {
    view.x = n.x - view.w / 2;
    view.y = n.y - view.h / 2;
    applyView();
  }

  function reheat(a) {
    if (reduceMotion) return;
    alpha = Math.max(alpha, a);
    if (!running) loop();
  }

  // ---- Run loop ------------------------------------------------------------
  let running = false;
  function loop() {
    running = true;
    const step = () => {
      tick();
      render();
      if (alpha > ALPHA_MIN) {
        requestAnimationFrame(step);
      } else {
        running = false;
      }
    };
    requestAnimationFrame(step);
  }

  // ---- Search, list filtering, type filters, view toggle ------------------
  const fallback = document.querySelector("[data-graph-fallback]");
  const listEmptyEl = fallback ? fallback.querySelector("[data-list-empty]") : null;
  const searchInput = document.getElementById("graph-q");
  const countEl = document.getElementById("graph-q-count");
  const clearBtn = document.querySelector("[data-graph-clear]");
  const searchEmptyEl = stage.querySelector("[data-graph-empty-search]");

  function updateSearchFeedback(q, count) {
    if (countEl) {
      countEl.textContent = q
        ? count === 0
          ? "No matches"
          : `${count} ${count === 1 ? "match" : "matches"}`
        : "";
    }
    if (clearBtn) clearBtn.hidden = !q;
    if (searchEmptyEl) searchEmptyEl.hidden = !(q && count === 0);
  }

  // Mirror the graph's filter + search onto the no-JS list so both views agree.
  function refreshList(q, live) {
    if (!fallback) return;
    fallback.querySelectorAll("[data-node-id]").forEach((el) => {
      const vis =
        !hiddenTypes.has(el.dataset.type) &&
        (live == null || live.has(el.dataset.nodeId)) &&
        (!q || (el.dataset.search || "").includes(q));
      el.classList.toggle("is-hidden", !vis);
    });
    fallback.querySelectorAll("[data-edge]").forEach((el) => {
      const yrs = (el.dataset.years || "").split(" ").filter(Boolean);
      let yearVis = true;
      if (live != null) {
        // dated edges match on their own years; structural ties ride their
        // endpoints' visibility, exactly as the graph does.
        yearVis = yrs.length
          ? yrs.includes(String(selectedYear))
          : live.has(el.dataset.sourceId) && live.has(el.dataset.targetId);
      }
      const vis =
        !hiddenTypes.has(el.dataset.sourceType) &&
        !hiddenTypes.has(el.dataset.targetType) &&
        yearVis &&
        (!q || (el.textContent || "").toLowerCase().includes(q));
      el.classList.toggle("is-hidden", !vis);
    });
    fallback.querySelectorAll("[data-group]").forEach((g) => {
      const shown = g.querySelectorAll(
        "[data-node-id]:not(.is-hidden), [data-edge]:not(.is-hidden)"
      ).length;
      g.classList.toggle("is-hidden", shown === 0);
    });
    if (listEmptyEl) {
      const any = fallback.querySelectorAll("[data-node-id]:not(.is-hidden)").length;
      listEmptyEl.hidden = any > 0;
    }
  }

  function clearSearch() {
    if (searchInput) searchInput.value = "";
    searchQuery = "";
  }

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      searchQuery = searchInput.value;
      refresh();
    });
    searchInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        const q = searchQuery.trim().toLowerCase();
        if (!q) return;
        const hit = nodes.find((n) => !hiddenTypes.has(n.type) && nodeMatches(n, q));
        if (hit) {
          clearSearch(); // commit the jump, then reveal the node's neighborhood
          select(hit, true);
          centerOn(hit);
          hit.el.focus();
        }
      } else if (ev.key === "Escape") {
        clearSearch();
        refresh();
      }
    });
  }
  if (clearBtn && searchInput) {
    clearBtn.addEventListener("click", () => {
      clearSearch();
      refresh();
      searchInput.focus();
    });
  }

  document.querySelectorAll(".gfilter").forEach((btn) => {
    btn.addEventListener("click", () => {
      const type = btn.dataset.type;
      const on = btn.getAttribute("aria-pressed") === "true";
      btn.setAttribute("aria-pressed", String(!on));
      if (on) hiddenTypes.add(type);
      else hiddenTypes.delete(type);
      refresh();
    });
  });

  // ---- Year filter: segmented control + shareable ?year= ------------------
  const yearWrap = document.querySelector("[data-graph-years]");
  if (yearWrap) {
    const yearBtns = yearWrap.querySelectorAll(".gyear");
    // Honour a deep-linked ?year= (the server already marked the active button).
    const initial = yearWrap.querySelector(".gyear.is-active");
    if (initial && initial.dataset.year) selectedYear = parseInt(initial.dataset.year, 10);

    const syncYearURL = () => {
      const url = new URL(window.location.href);
      if (selectedYear == null) url.searchParams.delete("year");
      else url.searchParams.set("year", String(selectedYear));
      history.replaceState(null, "", url);
    };

    yearBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const val = btn.dataset.year ? parseInt(btn.dataset.year, 10) : null;
        if (val === selectedYear) return;
        selectedYear = val;
        yearBtns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle("is-active", active);
          b.setAttribute("aria-pressed", String(active));
        });
        // The reframed graph may have dropped whatever was selected; reset the rail.
        clearSelection();
        syncYearURL();
        refresh();
      });
    });
  }

  function setView(mode) {
    const graphMode = mode === "graph";
    stage.hidden = !graphMode;
    if (fallback) fallback.hidden = graphMode;
    document.querySelectorAll(".gview").forEach((b) => {
      const active = b.dataset.view === mode;
      b.classList.toggle("is-active", active);
      b.setAttribute("aria-pressed", String(active));
    });
    if (graphMode) fitView();
    refresh();
  }
  document.querySelectorAll(".gview").forEach((b) => {
    b.addEventListener("click", () => setView(b.dataset.view));
  });

  const resetBtn = stage.querySelector("[data-graph-reset]");
  if (resetBtn) resetBtn.addEventListener("click", fitView);

  window.addEventListener("resize", () => {
    if (!stage.hidden) fitView();
  });

  // ---- Boot ----------------------------------------------------------------
  // settle the layout, then reveal the interactive stage (progressive enhance)
  if (reduceMotion) {
    for (let i = 0; i < 420; i++) {
      alpha = 1; // hold energy high for a deterministic synchronous settle
      tick();
    }
    render();
  } else {
    // warm the layout off-screen so the first painted frame is already organized
    for (let i = 0; i < 90; i++) tick();
    render();
  }
  setView("graph");
  if (!reduceMotion) loop();
})();
