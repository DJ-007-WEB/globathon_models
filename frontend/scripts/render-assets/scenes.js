// Procedural scenes for SolarSleuth marketing photography.
// Rendered headlessly by render.mjs; every image is generated here, so no third-party
// photograph is used. Each scene is deterministic (seeded random).
import * as THREE from "three";

const params = new URLSearchParams(location.search);
const sceneName = params.get("scene") || "hero-aerial";
const W = Number(params.get("w") || 1600);
const H = Number(params.get("h") || 900);

// ---------- deterministic random ----------
let seed = 1234567;
const rand = () => {
  seed = (seed * 16807) % 2147483647;
  return (seed - 1) / 2147483646;
};
const range = (a, b) => a + (b - a) * rand();

// ---------- texture helpers ----------
function canvasTexture(w, h, draw, { repeat = [1, 1], srgb = true } = {}) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(...repeat);
  t.anisotropy = 8;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function noise(ctx, w, h, colors, count, size) {
  for (let i = 0; i < count; i++) {
    ctx.fillStyle = colors[Math.floor(rand() * colors.length)];
    const s = range(size[0], size[1]);
    ctx.globalAlpha = range(0.15, 0.6);
    ctx.fillRect(rand() * w, rand() * h, s, s * range(0.6, 1.6));
  }
  ctx.globalAlpha = 1;
}

const grassCache = new Map();
const grassTexture = (base = "#3f5c27", repeat = [40, 40]) => {
  const key = base;
  if (!grassCache.has(key)) {
    grassCache.set(key, canvasTexture(2048, 2048, (ctx, w, h) => {
      ctx.fillStyle = base; ctx.fillRect(0, 0, w, h);
      // large patches of drier and lusher grass, baked in so sunlight cannot wash them out
      ctx.filter = "blur(40px)";
      const patches = ["rgba(120,120,60,0.35)", "rgba(40,70,25,0.45)", "rgba(95,110,50,0.3)", "rgba(30,50,20,0.4)"];
      for (let i = 0; i < 220; i++) {
        ctx.fillStyle = patches[i % patches.length];
        const [x, y, rx, ry, rot] = [rand() * w, rand() * h, range(40, 220), range(30, 140), rand() * 3];
        // draw wrapped copies so the texture tiles without seams
        for (const dx of [-w, 0, w]) for (const dy of [-h, 0, h]) {
          ctx.beginPath(); ctx.ellipse(x + dx, y + dy, rx, ry, rot, 0, Math.PI * 2); ctx.fill();
        }
      }
      ctx.filter = "none";
      noise(ctx, w, h, ["#2f4a1d", "#4c6e2f", "#577a34", "#3a5524", "#6a7a3f", "#7d7a48"], 140000, [1, 3]);
    }));
  }
  const t = grassCache.get(key).clone();
  t.needsUpdate = true;
  t.repeat.set(repeat[0] / 6, repeat[1] / 6);
  return t;
};

// Low-frequency light/dark variation, applied once across the whole ground (no visible tiling).
const macroTexture = () => canvasTexture(1024, 1024, (ctx, w, h) => {
  ctx.fillStyle = "#c8c8c8"; ctx.fillRect(0, 0, w, h);
  ctx.filter = "blur(30px)";
  for (let i = 0; i < 160; i++) {
    const v = Math.floor(range(120, 255));
    ctx.fillStyle = `rgb(${v},${v},${v})`;
    ctx.beginPath(); ctx.ellipse(rand() * w, rand() * h, range(30, 140), range(20, 90), rand() * 3, 0, Math.PI * 2); ctx.fill();
  }
  ctx.filter = "none";
}, { srgb: false });

const gravelTexture = () => canvasTexture(256, 256, (ctx, w, h) => {
  ctx.fillStyle = "#8f8a7c"; ctx.fillRect(0, 0, w, h);
  noise(ctx, w, h, ["#a39e8e", "#7b7668", "#b6b1a0", "#6c6759"], 5000, [1, 3]);
}, { repeat: [2, 60] });

