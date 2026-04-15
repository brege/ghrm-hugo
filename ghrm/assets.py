from __future__ import annotations

import argparse
import re
import urllib.request
from pathlib import Path

from . import VENDOR_DIR


FILES = [
    ("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.js", "mermaid.js"),
    ("https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.2/dist/svg-pan-zoom.min.js", "svg-pan-zoom.min.js"),
    ("https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css", "katex/katex.min.css"),
    ("https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js", "katex/katex.min.js"),
    ("https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js", "katex/auto-render.min.js"),
    ("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "leaflet/leaflet.css"),
    ("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "leaflet/leaflet.js"),
    ("https://unpkg.com/topojson-client@3/dist/topojson-client.min.js", "topojson-client.min.js"),
]

FONTS = [
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
]


class AssetSync:
    def __init__(self, refresh: bool) -> None:
        self.refresh = refresh

    def run(self) -> int:
        files = list(FILES)
        for font in FONTS:
            files.append(
                (
                    f"https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/fonts/{font}.woff2",
                    f"katex/fonts/{font}.woff2",
                )
            )
        for url, rel in files:
            self.fetch(url, rel)
        self.write_mermaid_version()
        return 0

    def fetch(self, url: str, rel: str) -> None:
        path = VENDOR_DIR / rel
        if not self.refresh and path.is_file():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url) as response:
            path.write_bytes(response.read())

    def write_mermaid_version(self) -> None:
        mermaid = (VENDOR_DIR / "mermaid.js").read_text(encoding="utf-8")
        match = re.search(r'version: "([^"]*)"', mermaid)
        version = match.group(1) if match else "unknown"
        (VENDOR_DIR / "mermaid-version.txt").write_text(f"{version}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assets")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    return AssetSync(refresh=args.refresh).run()


if __name__ == "__main__":
    raise SystemExit(main())
