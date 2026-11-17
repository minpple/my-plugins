#!/usr/bin/env python3
"""Print where a task location keeps its project blueprint and check the format of its files (architecture 4.7.5).

usage: blueprint.py check --loc <task location> [--data-dir X]

First line: `blueprint: <absolute folder>`, or `blueprint: off (the task location is the data folder)` when the
location is the data folder (a task outside any project keeps no blueprint; nothing else is printed, exit 0).
Then one `problem: <file>:<line> <what>` line per format problem, or the one line
`ok: features <n>, decisions <n>, backlog <n>` (entry counts; a missing file or folder counts 0).
It only reads. Exit 0 ok or off, 1 problems, 2 bad arguments.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_blueprint  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description='check the project blueprint of a task location')
    parser.add_argument('command', choices=['check'])
    parser.add_argument('--loc', required=True)
    parser.add_argument('--data-dir', default=None)
    args = parser.parse_args()
    location = Path(args.loc).expanduser()
    if not location.is_dir():
        print(f'blueprint: no such folder: {location}', file=sys.stderr)
        return 2
    folder = ma_blueprint.root(location.resolve(), args.data_dir)
    if folder is None:
        print('blueprint: off (the task location is the data folder)')
        return 0
    print(f'blueprint: {folder}')
    counts, problems = ma_blueprint.check(folder)
    if problems:
        print('\n'.join(f'problem: {p}' for p in problems))
        return 1
    print('ok: ' + ', '.join(f'{name[:-3]} {counts[name]}' for name in ma_blueprint.FILES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
