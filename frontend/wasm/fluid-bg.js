// Ambient background: a real fluid-dynamics velocity field (Stable Fluids,
// see wasm-fluid/src/lib.rs) rendered as dye particles advected through it.
// The current visitor's own live cursor always injects force in real time.
//
// On the home page ONLY (window.FLUID_HISTORY_ENABLED === true, set in
// index.html before this script loads -- docs.html leaves it unset), this
// also does something more literal than an aggregate field: it RECORDS the
// visitor's own cursor path -- (t_ms, nx, ny) samples -- for their first two
// minutes, sends it to the backend once, and on every page load fetches a
// random handful of OTHER visitors' previously-recorded paths and loops them
// forever as "ghost" cursors injecting into the same fluid field alongside
// the live one. The background is never the same twice, and it's built from
// how real people actually moved, not a synthesized pattern -- see
// docs/Memory.md's cursor-flow redesign for the full rationale, including
// why this is a materially different (and more carefully bounded) privacy
// posture than the coarse aggregate-grid approach it replaced.
(function () {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (typeof WebAssembly === 'undefined') return;

  var HISTORY_ENABLED = window.FLUID_HISTORY_ENABLED === true;
  var RECORD_DURATION_MS = 120000; // 2 minutes
  var GHOST_COUNT = 6;

  var canvas = document.querySelector('.bg-network');
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext('2d');
  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  var w, h;

  var wasm = null;
  var sim = null;

  // ---- recording the current visitor's own path (home page only) ----
  var recordStart = performance.now();
  var recordedSamples = []; // [t_ms, nx, ny]
  var pathSent = false;
  var lastRecordT = 0;

  function recordSample(nx, ny) {
    if (!HISTORY_ENABLED || pathSent) return;
    var elapsed = performance.now() - recordStart;
    if (elapsed > RECORD_DURATION_MS) {
      sendOwnPath(false);
      return;
    }
    if (elapsed - lastRecordT < 80) return; // ~12/s, plenty for smooth playback later
    lastRecordT = elapsed;
    recordedSamples.push([Math.round(elapsed), nx, ny]);
  }

  function sendOwnPath(useBeacon) {
    if (!HISTORY_ENABLED || pathSent || recordedSamples.length < 20) return;
    pathSent = true;
    var body = JSON.stringify({ samples: recordedSamples });
    var url = CONFIG.BACKEND_URL + '/telemetry/path';
    if (useBeacon && navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }));
    } else {
      fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true }).catch(function () {});
    }
  }
  if (HISTORY_ENABLED) {
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) sendOwnPath(true);
    });
    window.addEventListener('pagehide', function () { sendOwnPath(true); });
  }

  // ---- live cursor: always injects, regardless of HISTORY_ENABLED ----
  var lastPointer = null;
  var lastSampleT = 0;
  function onPointerMove(ev) {
    var now = performance.now();
    if (now - lastSampleT < 60) return;
    lastSampleT = now;
    var nx = ev.clientX / window.innerWidth;
    var ny = ev.clientY / window.innerHeight;
    if (lastPointer) {
      var dnx = nx - lastPointer.nx, dny = ny - lastPointer.ny;
      if (wasm && sim) wasm.fluid_inject(sim, nx, ny, dnx * 32, dny * 32, 3.0);
    }
    lastPointer = { nx: nx, ny: ny };
    recordSample(nx, ny);
  }
  window.addEventListener('pointermove', onPointerMove, { passive: true });

  // ---- ghosts: other visitors' recorded paths, looped forever ----
  var ghosts = []; // { samples, duration, startTime, lastPos }

  function findBracket(samples, t) {
    // Binary search for the pair of samples straddling t (samples sorted by t_ms).
    var lo = 0, hi = samples.length - 1;
    if (t <= samples[0][0]) return [0, 0, 0];
    if (t >= samples[hi][0]) return [hi, hi, 0];
    while (hi - lo > 1) {
      var mid = (lo + hi) >> 1;
      if (samples[mid][0] <= t) lo = mid; else hi = mid;
    }
    var t0 = samples[lo][0], t1 = samples[hi][0];
    var frac = t1 > t0 ? (t - t0) / (t1 - t0) : 0;
    return [lo, hi, frac];
  }

  function ghostPosition(g, now) {
    var elapsed = (now - g.startTime) % g.duration;
    var b = findBracket(g.samples, elapsed);
    var a = g.samples[b[0]], c = g.samples[b[1]], f = b[2];
    return { nx: a[1] + (c[1] - a[1]) * f, ny: a[2] + (c[2] - a[2]) * f };
  }

  async function loadGhosts() {
    if (!HISTORY_ENABLED) return;
    try {
      var resp = await fetch(CONFIG.BACKEND_URL + '/telemetry/paths?limit=' + GHOST_COUNT);
      var data = await resp.json();
      var now = performance.now();
      (data.paths || []).forEach(function (p) {
        if (!p.samples || p.samples.length < 2) return;
        var duration = p.samples[p.samples.length - 1][0];
        if (!(duration > 0)) return;
        var startTime = now - Math.random() * duration;
        ghosts.push({ samples: p.samples, duration: duration, startTime: startTime, lastPos: null });
      });
    } catch (e) {
      // No historical paths yet (fresh deploy) or backend unreachable -- the
      // background still works, just driven by live cursors only until a
      // pool of recorded paths exists.
    }
  }

  // ---- rendering ----
  var particles = [];
  function spawnParticles() {
    var n = Math.max(90, Math.min(170, Math.round((w * h) / 9500)));
    particles = [];
    for (var i = 0; i < n; i++) {
      particles.push({ x: Math.random() * w, y: Math.random() * h, age: 0, life: 100 + Math.random() * 200 });
    }
  }

  function resize() {
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    spawnParticles();
  }
  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resize, 150);
  });

  var GRID_W = 48, GRID_H = 27, CELL_COUNT = GRID_W * GRID_H;

  function sampleVelocity(vxView, vyView, px, py) {
    var gx = (px / w) * GRID_W - 0.5;
    var gy = (py / h) * GRID_H - 0.5;
    var x0 = Math.floor(gx), y0 = Math.floor(gy);
    var tx = gx - x0, ty = gy - y0;
    var x0c = Math.max(0, Math.min(GRID_W - 1, x0));
    var x1c = Math.max(0, Math.min(GRID_W - 1, x0 + 1));
    var y0c = Math.max(0, Math.min(GRID_H - 1, y0));
    var y1c = Math.max(0, Math.min(GRID_H - 1, y0 + 1));
    var i00 = x0c + y0c * GRID_W, i10 = x1c + y0c * GRID_W, i01 = x0c + y1c * GRID_W, i11 = x1c + y1c * GRID_W;
    var vx = vxView[i00] * (1 - tx) * (1 - ty) + vxView[i10] * tx * (1 - ty) + vxView[i01] * (1 - tx) * ty + vxView[i11] * tx * ty;
    var vy = vyView[i00] * (1 - tx) * (1 - ty) + vyView[i10] * tx * (1 - ty) + vyView[i01] * (1 - tx) * ty + vyView[i11] * tx * ty;
    return [vx, vy];
  }

  var raf;
  function step() {
    var now = performance.now();

    for (var g = 0; g < ghosts.length; g++) {
      var ghost = ghosts[g];
      var pos = ghostPosition(ghost, now);
      if (ghost.lastPos && wasm && sim) {
        var dnx = pos.nx - ghost.lastPos.nx, dny = pos.ny - ghost.lastPos.ny;
        wasm.fluid_inject(sim, pos.nx, pos.ny, dnx * 32, dny * 32, 2.4);
      }
      ghost.lastPos = pos;
    }

    wasm.fluid_step(sim, 0.12, 0.15);
    var vxView = new Float32Array(wasm.memory.buffer, wasm.fluid_vx_ptr(sim), CELL_COUNT);
    var vyView = new Float32Array(wasm.memory.buffer, wasm.fluid_vy_ptr(sim), CELL_COUNT);

    ctx.fillStyle = 'rgba(0,0,0,0.09)';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(255,255,255,0.11)';
    ctx.lineWidth = 1;
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      var v = sampleVelocity(vxView, vyView, p.x, p.y);
      var nx2 = p.x + v[0] * w * 0.02;
      var ny2 = p.y + v[1] * h * 0.02;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(nx2, ny2);
      ctx.stroke();
      p.x = nx2; p.y = ny2; p.age++;
      if (p.age > p.life || p.x < 0 || p.x > w || p.y < 0 || p.y > h) {
        p.x = Math.random() * w; p.y = Math.random() * h; p.age = 0; p.life = 100 + Math.random() * 200;
      }
    }
    raf = requestAnimationFrame(step);
  }

  async function init() {
    resize();
    var resp = await fetch('/wasm/fluid_flow.wasm');
    var bytes = await resp.arrayBuffer();
    var result = await WebAssembly.instantiate(bytes, {});
    wasm = result.instance.exports;
    sim = wasm.fluid_new(GRID_W, GRID_H);
    await loadGhosts();
    raf = requestAnimationFrame(step);
  }

  init().catch(function (e) { console.warn('fluid background unavailable:', e); });
})();
