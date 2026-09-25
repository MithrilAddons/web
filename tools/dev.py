"""Run both loopback-only development servers; stop both on exit."""

import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    python = ROOT / (
        ".venv/Scripts/python.exe" if (ROOT / ".venv/Scripts").is_dir() else ".venv/bin/python"
    )
    node = shutil.which("node")
    vite = ROOT / "node_modules/vite/bin/vite.js"
    if not python.is_file() or not node or not vite.is_file():
        raise SystemExit("Install locked dependencies first; see docs/DEVELOPMENT.md.")
    commands = [
        [
            str(python),
            "-m",
            "uvicorn",
            "mithril_web.app:app",
            "--app-dir",
            "backend",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        [node, str(vite), "--config", "frontend/vite.config.ts"],
    ]
    processes = []
    try:
        for command in commands:
            processes.append(subprocess.Popen(command, cwd=ROOT))
        print("Open http://127.0.0.1:5173 — Ctrl+C stops both servers.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
        raise SystemExit("A development server exited; both have been stopped.")
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
