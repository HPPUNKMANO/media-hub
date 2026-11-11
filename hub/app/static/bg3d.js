/* Media Hub - 3D background: a slow, glowing particle wave that follows the mouse.
   Light on the GPU (capped pixel ratio, ~40 fps), pauses when the window is hidden, off with "reduce motion". */
(function () {
  "use strict";
  if (!window.THREE || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const canvas = document.getElementById("bg3d");
  if (!canvas) return;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x07070b, 0.018);
  const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 200);
  camera.position.set(0, 9, 34);

  const COLS = 150, ROWS = 70, GAP = 0.62;
  const count = COLS * ROWS;
  const pos = new Float32Array(count * 3), col = new Float32Array(count * 3), base = new Float32Array(count * 2);
  const c1 = new THREE.Color("#8d8a84"), c2 = new THREE.Color("#ff5b2e"), c3 = new THREE.Color("#e9e4d8"), tmp = new THREE.Color();
  let i = 0;
  for (let x = 0; x < COLS; x++) for (let z = 0; z < ROWS; z++, i++) {
    const px = (x - COLS / 2) * GAP, pz = (z - ROWS / 2) * GAP;
    pos[i * 3] = px; pos[i * 3 + 2] = pz; base[i * 2] = px; base[i * 2 + 1] = pz;
    const t = x / COLS;
    tmp.copy(c1).lerp(t < 0.5 ? c2 : c3, Math.abs(t - 0.5) * 2);
    col[i * 3] = tmp.r; col[i * 3 + 1] = tmp.g; col[i * 3 + 2] = tmp.b;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));

  // soft round sprite so particles glow instead of being squares
  const dot = document.createElement("canvas"); dot.width = dot.height = 64;
  const g = dot.getContext("2d"), grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, "rgba(255,255,255,1)"); grd.addColorStop(0.35, "rgba(255,255,255,.55)"); grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  const mat = new THREE.PointsMaterial({ size: 0.26, map: new THREE.CanvasTexture(dot), vertexColors: true, transparent: true,
    opacity: 0.7, depthWrite: false, blending: THREE.AdditiveBlending });
  const points = new THREE.Points(geo, mat);
  points.rotation.x = -0.12;
  scene.add(points);

  let mx = 0, my = 0, tx = 0, ty = 0;
  addEventListener("pointermove", (e) => { tx = e.clientX / innerWidth - 0.5; ty = e.clientY / innerHeight - 0.5; }, { passive: true });

  function resize() {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  addEventListener("resize", resize); resize();

  let last = 0, running = true;
  document.addEventListener("visibilitychange", () => { running = !document.hidden; if (running) requestAnimationFrame(loop); });
  function loop(now) {
    if (!running) return;
    requestAnimationFrame(loop);
    if (now - last < 25) return;   // ~40 fps is plenty for a background
    last = now;
    const t = now * 0.00045;
    const p = geo.attributes.position.array;
    for (let k = 0; k < count; k++) {
      const x = base[k * 2], z = base[k * 2 + 1];
      p[k * 3 + 1] = Math.sin(x * 0.18 + t * 2) * 1.6 + Math.cos(z * 0.22 + t * 1.4) * 1.3 + Math.sin((x + z) * 0.08 + t) * 1.1;
    }
    geo.attributes.position.needsUpdate = true;
    mx += (tx - mx) * 0.04; my += (ty - my) * 0.04;
    camera.position.x = mx * 10; camera.position.y = 9 - my * 5;
    camera.lookAt(0, 0, 0);
    points.rotation.y = t * 0.08;
    renderer.render(scene, camera);
  }
  requestAnimationFrame(loop);
})();
