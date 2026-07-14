"""Keep the dashboard aligned with the Windows Codex process lifecycle."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:  # pragma: no cover - install.ps1 checks this dependency.
    psutil = None

from data_provider import clear_dismissal, is_manually_dismissed


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "scripts" / "dashboard.py"


def codex_processes() -> List[Tuple[int, int]]:
    if psutil is None:
        return []
    result: List[Tuple[int, int]] = []
    for process in psutil.process_iter(["pid", "name", "create_time", "exe"]):
        try:
            name = str(process.info.get("name") or "").lower()
            executable = str(process.info.get("exe") or "").lower()
            is_desktop_codex = (
                "openai.codex_" in executable
                and name in {"chatgpt.exe", "codex.exe", "codex"}
            )
            if not is_desktop_codex:
                continue
            result.append((int(process.info["pid"]), int(float(process.info["create_time"]) * 1000)))
        except (psutil.Error, KeyError, TypeError, ValueError):
            continue
    return sorted(result)


def lifecycle_for(processes: List[Tuple[int, int]]) -> Tuple[str, int]:
    started_at = min(start_time for _, start_time in processes)
    lifecycle_id = "|".join("{}:{}".format(pid, start_time) for pid, start_time in processes)
    return lifecycle_id, started_at


def python_gui() -> str:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else executable)


def start_dashboard(lifecycle_id: str, started_at: int) -> subprocess.Popen[Any]:
    environment = os.environ.copy()
    environment["CODEX_LIFECYCLE_ID"] = lifecycle_id
    environment["CODEX_STARTED_AT_MS"] = str(started_at)
    return subprocess.Popen(
        [python_gui(), str(DASHBOARD)],
        cwd=str(ROOT),
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def stop_dashboard(process: Optional[subprocess.Popen[Any]]) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=1.5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass


def main() -> None:
    dashboard: Optional[subprocess.Popen[Any]] = None
    active_lifecycle: Optional[str] = None
    restart_after = 0.0
    try:
        while True:
            processes = codex_processes()
            if not processes:
                stop_dashboard(dashboard)
                dashboard = None
                active_lifecycle = None
                clear_dismissal()
                time.sleep(2.0)
                continue

            lifecycle_id, started_at = lifecycle_for(processes)
            if lifecycle_id != active_lifecycle:
                stop_dashboard(dashboard)
                dashboard = None
                active_lifecycle = lifecycle_id
                restart_after = 0.0

            if (
                dashboard is None
                and time.monotonic() >= restart_after
                and not is_manually_dismissed(lifecycle_id)
            ):
                try:
                    dashboard = start_dashboard(lifecycle_id, started_at)
                except OSError:
                    restart_after = time.monotonic() + 10.0

            if dashboard is not None and dashboard.poll() is not None:
                dashboard = None
                # dashboard.py writes a dismissal marker when the close button is used.
                restart_after = time.monotonic() + 2.0
            time.sleep(2.0)
    except KeyboardInterrupt:
        stop_dashboard(dashboard)


if __name__ == "__main__":
    main()
