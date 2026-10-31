// Render the generated SolarSleuth photography to public/images/*.jpg.
// Usage (from frontend/): node scripts/render-assets/render.mjs [scene ...]
// Needs the dev dependency `three` and a Playwright Chromium (any recent version).
import { createServer } from "vite";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch {
  ({ chromium } = require(path.join(process.env.NODE_PATH || "", "playwright")));
}

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, "../../public/images");

// name: [width, height, render scale]; rendered at scale then downsampled by the browser screenshot.
const SCENES = {
  "hero-aerial": [2400, 1350],
  "pv-topdown": [1920, 1080],
  "pv-landscape": [1600, 1000],
  "dusk-field": [1920, 1080],
  "switchgear-panel": [1600, 1200],
  "switchgear-room": [1600, 1000],
  "pylon-dusk": [1920, 1080],
  "pv-closeup": [1600, 1100],
};

const wanted = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SCENES);
const server = await createServer({ root: here, logLevel: "error", server: { port: 5199, strictPort: true } });
await server.listen();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
for (const name of wanted) {
  const [w, h] = SCENES[name];
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  page.on("pageerror", (error) => console.error(name, error.message));
  await page.goto(`http://localhost:5199/index.html?scene=${name}&w=${w}&h=${h}`, { waitUntil: "domcontentloaded", timeout: 180000 });
  await page.waitForFunction(() => document.body.dataset.done === "1", null, { timeout: 180000 });
  await page.screenshot({ path: path.join(out, `${name}.jpg`), type: "jpeg", quality: 80, timeout: 300000 });
  console.log("rendered", name, `${w}x${h}`);
  await page.close();
}
await browser.close();
await server.close();
