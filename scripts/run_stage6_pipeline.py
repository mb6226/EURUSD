"""Optional Stage-5 -> Stage-6 orchestration entry point."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stage-6 governance, optionally refreshing the Stage-5 walk-forward first."
    )
    parser.add_argument("--refresh-stage5", action="store_true",
                        help="Run the complete Stage-5 chronological simulation before Stage-6 evaluation.")
    parser.add_argument("--min-train-days", type=int, default=180)
    parser.add_argument("--retrain-every", type=int, default=5)
    parser.add_argument("--min-evaluated", type=int, default=250)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    args = parser.parse_args()

    if args.refresh_stage5:
        command = [
            sys.executable, str(ROOT / "scripts/run_elliott_walk_forward.py"),
            "--min-train-days", str(args.min_train_days),
            "--retrain-every", str(args.retrain_every),
        ]
        print("Running Stage 5 before Stage 6:", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)

    command = [
        sys.executable, str(ROOT / "scripts/stage6_evaluate_and_govern.py"),
        "--min-evaluated", str(args.min_evaluated),
        "--bootstrap-samples", str(args.bootstrap_samples),
    ]
    print("Running Stage 6 governance:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
