from __future__ import annotations

import hashlib
import os
import signal
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Callable, Iterable


EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


def real_target(target: str) -> Path:
    return Path(target).expanduser().resolve()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_markdown(path: str | Path) -> bool:
    return Path(path).suffix in {".md", ".MD"}


def markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS]
        current_path = Path(current)
        for name in names:
            path = current_path / name
            if is_markdown(path) and path.is_file():
                files.append(path)
    files.sort()
    return files


def markdown_state(root: Path) -> tuple[tuple[int, str], ...]:
    return tuple(
        (int(path.stat().st_mtime_ns), str(path))
        for path in markdown_files(root)
    )


def asset_state(paths: Iterable[Path]) -> tuple[tuple[int, str], ...]:
    items: list[tuple[int, str]] = []
    for path in sorted({path.resolve(strict=False) for path in paths}):
        try:
            mtime = int(path.stat().st_mtime_ns)
        except OSError:
            mtime = -1
        items.append((mtime, str(path)))
    return tuple(items)


def find_binary(name: str) -> str | None:
    return shutil.which(name)


def choose_port(start: int) -> int:
    port = start
    ss = find_binary("ss")
    if ss is None:
        return port

    while True:
        proc = subprocess.run(
            [ss, "-tln", f"sport = :{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if str(port) not in proc.stdout:
            return port
        port += 1


def kill_process(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait()


@dataclass
class PollWatcher:
    root: Path
    on_change: Callable[[], None]
    assets: Callable[[], set[Path]] | None = None
    interval: float = 1.0

    def __post_init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        state = (markdown_state(self.root), asset_state(self.assets() if self.assets is not None else ()))
        while not self._stop.wait(self.interval):
            current = (markdown_state(self.root), asset_state(self.assets() if self.assets is not None else ()))
            if current == state:
                continue
            state = current
            self.on_change()


class InotifyWatcher:
    def __init__(
        self,
        root: Path,
        on_change: Callable[[], None],
        assets: Callable[[], set[Path]] | None = None,
    ) -> None:
        self.root = root
        self.on_change = on_change
        self.assets = assets
        self.proc: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()

    def start(self) -> None:
        inotifywait = find_binary("inotifywait")
        if inotifywait is None:
            raise RuntimeError("inotifywait not available")

        self.proc = subprocess.Popen(
            [
                inotifywait,
                "--monitor",
                "--recursive",
                "--quiet",
                "--event",
                "close_write,moved_to,create,delete",
                "--format",
                "%w%f",
                str(self.root),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        kill_process(self.proc)
        if self.thread is not None:
            self.thread.join(timeout=2)

    def _run(self) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            if self.stop_event.is_set():
                return
            path = Path(line.strip()).resolve(strict=False)
            if is_markdown(path) or (self.assets is not None and path in self.assets()):
                self.on_change()


def build_watcher(
    root: Path,
    on_change: Callable[[], None],
    assets: Callable[[], set[Path]] | None = None,
):
    if find_binary("inotifywait") is not None:
        watcher = InotifyWatcher(root, on_change, assets=assets)
        watcher.start()
        return watcher
    watcher = PollWatcher(root, on_change, assets=assets)
    watcher.start()
    return watcher
