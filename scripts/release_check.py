from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Open Novel release readiness checks.")
    parser.add_argument(
        "--skip-final",
        action="store_true",
        help="Skip scripts/final_acceptance.py for a faster local release precheck.",
    )
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip frontend typecheck/build checks.",
    )
    return parser.parse_args()


def run_step(label: str, args: list[str]) -> None:
    print(f"\n==> {label}", flush=True)
    print(f"$ {shlex.join(args)}", flush=True)
    completed = subprocess.run(args, cwd=ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    args = parse_args()
    python = sys.executable

    run_step("unit tests", [python, "-m", "pytest", "-q"])
    run_step("lint", [python, "-m", "ruff", "check", "."])
    run_step("package check", [python, "scripts/package_check.py"])
    if not args.skip_frontend:
        run_step("frontend build", ["npm", "--prefix", "frontend", "run", "build"])

    if not args.skip_final:
        run_step("final acceptance", [python, "scripts/final_acceptance.py"])

    print("\nRELEASE_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
