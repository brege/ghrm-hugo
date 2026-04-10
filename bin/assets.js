#!/usr/bin/env node
const fs = require("node:fs/promises");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const vendor = path.join(root, "theme/gh-readme/static/vendor");
const katex = [
  "KaTeX_AMS-Regular",
  "KaTeX_Caligraphic-Bold",
  "KaTeX_Caligraphic-Regular",
  "KaTeX_Fraktur-Bold",
  "KaTeX_Fraktur-Regular",
  "KaTeX_Main-Bold",
  "KaTeX_Main-BoldItalic",
  "KaTeX_Main-Italic",
  "KaTeX_Main-Regular",
  "KaTeX_Math-BoldItalic",
  "KaTeX_Math-Italic",
  "KaTeX_SansSerif-Bold",
  "KaTeX_SansSerif-Italic",
  "KaTeX_SansSerif-Regular",
  "KaTeX_Script-Regular",
  "KaTeX_Size1-Regular",
  "KaTeX_Size2-Regular",
  "KaTeX_Size3-Regular",
  "KaTeX_Size4-Regular",
  "KaTeX_Typewriter-Regular",
];

const files = [
  ["https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.js", "mermaid.js"],
  ["https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.2/dist/svg-pan-zoom.min.js", "svg-pan-zoom.min.js"],
  ["https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css", "katex/katex.min.css"],
  ["https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js", "katex/katex.min.js"],
  ["https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js", "katex/auto-render.min.js"],
  ["https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "leaflet/leaflet.css"],
  ["https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "leaflet/leaflet.js"],
  ["https://unpkg.com/topojson-client@3/dist/topojson-client.min.js", "topojson-client.min.js"],
  ...katex.map((font) => [
    "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/fonts/" + font + ".woff2",
    "katex/fonts/" + font + ".woff2",
  ]),
];

async function has(file) {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

async function get(url, rel) {
  const file = path.join(vendor, rel);
  if (await has(file)) {
    return;
  }

  const res = await fetch(url);
  if (!res.ok) {
    throw new Error("download failed: " + url);
  }

  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, Buffer.from(await res.arrayBuffer()));
}

async function writeVersion() {
  const file = path.join(vendor, "mermaid.js");
  const text = await fs.readFile(file, "utf8");
  const match = text.match(/version:\s*"([^"]+)"/);
  const version = match ? match[1] : "unknown";
  await fs.writeFile(path.join(vendor, "mermaid-version.txt"), version + "\n");
}

async function main() {
  await Promise.all(files.map(([url, rel]) => get(url, rel)));
  await writeVersion();
}

main().catch((error) => {
  console.error("error: " + error.message);
  process.exit(1);
});
