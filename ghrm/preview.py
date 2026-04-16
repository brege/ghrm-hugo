from __future__ import annotations

import argparse
import os
import signal
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from . import THEME_DIR, VENDOR_DIR
from .common import build_watcher, choose_port, is_markdown, kill_process, real_target, sha256_text
from .stage import StageBuilder


REQUIRED_ASSETS = [
    "mermaid.js",
    "mermaid-version.txt",
    "svg-pan-zoom.min.js",
    "katex/katex.min.css",
    "katex/katex.min.js",
    "katex/auto-render.min.js",
    "leaflet/leaflet.css",
    "leaflet/leaflet.js",
    "topojson-client.min.js",
]


@dataclass
class PreviewConfig:
    target: Path
    mode: str
    cache_home: Path
    port: int
    bind: str
    open_browser: bool

    @property
    def cache_dir(self) -> Path:
        return self.cache_home / "ghrm"

    @property
    def hugo_cache_dir(self) -> Path:
        return self.cache_dir / "hugo"

    @property
    def target_key(self) -> str:
        return sha256_text(f"{self.mode}:{self.target}")

    @property
    def site_dir(self) -> Path:
        return self.cache_dir / "sites" / self.target_key

    @property
    def content_dir(self) -> Path:
        return self.site_dir / "content"

    @property
    def static_dir(self) -> Path:
        return self.site_dir / "static"

    @property
    def layouts_dir(self) -> Path:
        return self.site_dir / "layouts"

    @property
    def shortcodes_dir(self) -> Path:
        return self.layouts_dir / "shortcodes"


class PreviewApp:
    def __init__(self, config: PreviewConfig) -> None:
        self.config = config
        self.hugo: subprocess.Popen[str] | None = None
        self.watcher = None
        self.lock = threading.Lock()
        self.stopping = threading.Event()

    def run(self) -> int:
        self.validate()
        self.prepare_site()
        self.sync_target()
        self.write_config()
        self.watcher = build_watcher(self.watch_root(), self.sync_target)
        self.start_hugo()
        self.install_signals()
        return self.wait()

    def browser_host(self) -> str:
        if self.config.bind in {"0.0.0.0", "::"}:
            return "localhost"
        return self.config.bind

    def validate(self) -> None:
        if shutil.which("hugo") is None:
            raise SystemExit("error: hugo not found in PATH")
        for rel in REQUIRED_ASSETS:
            path = VENDOR_DIR / rel
            if not path.is_file():
                raise SystemExit(
                    f"error: missing vendor asset: {path}\n"
                    "run 'make assets' while online to refresh bundled dependencies"
                )

    def prepare_site(self) -> None:
        self.config.content_dir.mkdir(parents=True, exist_ok=True)
        self.config.static_dir.mkdir(parents=True, exist_ok=True)
        self.config.shortcodes_dir.mkdir(parents=True, exist_ok=True)
        self.config.hugo_cache_dir.mkdir(parents=True, exist_ok=True)
        themes_dir = self.config.site_dir / "themes"
        themes_dir.mkdir(parents=True, exist_ok=True)
        target = themes_dir / "gh-readme"
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(THEME_DIR)

    def sync_target(self) -> None:
        if self.stopping.is_set():
            return
        with self.lock:
            if self.stopping.is_set():
                return
            StageBuilder(
                mode=self.config.mode,
                target=self.config.target,
                content_dir=self.config.content_dir,
                shortcodes_dir=self.config.shortcodes_dir,
                static_dir=self.config.static_dir,
            ).run()

    def watch_root(self) -> Path:
        return self.config.target if self.config.mode == "dir" else self.config.target.parent

    def write_config(self) -> None:
        title = self.config.target.name if self.config.mode == "dir" else "README Preview"
        params = '\n[params]\n  dirMode = true\n' if self.config.mode == "dir" else "\n"
        disable_kinds = (
            'disableKinds = ["taxonomy", "term", "RSS", "sitemap", "robotsTXT", "404"]\n'
            if self.config.mode == "dir"
            else 'disableKinds = ["section", "taxonomy", "term", "RSS", "sitemap", "robotsTXT", "404"]\n'
        )
        static_mount = (
            f'[[module.mounts]]\n  source = "{self.config.target.parent}"\n  target = "static"\n'
            if self.config.mode == "file"
            else '[[module.mounts]]\n  source = "static"\n  target = "static"\n'
        )
        config = (
            f'baseURL = "http://{self.browser_host()}:{self.config.port}/"\n'
            f'title = "{title}"\n'
            'theme = "gh-readme"\n'
            'disablePathToLower = true\n'
            f"{disable_kinds}"
            'enableEmoji = true\n'
            f"{params}"
            '[markup.goldmark.renderer]\n  unsafe = true\n\n'
            '[markup.goldmark.extensions]\n'
            '  strikethrough = true\n'
            '  linkify = true\n'
            '  taskList = true\n'
            '  footnote = true\n'
            '  typographer = true\n\n'
            '[markup.highlight]\n  noClasses = false\n\n'
            '[[module.mounts]]\n  source = "themes/gh-readme/assets"\n  target = "assets"\n\n'
            '[[module.mounts]]\n  source = "content"\n  target = "content"\n\n'
            f"{static_mount}"
        )
        (self.config.site_dir / "hugo.toml").write_text(config, encoding="utf-8")

    def start_hugo(self) -> None:
        cmd = [
            "hugo",
            "server",
            "--source",
            str(self.config.site_dir),
            "--cacheDir",
            str(self.config.hugo_cache_dir),
            "--port",
            str(self.config.port),
            "--bind",
            self.config.bind,
            "--disableFastRender",
            "--renderToMemory",
            "--noBuildLock",
        ]
        if self.config.open_browser:
            cmd.append("--openBrowser")
        self.hugo = subprocess.Popen(cmd, start_new_session=True)

    def install_signals(self) -> None:
        def handle_term(_signum, _frame) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, handle_term)

    def wait(self) -> int:
        assert self.hugo is not None
        try:
            return self.hugo.wait()
        except KeyboardInterrupt:
            return 130
        finally:
            self.stop()

    def stop(self) -> None:
        self.stopping.set()
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
        kill_process(self.hugo)
        self.hugo = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghrm")
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("-p", "--port", type=int)
    parser.add_argument("-b", "--bind", default="127.0.0.1")
    args = parser.parse_args(argv)

    target = real_target(args.target)
    if target.is_dir():
        mode = "dir"
    elif target.is_file() and is_markdown(target):
        mode = "file"
    elif target.is_file():
        raise SystemExit(f"error: {target} is not a markdown file")
    else:
        raise SystemExit(f"error: {target} not found")

    cache_home = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    port = args.port if args.port is not None else choose_port(1313)
    app = PreviewApp(
        PreviewConfig(
            target=target,
            mode=mode,
            cache_home=cache_home,
            port=port,
            bind=args.bind,
            open_browser=os.environ.get("GHRM_OPEN", "1") != "0",
        )
    )
    return app.run()
