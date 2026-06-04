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
    organization: { label: "Body", shape: "square", hue: 300, r: 21 },
    meeting: { label: "Meeting", shape: "diamond", hue: 150, r: 16 },
    person: { label: "Person", shape: "circle", hue: 25, r: 12 },
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
    neighbors.get(l.source.id).push({ node: l.target, label: l.label, dir: "out" });
    neighbors.get(l.target.id).push({ node: l.source, label: l.label, dir: "in" });
  });

  // ---- SVG scaffold --------------------------------------------------------
  const svg = stage.querySelector("[data-graph-canvas]");
  const gEdges = document.createElementNS(SVGNS, "g");
  const gEdgeLabels = document.createElementNS(SVGNS, "g");
  const gNodes = document.createElementNS(SVGNS, "g");
  gEdges.setAttribute("class", "g-edges");
  gEdgeLabels.setAttribute("class", "g-edgelabels");
  gNodes.setAttribute("class", "g-nodes");
  svg.append(gEdges, gEdgeLabels, gNodes);

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

  // Build node + edge DOM
  const linkEls = links.map((l) => {
    const line = document.createElementNS(SVGNS, "line");
    line.setAttribute("class", "g-edge");
    gEdges.appendChild(line);
    l.el = line;
    return line;
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
      l.el.setAttribute("x1", l.source.x);
      l.el.setAttribute("y1", l.source.y);
      l.el.setAttribute("x2", l.target.x);
      l.el.setAttribute("y2", l.target.y);
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

  // ---- Pointer: pan background, drag nodes ---------------------------------
  let drag = null; // {node|null, startX, startY, moved}
  svg.addEventListener("pointerdown", (ev) => {
    const nodeG = ev.target.closest(".gnode");
    const start = clientToWorld(ev.clientX, ev.clientY);
    if (nodeG) {
      const n = byId.get(nodeG.dataset ? nodeG.dataset.id : null) || nodes.find((x) => x.el === nodeG);
      drag = { node: n, sx: ev.clientX, sy: ev.clientY, moved: false };
      n.fx = n.x;
      n.fy = n.y;
    } else {
      drag = { node: null, sx: ev.clientX, sy: ev.clientY, wx: start.x, wy: start.y, vx: view.x, vy: view.y, moved: false };
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
    } else {
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
      if (!drag.moved) select(drag.node, false);
    }
    drag = null;
    if (ev && ev.pointerId != null) {
      try { svg.releasePointerCapture(ev.pointerId); } catch (_) {}
    }
  }
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  // ---- Selection + hover + the detail rail --------------------------------
  const rail = stage.querySelector("[data-graph-rail]");
  let selected = null;
  let hovered = null;

  function setEdgeState() {
    links.forEach((l) => {
      const active =
        selected && (l.source.id === selected.id || l.target.id === selected.id);
      const dimmed = selected && !active;
      l.el.classList.toggle("is-active", !!active);
      l.el.classList.toggle("is-dim", !!dimmed);
    });
    nodes.forEach((n) => {
      const isSel = selected && n.id === selected.id;
      const isNbr =
        selected && neighbors.get(selected.id).some((x) => x.node.id === n.id);
      n.el.classList.toggle("is-selected", !!isSel);
      n.el.classList.toggle("is-dim", !!(selected && !isSel && !isNbr));
    });
    renderActiveEdgeLabels();
  }

  function renderActiveEdgeLabels() {
    gEdgeLabels.replaceChildren();
    if (!selected) return;
    links
      .filter((l) => l.source.id === selected.id || l.target.id === selected.id)
      .forEach((l) => {
        if (!l.label) return;
        const t = document.createElementNS(SVGNS, "text");
        t.setAttribute("class", "g-edgelabel");
        t.setAttribute("text-anchor", "middle");
        t.textContent = l.label;
        gEdgeLabels.appendChild(t);
        l.labelEl = t;
      });
    positionActiveEdgeLabels();
  }
  function positionActiveEdgeLabels() {
    if (!selected) return;
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
    const connItems = conns
      .map(
        (c) =>
          `<li><button type="button" class="gr-conn" data-goto="${esc(c.node.id)}">
             <span class="gr-conn__rel mono">${esc(c.label)}</span>
             <span class="gr-conn__name">${esc(c.node.label)}</span>
           </button></li>`
      )
      .join("");

    return `
      <div class="gr-head" style="--c: oklch(74% 0.135 ${t.hue});">
        <span class="gr-type"><span class="gr-type__dot gfilter__swatch--${t.shape}"></span>${esc(t.label)}</span>
        <h2 class="gr-name">${esc(n.label)}</h2>
        ${n.sublabel && n.sublabel !== t.label ? `<p class="gr-sub">${esc(n.sublabel)}</p>` : ""}
      </div>
      ${stats ? `<dl class="gr-stats">${stats}</dl>` : ""}
      ${docs ? `<div class="gr-block"><h3 class="gr-block__title">Source documents</h3><ul class="gr-docs">${docs}</ul></div>` : ""}
      ${connItems ? `<div class="gr-block"><h3 class="gr-block__title">Connections <span class="mono">${conns.length}</span></h3><ul class="gr-conns">${connItems}</ul></div>` : ""}
      ${n.href ? `<a class="gr-cta" href="${esc(n.href)}">Follow to the record <span aria-hidden="true">↗</span></a>` : ""}
    `;
  }

  function select(n, fromKeyboard) {
    selected = n;
    rail.innerHTML = railHTML(n);
    rail.classList.add("is-filled");
    setEdgeState();
    rail.querySelectorAll("[data-goto]").forEach((b) => {
      b.addEventListener("click", () => {
        const t = byId.get(b.dataset.goto);
        if (t) {
          select(t, false);
          centerOn(t);
          t.el.focus();
        }
      });
    });
    if (fromKeyboard) {
      const h = rail.querySelector(".gr-name");
      if (h) h.setAttribute("tabindex", "-1");
    }
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

  // ---- Filters + view toggle + reset --------------------------------------
  const hiddenTypes = new Set();
  function applyFilters() {
    nodes.forEach((n) => n.el.classList.toggle("is-filtered", hiddenTypes.has(n.type)));
    links.forEach((l) =>
      l.el.classList.toggle(
        "is-filtered",
        hiddenTypes.has(l.source.type) || hiddenTypes.has(l.target.type)
      )
    );
  }
  document.querySelectorAll(".gfilter").forEach((btn) => {
    btn.addEventListener("click", () => {
      const type = btn.dataset.type;
      const on = btn.getAttribute("aria-pressed") === "true";
      btn.setAttribute("aria-pressed", String(!on));
      if (on) hiddenTypes.add(type);
      else hiddenTypes.delete(type);
      applyFilters();
    });
  });

  const fallback = document.querySelector("[data-graph-fallback]");
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
