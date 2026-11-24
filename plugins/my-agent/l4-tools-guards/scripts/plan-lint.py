#!/usr/bin/env python3
"""Plan gaps before G1b (architecture 4.4 "Plan gaps"): the format checks a plan must pass to be approved.

usage: plan-lint.py --task TASK_FOLDER

Reads intake.md (`Profile:`), scope.md (if any) and plan.md of the task folder and prints `plan-lint: ok`, or one
`plan-lint: FAIL <gap>` line per gap (`ma_schema.plan_gaps`): a completion criterion without one of the four check
tags, in the dev profile a `[check: command]` criterion that no work unit listing it marks with `(criterion <n>)`,
a `(background b<n>)` mark in plan.md whose `b<n>` is not an ID under `## Background research` in scope.md,
and a `Files to change` path in the task records folder (a coder cannot write there).
The G1b hook (`plan-approved-check.py`) runs the same check on the write of the `Approved` line.
exit: 0 no gap, 1 a gap or plan.md missing, 2 bad arguments.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_plan  # noqa: E402
import ma_schema  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--task', required=True)
    args = ap.parse_args(argv)
    task = Path(args.task).expanduser()
    plan = ma_plan.read(task / 'plan.md')
    if not plan.strip():
        print(f'plan-lint: FAIL {task / "plan.md"} is missing or empty')
        return 1
    gaps = ma_plan.gaps(task, plan)
    for gap in gaps:
        print(f'plan-lint: FAIL {gap}')
    if not gaps:
        print('plan-lint: ok')
    return 1 if gaps else 0


if __name__ == '__main__':
    sys.exit(main())