// A PV module: cell grid, busbars, frame, faint sky reflection gradient.
const panelTexture = (cols = 6, rows = 12, tint = "#16245a") => canvasTexture(512, 1024, (ctx, w, h) => {
  const g = ctx.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, "#1a2756"); g.addColorStop(0.5, tint); g.addColorStop(1, "#0a1230");
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  const pad = 10, cw = (w - pad * 2) / cols, ch = (h - pad * 2) / rows;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const x = pad + c * cw, y = pad + r * ch;
    ctx.fillStyle = `rgba(${14 + rand() * 10},${22 + rand() * 12},${58 + rand() * 22},0.7)`;
    ctx.fillRect(x + 2, y + 2, cw - 4, ch - 4);
    ctx.strokeStyle = "rgba(150,170,220,0.35)"; ctx.lineWidth = 1;
    for (let k = 1; k < 4; k++) { ctx.beginPath(); ctx.moveTo(x + (cw * k) / 4, y + 2); ctx.lineTo(x + (cw * k) / 4, y + ch - 2); ctx.stroke(); }
  }
  ctx.strokeStyle = "rgba(205,214,232,0.7)"; ctx.lineWidth = 3;
  for (let c = 0; c <= cols; c++) { ctx.beginPath(); ctx.moveTo(pad + c * cw, pad); ctx.lineTo(pad + c * cw, h - pad); ctx.stroke(); }
  for (let r = 0; r <= rows; r++) { ctx.beginPath(); ctx.moveTo(pad, pad + r * ch); ctx.lineTo(w - pad, pad + r * ch); ctx.stroke(); }
  ctx.strokeStyle = "#c9ced6"; ctx.lineWidth = 12; ctx.strokeRect(0, 0, w, h);
});

function skyTexture(top, mid, bottom, sun) {
  return canvasTexture(1024, 512, (ctx, w, h) => {
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, top); g.addColorStop(0.55, mid); g.addColorStop(1, bottom);
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    if (sun) {
      const s = ctx.createRadialGradient(sun.x * w, sun.y * h, 0, sun.x * w, sun.y * h, sun.r * w);
      s.addColorStop(0, sun.color); s.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = s; ctx.fillRect(0, 0, w, h);
    }
    // soft, blurred cloud banks
    ctx.filter = "blur(18px)";
    for (let i = 0; i < 26; i++) {
      ctx.fillStyle = `rgba(255,255,255,${range(0.04, 0.12)})`;
      ctx.beginPath(); ctx.ellipse(rand() * w, range(0.08, 0.5) * h, range(80, 260), range(10, 26), 0, 0, Math.PI * 2); ctx.fill();
    }
    ctx.filter = "none";
  }, { repeat: [1, 1] });
}

// ---------- renderer ----------
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = Number(params.get("exposure") || 0.82);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

function envFromSky(scene, skyTex) {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envScene = new THREE.Scene();
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(50, 32, 16), new THREE.MeshBasicMaterial({ map: skyTex, side: THREE.BackSide }));
  envScene.add(sphere);
  scene.environment = pmrem.fromScene(envScene, 0.04).texture;
}

function sunLight(scene, color, intensity, pos, area = 160) {
  const light = new THREE.DirectionalLight(color, intensity);
  light.position.set(...pos);
  light.castShadow = true;
  light.shadow.mapSize.set(4096, 4096);
  const c = light.shadow.camera;
  c.left = -area; c.right = area; c.top = area; c.bottom = -area; c.near = 1; c.far = 800;
  light.shadow.bias = -0.0004;
  scene.add(light);
  return light;
}

// PV row: a long tilted table of modules on posts.
function pvRow(length, { tilt = 0.45, height = 1.1, depth = 4.0, panelTex, frameColor = 0xb8bec8 } = {}) {
  const group = new THREE.Group();
  const modules = Math.max(1, Math.round(length / 1.05));
  const mat = new THREE.MeshStandardMaterial({ map: panelTex, roughness: 0.3, metalness: 0.2, envMapIntensity: 0.55 });
  const frame = new THREE.MeshStandardMaterial({ color: frameColor, roughness: 0.5, metalness: 0.6 });
  const table = new THREE.Group();
  for (let i = 0; i < modules; i++) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.04, depth), mat);
    m.position.set(-length / 2 + i * 1.05 + 0.5, 0, 0);
    m.castShadow = true; m.receiveShadow = true;
    table.add(m);
  }
  const rail = new THREE.Mesh(new THREE.BoxGeometry(length, 0.06, 0.06), frame);
  rail.position.set(0, -0.05, depth * 0.3); table.add(rail);
  table.rotation.x = -tilt;
  table.position.y = height;
  group.add(table);
  for (let x = -length / 2; x <= length / 2; x += 4) {
    const post = new THREE.Mesh(new THREE.BoxGeometry(0.08, height, 0.08), frame);
    post.position.set(x, height / 2, 0.2); post.castShadow = true; group.add(post);
  }
  return group;
}

