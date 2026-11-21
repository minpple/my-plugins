#!/usr/bin/env python3
"""Archive a task folder: copy it into `archive/<time>-<name>/` and compare the copy (architecture 4.8.1).

usage: archive.py --task TASK_FOLDER --name NAME [--only FILE ...]

Makes `<task folder>/archive/<yymmdd-HHMMSS>-<NAME>/` (the time comes from the clock; a folder of that name that
already exists gets `-b`, `-c` … appended), copies into it and compares every copied file byte for byte with its
source. Without --only it copies the whole task folder except `archive/` (the "Archive" of recorder.md, for
`rev<N>-draft`, `rev<N>`, `rev<N>-profile`); with --only it copies the named files of the task folder that exist
(Back to Execute and a Review-only rerun: `--name run<N> --only verify.md review.md changed-files.md`; a Scope Review
`REVISE`: `--name scope-run<N> --only scope-review.md`). File times are kept, as `cp -p` does.
Prints one line, the folder relative to the task folder (`archive/261116-002752-rev0-draft`), which is the value of
`archive=` on the run-log line.
exit: 0 copied and equal; 1 nothing to archive (no named file exists), the folder is not written; 2 bad arguments
or no such task folder; 3 the copy failed or differs from its source (one line with the cause; stop and report).
"""
import argparse
import filecmp
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

NAME = re.compile(r'[A-Za-z0-9._-]+')
ARCHIVE = 'archive'


def say(text: str, code: int) -> int:
    print(f'archive: {text}')
    return code


def target(task: Path, name: str) -> Path:
    """A folder under archive/ that does not exist yet: `<time>-<name>`, then `-b`, `-c` …"""
    base = f'{datetime.now():%y%m%d-%H%M%S}-{name}'
    for suffix in [''] + [f'-{chr(c)}' for c in range(ord('b'), ord('z') + 1)]:
        folder = task / ARCHIVE / (base + suffix)
        if not folder.exists():
            return folder
    raise OSError(f'too many archives named {base}')


def sources(task: Path, only):
    """Relative paths of the files to copy, sorted."""
    if only is not None:
        return sorted(n for n in only if (task / n).is_file())
    return sorted(p.relative_to(task).as_posix() for p in task.rglob('*')
                  if p.is_file() and p.relative_to(task).parts[0] != ARCHIVE)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--task', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--only', nargs='+')
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    task = Path(args.task).resolve()
    if not (task / 'intake.md').is_file():
        return say(f'no such task folder {task}', 2)
    if not NAME.fullmatch(args.name) or args.name in ('.', '..'):
        return say(f'bad --name {args.name!r} (letters, digits, `.`, `_`, `-`)', 2)
    for n in args.only or []:
        parts = Path(n).parts
        if Path(n).is_absolute() or '..' in parts or not parts or parts[0] == ARCHIVE:
            return say(f'bad --only {n!r} (a file of the task folder, not under {ARCHIVE}/)', 2)
    names = sources(task, args.only)
    if not names:
        return say('nothing to archive', 1)
    try:
        folder = target(task, args.name)
        for n in names:
            (folder / n).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(task / n, folder / n)
        differ = [n for n in names if not filecmp.cmp(task / n, folder / n, shallow=False)]
    except OSError as exc:
        return say(f'cannot copy: {exc}', 3)
    if differ:
        return say(f'the copy differs from its source: {", ".join(differ)} ({folder})', 3)
    print(folder.relative_to(task).as_posix())
    return 0


if __name__ == '__main__':
    sys.exit(main())
