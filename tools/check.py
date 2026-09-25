"""The same offline checks run locally and in CI after locked dependency installation."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def uv_executable() -> str:
    executable = shutil.which("uv")
    if executable:
        return executable
    for relative in (".tools/Scripts/uv.exe", ".tools/bin/uv"):
        candidate = ROOT / relative
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("Install uv 0.12.19; see docs/DEVELOPMENT.md.")


def main() -> None:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise SystemExit("Install Node.js 24.15.0 or newer in the 24.x series.")
    uv = uv_executable()
    commands = [
        [uv, "lock", "--check", "--offline"],
        [uv, "run", "--locked", "--no-sync", "ruff", "check", "."],
        [uv, "run", "--locked", "--no-sync", "ruff", "format", "--check", "."],
        [uv, "run", "--locked", "--no-sync", "pytest", "--junitxml=build/reports/python.xml"],
        *[[npm, "run", task] for task in ("format:check", "lint", "test", "build")],
    ]
    for command in commands:
        print(f"\n> {' '.join(command)}", flush=True)
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