function ground(scene, tex, size = 8000, color = 0xffffff) {
  const ao = macroTexture(); ao.repeat.set(3, 3);
  const g = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshStandardMaterial({ map: tex, color, roughness: 0.95, aoMap: ao, aoMapIntensity: 1.0 }));
  g.rotation.x = -Math.PI / 2; g.receiveShadow = true; scene.add(g);
  return g;
}

function strip(scene, tex, length, width, { x = 0, z = 0, rotY = 0, y = 0.02, color = 0xffffff } = {}) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(width, length), new THREE.MeshStandardMaterial({ map: tex, color, roughness: 1 }));
  m.rotation.x = -Math.PI / 2; m.rotation.z = rotY; m.position.set(x, y, z); m.receiveShadow = true; scene.add(m);
  return m;
}

// ---------- scenes ----------
const scenes = {};

// Oblique aerial of a PV field with access road and railway, low sun (home hero, contact, about).
scenes["hero-aerial"] = () => {
  const scene = new THREE.Scene();
  const sky = skyTexture("#9fb6c8", "#c9d6d8", "#e6e2cf");
  scene.background = new THREE.Color("#9db0a2");
  scene.fog = new THREE.Fog("#a3b09a", 220, 620);
  envFromSky(scene, sky);
  scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x3b5a22, 0.9));
  sunLight(scene, 0xfff1d6, 2.6, [-120, 90, 60], 220);
  ground(scene, grassTexture("#3f5c27", [120, 120]));
  const panel = panelTexture();
  const field = new THREE.Group();
  for (let r = 0; r < 34; r++) {
    for (let seg = 0; seg < 3; seg++) {
      const len = range(26, 40);
      if (rand() < 0.08) continue;
      const row = pvRow(len, { panelTex: panel });
      row.position.set(seg * 46 - 46 + range(-3, 3), 0, r * 8.5 - 130);
      field.add(row);
    }
  }
  field.rotation.y = 0.55;
  scene.add(field);
  // gravel road and railway along the top-right
  const gravel = gravelTexture();
  strip(scene, gravel, 600, 5, { x: 70, z: -40, rotY: 0.55 + Math.PI / 2 - 0.15 });
  const rails = new THREE.MeshStandardMaterial({ color: 0x6e6a62, roughness: 0.6, metalness: 0.4 });
  for (const off of [0, 1.6, 8, 9.6]) {
    const r = new THREE.Mesh(new THREE.BoxGeometry(600, 0.15, 0.15), rails);
    r.rotation.y = 0.55 - 0.15; r.position.set(110 + off, 0.1, -120 + off * 0.4); scene.add(r);
  }
  strip(scene, gravel, 600, 14, { x: 112, z: -118, rotY: 0.4 + Math.PI / 2, color: 0x9a9480 });
  const camera = new THREE.PerspectiveCamera(42, W / H, 1, 2000);
  camera.position.set(-50, 70, 80);
  camera.lookAt(20, 0, -30);
  return { scene, camera };
};

// Straight-down view of diagonal rows separated by grass strips (trust hero, energy waterfall).
scenes["pv-topdown"] = () => {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#4d7a2c");
  envFromSky(scene, skyTexture("#9ab4d0", "#cdd8e0", "#e9eef0"));
  scene.add(new THREE.HemisphereLight(0xe8f0ff, 0x45652a, 1.0));
  sunLight(scene, 0xfff3dc, 2.4, [-40, 80, 30], 120);
  ground(scene, grassTexture("#3f5c27", [80, 80]));
  const panel = panelTexture(6, 12, "#1a2a66");
  const field = new THREE.Group();
  for (let r = 0; r < 30; r++) {
    const row = pvRow(260, { panelTex: panel, tilt: 0.42, depth: 4.4 });
    row.position.set(0, 0, r * 8.6 - 120);
    field.add(row);
  }
  field.rotation.y = -0.62;
  scene.add(field);
  const camera = new THREE.PerspectiveCamera(35, W / H, 1, 1000);
  camera.position.set(0, 140, 0.01);
  camera.lookAt(0, 0, 0);
  return { scene, camera };
};

