// Capture README screenshots of the running Puffin Copilot UI.
// Usage: node scripts/screenshots.mjs http://localhost:8799 ../../docs/images
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const base = process.argv[2] || "http://localhost:8799";
const outDir = resolve(process.argv[3] || "../../docs/images");
mkdirSync(outDir, { recursive: true });

const pages = [
  { path: "/dashboard/", file: "dashboard.png" },
  { path: "/train/", file: "train-studio.png" },
  { path: "/runs/", file: "runs.png" },
  { path: "/monitor/", file: "monitor.png" },
  { path: "/evaluate/", file: "evaluate.png" },
];

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2, // retina-crisp
  colorScheme: "dark",
});
const page = await ctx.newPage();

for (const { path, file } of pages) {
  const url = base + path;
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  } catch {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
  }
  // Let charts/tiles settle.
  await page.waitForTimeout(2500);
  const dest = resolve(outDir, file);
  await page.screenshot({ path: dest });
  console.log("saved", dest);
}

await browser.close();
