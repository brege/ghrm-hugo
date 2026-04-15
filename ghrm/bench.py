from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import ROOT_DIR
from .common import kill_process


@dataclass
class BenchCase:
    label: str
    kind: str
    target: str


class BenchRunner:
    def __init__(self, open_browser: bool | None) -> None:
        self.open_browser = open_browser
        self.root = ROOT_DIR
        self.ghrm_bin = self.root / "bin" / "ghrm"
        self.runs = int(os.environ.get("BENCH_RUNS", "3"))
        self.warmups = int(os.environ.get("BENCH_WARMUPS", "1"))
        self.timeout_seconds = int(os.environ.get("BENCH_TIMEOUT_SECONDS", "30"))
        self.env_file = Path(os.environ.get("BENCH_ENV_FILE", str(self.root / ".env")))
        self.labels: list[str] = []
        self.ready_avgs: list[int] = []
        self.build_avgs: list[int] = []

    def run(self) -> int:
        values = self.load_env()
        cases = [
            BenchCase("site", "hugo", values["BENCH_SITE_DIR"]),
            BenchCase("demo", "hugo", values["BENCH_DEMO_DIR"]),
            BenchCase("ghrm", "ghrm", values["BENCH_README_FILE"]),
        ]
        for case in cases:
            self.bench_case(case)
        self.print_summary()
        return 0

    def load_env(self) -> dict[str, str]:
        if not self.env_file.is_file():
            raise SystemExit(
                f"error: missing env file: {self.env_file}\n"
                "copy .env.example to .env and set benchmark paths"
            )
        values: dict[str, str] = {}
        for line in self.env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, value = stripped.split("=", 1)
            values[key] = value
        for key in ("BENCH_SITE_DIR", "BENCH_DEMO_DIR", "BENCH_README_FILE"):
            values[key] = os.environ.get(key, values.get(key, ""))
            if not values[key]:
                raise SystemExit(f"error: {key} is not set")
        self.runs = int(os.environ.get("BENCH_RUNS", str(self.runs)))
        self.warmups = int(os.environ.get("BENCH_WARMUPS", str(self.warmups)))
        self.timeout_seconds = int(os.environ.get("BENCH_TIMEOUT_SECONDS", str(self.timeout_seconds)))
        if self.open_browser is None:
            self.open_browser = os.environ.get("BENCH_OPEN_BROWSER", "0") == "1"
        return values

    def bench_case(self, case: BenchCase) -> None:
        print(f"\n{case.label}")
        print(f"  target: {case.target}")
        sum_ready = 0
        sum_build = 0
        min_ready = 0
        max_ready = 0

        for run in range(1, self.warmups + 1):
            ready, build = self.measure(case)
            print(f"  warmup {run}: ready={ready}ms build={build}ms")

        for run in range(1, self.runs + 1):
            ready, build = self.measure(case)
            print(f"  run {run}: ready={ready}ms build={build}ms")
            sum_ready += ready
            sum_build += build
            min_ready = ready if min_ready == 0 else min(min_ready, ready)
            max_ready = max(max_ready, ready)

        self.labels.append(case.label)
        self.ready_avgs.append(sum_ready // self.runs)
        self.build_avgs.append(sum_build // self.runs)
        print(
            f"  avg ready={sum_ready // self.runs}ms "
            f"min={min_ready}ms max={max_ready}ms avg build={sum_build // self.runs}ms"
        )

    def measure(self, case: BenchCase) -> tuple[int, int]:
        with tempfile.NamedTemporaryFile(prefix="ghrm-bench-", suffix=".log", delete=False) as handle:
            log = Path(handle.name)
        proc = self.start(case, log)
        start = time.monotonic_ns()
        deadline = time.monotonic() + self.timeout_seconds
        try:
            while time.monotonic() < deadline:
                text = log.read_text(encoding="utf-8", errors="replace")
                if "Web Server is available at" in text:
                    ready_ms = (time.monotonic_ns() - start) // 1_000_000
                    return int(ready_ms), self.build_ms(text)
                if proc.poll() is not None:
                    raise SystemExit(f"error: benchmark target exited early: {case.target}\n{text}")
                time.sleep(0.02)
            raise SystemExit(f"error: timed out waiting for ready state: {case.target}\n{log.read_text()}")
        finally:
            kill_process(proc)
            log.unlink(missing_ok=True)

    def start(self, case: BenchCase, log: Path) -> subprocess.Popen[str]:
        env = os.environ.copy()
        stdout = log.open("w", encoding="utf-8")
        if case.kind == "hugo":
            cmd = ["hugo", "server"]
            if self.open_browser:
                cmd.append("--openBrowser")
            return subprocess.Popen(cmd, cwd=case.target, stdout=stdout, stderr=subprocess.STDOUT, text=True, env=env)
        if not self.open_browser:
            env["GHRM_OPEN"] = "0"
        return subprocess.Popen(
            [str(self.ghrm_bin), case.target],
            cwd=self.root,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )

    def build_ms(self, text: str) -> int:
        matches = re.findall(r"Built in (\d+) ms", text)
        return int(matches[-1]) if matches else 0

    def print_summary(self) -> None:
        print("\nSummary")
        print(f"{'case':<18} {'ready_avg':>10} {'build_avg':>10}")
        for label, ready, build in zip(self.labels, self.ready_avgs, self.build_avgs):
            print(f"{label:<18} {f'{ready}ms':>10} {f'{build}ms':>10}")
        if len(self.labels) >= 3:
            print("\nComparison")
            print(f"  ghrm minus site ready avg: {self.ready_avgs[2] - self.ready_avgs[0]}ms")
            print(f"  ghrm minus demo ready avg: {self.ready_avgs[2] - self.ready_avgs[1]}ms")
            print(f"  demo minus site ready avg: {self.ready_avgs[1] - self.ready_avgs[0]}ms")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench")
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    open_browser = True if args.open_browser else None
    return BenchRunner(open_browser=open_browser).run()


if __name__ == "__main__":
    raise SystemExit(main())