// Wide farmland with a PV block, horizon and soft sky (expected-energy baseline).
scenes["pv-landscape"] = () => {
  const scene = new THREE.Scene();
  const sky = skyTexture("#8fa8c2", "#c7d3dc", "#eef0ea", { x: 0.7, y: 0.75, r: 0.4, color: "rgba(255,240,210,0.6)" });
  scene.background = sky;
  scene.fog = new THREE.Fog("#c9d3d4", 200, 900);
  envFromSky(scene, sky);
  scene.add(new THREE.HemisphereLight(0xe2ecff, 0x4a6b2c, 0.9));
  sunLight(scene, 0xfff0d4, 3.0, [120, 70, -60], 160);
  ground(scene, grassTexture("#3f5c27", [160, 160]));
  // farmland patches
  const tones = ["#5d7a34", "#7c8746", "#4d6a2b", "#8f875c", "#6b7c3c", "#43622a", "#86805a"];
  const fieldTex = tones.map((tone) => canvasTexture(256, 256, (ctx, w, h) => {
    ctx.fillStyle = tone; ctx.fillRect(0, 0, w, h);
    noise(ctx, w, h, ["#3a5524", "#6a7a3f", "#7d7a48", "#4c6e2f"], 3000, [1, 3]);
  }, { repeat: [6, 6] }));
  for (let i = 0; i < 40; i++) {
    const tex = fieldTex[i % fieldTex.length];
    strip(scene, tex, range(40, 120), range(30, 90), { x: range(-500, 500), z: range(-700, -60), rotY: range(-0.3, 0.3), y: 0.03 + i * 0.001 });
  }
  const panel = panelTexture();
  const field = new THREE.Group();
  for (let r = 0; r < 22; r++) {
    const row = pvRow(70, { panelTex: panel });
    row.position.set(0, 0, r * 7.4);
    field.add(row);
  }
  field.position.set(-10, 0, -40);
  field.rotation.y = 0.35;
  scene.add(field);
  strip(scene, gravelTexture(), 400, 4, { x: -60, z: 0, rotY: 0.35 });
  const camera = new THREE.PerspectiveCamera(40, W / H, 1, 3000);
  camera.position.set(-90, 55, 120);
  camera.lookAt(0, 0, -10);
  return { scene, camera };
};

// Dusk over a dark field with low glinting rows (principles background, resources hero).
scenes["dusk-field"] = () => {
  const scene = new THREE.Scene();
  const sky = skyTexture("#1b2420", "#4a4630", "#c48a46", { x: 0.62, y: 0.95, r: 0.45, color: "rgba(255,196,120,0.85)" });
  scene.background = sky;
  scene.fog = new THREE.Fog("#3a3626", 60, 320);
  envFromSky(scene, sky);
  scene.add(new THREE.HemisphereLight(0x9a8a6a, 0x141a10, 0.9));
  sunLight(scene, 0xffb46a, 3.0, [60, 10, -200], 200);
  ground(scene, grassTexture("#2a3a1c", [120, 120]));
  const panel = panelTexture(6, 12, "#101a3a");
  for (let r = 0; r < 26; r++) {
    const row = pvRow(160, { panelTex: panel, tilt: 0.5 });
    row.children[0].children.forEach((m) => { if (m.material?.map) m.material = m.material.clone(), m.material.envMapIntensity = 1.6, m.material.roughness = 0.12; });
    row.position.set(-20, 0, -r * 8 + 30);
    row.rotation.y = 0.12;
    scene.add(row);
  }
  const camera = new THREE.PerspectiveCamera(48, W / H, 0.5, 2000);
  camera.position.set(-40, 12, 46);
  camera.lookAt(20, 3, -60);
  return { scene, camera };
};

// Close-up of a green switchgear cabinet with push buttons, labels and a warning sign.
function labelTexture(text) {
  return canvasTexture(256, 64, (ctx, w, h) => {
    ctx.fillStyle = "#eceae2"; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#3a3a3a"; ctx.font = "22px sans-serif"; ctx.fillText(text, 14, 40);
  });
}
const warningTexture = () => canvasTexture(256, 256, (ctx, w, h) => {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#f2c200"; ctx.strokeStyle = "#111"; ctx.lineWidth = 14;
  ctx.beginPath(); ctx.moveTo(w / 2, 18); ctx.lineTo(w - 16, h - 22); ctx.lineTo(16, h - 22); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#111"; ctx.beginPath();
  ctx.moveTo(140, 80); ctx.lineTo(104, 150); ctx.lineTo(132, 150); ctx.lineTo(112, 205); ctx.lineTo(158, 128); ctx.lineTo(130, 128); ctx.lineTo(150, 80); ctx.closePath(); ctx.fill();
});

scenes["switchgear-panel"] = () => {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#0c120e");
  envFromSky(scene, skyTexture("#3a4a40", "#556b5c", "#2a3530"));
  scene.add(new THREE.AmbientLight(0x9fb3a6, 0.35));
  const key = new THREE.SpotLight(0xf3f7ff, 260, 40, 0.7, 0.6, 1.5);
  key.position.set(-6, 6, 9); key.target.position.set(1, 0, 0); key.castShadow = true;
  scene.add(key, key.target);
  const paint = canvasTexture(512, 512, (ctx, w, h) => {
    ctx.fillStyle = "#6f8f6e"; ctx.fillRect(0, 0, w, h);
    noise(ctx, w, h, ["#647f62", "#7a9877", "#5b7559", "#839f80"], 4000, [1, 6]);
  });
  const steel = new THREE.MeshStandardMaterial({ map: paint, roughness: 0.55, metalness: 0.25 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(14, 10, 1), steel);
  body.receiveShadow = true; scene.add(body);
  // door seams
  const seam = new THREE.MeshStandardMaterial({ color: 0x1d261d, roughness: 0.8 });
  for (const x of [-2.2, 3.4]) { const s = new THREE.Mesh(new THREE.BoxGeometry(0.06, 10, 1.02), seam); s.position.x = x; scene.add(s); }
  const btnColors = [0xb3201c, 0xb3201c, 0x1c1c1e, 0xe9e5d6, 0xb3201c, 0x1c1c1e, 0xd9a441];
  const labels = ["START", "STOP", "RESET", "AUTO", "TRIP", "LOCAL", "TEST"];
  for (let col = 0; col < 7; col++) {
    for (let row = 0; row < 6; row++) {
      if (rand() < 0.18) continue;
      const x = -5.6 + col * 1.55 + (col > 2 ? 0.6 : 0), y = 3.6 - row * 1.35;
      const c = btnColors[(col + row * 3) % btnColors.length];
      const bezel = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.3, 0.12, 32), new THREE.MeshStandardMaterial({ color: 0x9aa09a, metalness: 0.8, roughness: 0.3 }));
      bezel.rotation.x = Math.PI / 2; bezel.position.set(x, y, 0.56); scene.add(bezel);
      const btn = new THREE.Mesh(new THREE.CylinderGeometry(0.21, 0.22, 0.22, 32), new THREE.MeshStandardMaterial({ color: c, roughness: 0.25, metalness: 0.05 }));
      btn.rotation.x = Math.PI / 2; btn.position.set(x, y, 0.64); btn.castShadow = true; scene.add(btn);
      const lab = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.22), new THREE.MeshStandardMaterial({ map: labelTexture(labels[(col + row) % labels.length]), roughness: 0.7 }));
      lab.position.set(x, y + 0.5, 0.505); scene.add(lab);
    }
  }
  // rotary selectors
  for (const [x, y] of [[-4.0, -4.2], [-1.0, -4.2]]) {
    const base = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.7, 0.1), new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.6 }));
    base.position.set(x, y, 0.55); scene.add(base);
    const knob = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.5, 0.2), new THREE.MeshStandardMaterial({ color: 0x111111 }));
    knob.position.set(x, y, 0.65); knob.rotation.z = 0.6; scene.add(knob);
  }
  // meter window
  const glass = new THREE.Mesh(new THREE.BoxGeometry(2.6, 1.6, 0.12), new THREE.MeshStandardMaterial({ color: 0x223028, roughness: 0.05, metalness: 0.6 }));
  glass.position.set(5.6, 3.7, 0.55); scene.add(glass);
  const warn = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 1.3), new THREE.MeshStandardMaterial({ map: warningTexture(), transparent: true, roughness: 0.6 }));
  warn.position.set(5.2, 0.2, 0.51); scene.add(warn);
  const camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 100);
  camera.position.set(-5.2, 0.8, 7.2);
  camera.lookAt(0.8, 0, 0);
  return { scene, camera };
};

// Corridor of switchgear cabinets with indicator LEDs (trust data handling, validation row).
scenes["switchgear-room"] = () => {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#2b2e2c");
  envFromSky(scene, skyTexture("#cfd3d0", "#e4e6e2", "#a9aca8"));
  scene.add(new THREE.AmbientLight(0xe6ece8, 0.55));
  for (const z of [-4, -12, -20]) {
    const l = new THREE.PointLight(0xf7f4ea, 60, 26, 1.6); l.position.set(0, 3.6, z); scene.add(l);
    const tube = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.06, 2.4), new THREE.MeshBasicMaterial({ color: 0xfffdf5 }));
    tube.position.set(0, 3.95, z); scene.add(tube);
  }
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(8, 60), new THREE.MeshStandardMaterial({ color: 0x8a8f94, roughness: 0.55, metalness: 0.1 }));
  floor.rotation.x = -Math.PI / 2; floor.position.z = -20; floor.receiveShadow = true; scene.add(floor);
  const line = new THREE.Mesh(new THREE.PlaneGeometry(0.12, 60), new THREE.MeshStandardMaterial({ color: 0xe8e4c8 }));
  line.rotation.x = -Math.PI / 2; line.position.set(0.9, 0.01, -20); scene.add(line);
  const ceiling = new THREE.Mesh(new THREE.PlaneGeometry(8, 60), new THREE.MeshStandardMaterial({ color: 0xc9cbc6 }));
  ceiling.rotation.x = Math.PI / 2; ceiling.position.set(0, 4, -20); scene.add(ceiling);
  const back = new THREE.Mesh(new THREE.PlaneGeometry(8, 4), new THREE.MeshStandardMaterial({ color: 0x9ca09a }));
  back.position.set(0, 2, -44); scene.add(back);
  const cabinet = new THREE.MeshStandardMaterial({ color: 0xc8c6bc, roughness: 0.6, metalness: 0.2 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x2a2c2c, roughness: 0.5 });
  for (const side of [-1, 1]) {
    for (let i = 0; i < 26; i++) {
      const z = -1 - i * 1.6;
      const cab = new THREE.Mesh(new THREE.BoxGeometry(0.9, 3.2, 1.5), cabinet);
      cab.position.set(side * 2.6, 1.6, z); cab.castShadow = true; cab.receiveShadow = true; scene.add(cab);
      const seam = new THREE.Mesh(new THREE.BoxGeometry(0.92, 3.2, 0.04), dark);
      seam.position.set(side * 2.6, 1.6, z - 0.76); scene.add(seam);
      for (let k = 0; k < 3; k++) {
        const panel = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.32, 0.4), dark);
        panel.position.set(side * (2.6 - 0.46), 2.6 - k * 0.8, z + range(-0.2, 0.2)); scene.add(panel);
        const led = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 8), new THREE.MeshBasicMaterial({ color: rand() < 0.6 ? 0xff3b30 : 0x34c759 }));
        led.position.set(side * (2.6 - 0.47), 2.2 - k * 0.8, z + range(-0.3, 0.3)); scene.add(led);
      }
    }
  }
  const camera = new THREE.PerspectiveCamera(58, W / H, 0.1, 200);
  camera.position.set(0.6, 1.7, 2.4);
  camera.lookAt(-0.2, 1.4, -20);
  return { scene, camera };
};

// Transmission pylon over a misty field at dusk (capabilities hero, anomalies row).
function lattice(height = 40, base = 8) {
  const group = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color: 0x2a2f30, metalness: 0.7, roughness: 0.45 });
  const bar = (a, b, r = 0.12) => {
    const d = new THREE.Vector3().subVectors(b, a);
    const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, d.length(), 6), mat);
    m.position.copy(a).addScaledVector(d, 0.5);
    m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.clone().normalize());
    group.add(m);
  };
  const levels = 12;
  const corner = (y, s) => [[-s, y, -s], [s, y, -s], [s, y, s], [-s, y, s]].map(p => new THREE.Vector3(...p));
  let prev = corner(0, base / 2);
  for (let i = 1; i <= levels; i++) {
    const y = (height * i) / levels;
    const s = (base / 2) * (1 - (0.8 * i) / levels);
    const cur = corner(y, s);
    for (let k = 0; k < 4; k++) {
      bar(prev[k], cur[k], 0.16);
      bar(prev[k], cur[(k + 1) % 4], 0.07);
      bar(cur[k], cur[(k + 1) % 4], 0.07);
    }
    prev = cur;
  }
  for (const y of [height * 0.62, height * 0.82]) {
    bar(new THREE.Vector3(-9, y, 0), new THREE.Vector3(9, y, 0), 0.14);
    for (const x of [-8.5, 8.5]) bar(new THREE.Vector3(x, y, 0), new THREE.Vector3(x, y - 2, 0), 0.05);
  }
  return group;
}

scenes["pylon-dusk"] = () => {
  const scene = new THREE.Scene();
  const sky = skyTexture("#2e3a3f", "#68797a", "#b4aa8c", { x: 0.3, y: 0.85, r: 0.3, color: "rgba(255,220,170,0.35)" });
  scene.background = sky;
  scene.fog = new THREE.Fog("#6f7b74", 30, 300);
  envFromSky(scene, sky);
  scene.add(new THREE.HemisphereLight(0x8fa0a4, 0x1d2a1a, 0.8));
  sunLight(scene, 0xffd9a8, 1.6, [-80, 30, -120], 160);
  ground(scene, grassTexture("#2f4a22", [100, 100]));
  const pylon = lattice(42, 9); pylon.position.set(14, 0, -40); scene.add(pylon);
  const far = lattice(42, 9); far.position.set(70, 0, -190); scene.add(far);
  const wire = new THREE.MeshBasicMaterial({ color: 0x1f2426 });
  for (const y of [26, 34.4]) for (const x of [-8.5, 8.5]) {
    const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(14 + x, y - 2, -40), new THREE.Vector3(40 + x, y - 9, -115), new THREE.Vector3(70 + x, y - 2, -190));
    scene.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 40, 0.06, 4), wire));
    const back = new THREE.QuadraticBezierCurve3(new THREE.Vector3(14 + x, y - 2, -40), new THREE.Vector3(-6 + x, y - 9, 30), new THREE.Vector3(-30 + x, y - 4, 110));
    scene.add(new THREE.Mesh(new THREE.TubeGeometry(back, 40, 0.06, 4), wire));
  }
  const panel = panelTexture(6, 12, "#122046");
  for (let r = 0; r < 6; r++) { const row = pvRow(60, { panelTex: panel }); row.position.set(-30, 0, -r * 6 + 10); row.rotation.y = 0.2; scene.add(row); }
  const camera = new THREE.PerspectiveCamera(50, W / H, 0.5, 2000);
  camera.position.set(-28, 6, 48);
  camera.lookAt(10, 16, -40);
  return { scene, camera };
};

// Low-angle close-up across modules with warm sun glare (audience section, replaces the reference's worker photo).
scenes["pv-closeup"] = () => {
  const scene = new THREE.Scene();
  const sky = skyTexture("#6f8fb8", "#c8cfd6", "#f4e2b8", { x: 0.85, y: 0.25, r: 0.25, color: "rgba(255,240,200,0.95)" });
  scene.background = sky;
  envFromSky(scene, sky);
  scene.add(new THREE.HemisphereLight(0xf0f4ff, 0x6b6a52, 0.8));
  sunLight(scene, 0xffe7b8, 2.6, [30, 22, -30], 40);
  ground(scene, grassTexture("#4a6a2e", [60, 60]));
  const panel = panelTexture(6, 10, "#14225a");
  for (let r = 0; r < 4; r++) {
    const row = pvRow(30, { panelTex: panel, tilt: 0.3, depth: 2.6, height: 0.9 });
    row.position.set(0, 0, -r * 3.4); scene.add(row);
  }
  const flare = new THREE.Sprite(new THREE.SpriteMaterial({ map: canvasTexture(256, 256, (ctx, w, h) => {
    const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    g.addColorStop(0, "rgba(255,250,230,1)"); g.addColorStop(0.2, "rgba(255,230,170,0.6)"); g.addColorStop(1, "rgba(255,200,120,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  }), blending: THREE.AdditiveBlending, depthWrite: false }));
  flare.scale.set(30, 30, 1); flare.position.set(40, 26, -60); scene.add(flare);
  const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 500);
  camera.position.set(-6, 3.4, 5.5);
  camera.lookAt(4, 0.4, -4);
  return { scene, camera };
};

const { scene, camera } = scenes[sceneName]();
renderer.render(scene, camera);
// Render twice so PMREM and shadow maps are settled.
requestAnimationFrame(() => {
  renderer.render(scene, camera);
  document.body.dataset.done = "1";
});
