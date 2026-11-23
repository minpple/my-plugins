#!/usr/bin/env python3
"""Bring the task folder of a task worktree back to the main checkout (architecture 4.6 "Task log copy back").

usage: task-log-copy.py --location TASK_LOCATION --task TASK_FOLDER

TASK_LOCATION is the folder the task runs in. It counts as a task worktree when it is a linked git worktree
(its `.git` is a `gitdir:` file) on a branch named `my-agent-task/<name>` (what `changes.md` "Task worktree" makes).
TASK_FOLDER is the absolute task folder `<TASK_LOCATION>/<task_dir>/<task-id>`.

Copies TASK_FOLDER to the same relative place in the main worktree of the repository (`<main>/<task_dir>/<task-id>`),
symbolic links as links. When `<main>/<task_dir>/.gitignore` is missing and the task location has one, that file is copied
too, so the copy stays out of git the way the task chose. Nothing in the task location is changed or deleted, and an
existing target is never overwritten.

Prints one line:
  `task-log-copy: copied <task folder> to <target>` (then ` (also .gitignore)` when that file was copied)
  `task-log-copy: nothing to do (<not a git work tree | not a linked worktree | branch is not my-agent-task/*>)`
  `task-log-copy: not copied: <cause>` (then `; cleanup incomplete: <path> (<reason>)[, ...]` for a part that
  could not be removed)
exit: 0 copied or nothing to do, 1 not copied (the cause is printed; nothing created by this run is left: the copied
`.gitignore`, the partial target and a records folder this run created in the main checkout are removed again, and a
part that cannot be removed is named after `; cleanup incomplete:`), 2 bad arguments.
"""
import argparse
import errno
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_active  # noqa: E402

BRANCH_PREFIX = 'my-agent-task/'


def say(text: str, code: int = 0) -> int:
    print(f'task-log-copy: {text}')
    return code


def branch_of(root: Path) -> str:
    try:
        r = subprocess.run(['git', '-C', str(root), 'branch', '--show-current'], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def run(location: Path, task: Path) -> int:
    location = location.resolve()
    task = task.resolve()
    if not (location / '.git').exists():
        return say('nothing to do (not a git work tree)')
    main = ma_active.main_worktree(location)
    if main is None:
        return say('nothing to do (not a linked worktree)')
    if not branch_of(location).startswith(BRANCH_PREFIX):
        return say(f'nothing to do (branch is not {BRANCH_PREFIX}*)')
    try:
        rel = task.relative_to(location)
    except ValueError:
        return say(f'not copied: {task} is not inside {location}', 1)
    if len(rel.parts) < 2:
        return say(f'not copied: {task} is not a task folder under a task_dir', 1)
    if not task.is_dir():
        return say(f'not copied: no such folder {task}', 1)
    main = main.resolve()
    target = main / rel
    if target.exists():
        return say(f'not copied: {target} exists already', 1)
    gitignore = None
    source_ignore = location / rel.parts[0] / '.gitignore'
    target_ignore = main / rel.parts[0] / '.gitignore'
    if source_ignore.is_file() and not target_ignore.exists():
        gitignore = (source_ignore, target_ignore)
    # What this run may create: folders from <main>/<task_dir> down to the target's parent that are missing now
    # (outermost first). Nothing that existed before is ever removed again.
    new_dirs = [d for d in reversed([target.parent, *target.parent.parents]) if main in d.parents and not d.exists()]
    try:
        if gitignore:
            target_ignore.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_ignore, target_ignore)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(task, target, symlinks=True)
    except OSError as e:
        left = []
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            pass
        except OSError as err:
            left.append(f'{target} ({err})')
        if gitignore and (target_ignore.exists() or target_ignore.is_symlink()):
            try:
                target_ignore.unlink()
            except OSError as err:
                left.append(f'{target_ignore} ({err})')
        for d in reversed(new_dirs):
            if not d.exists():
                continue
            try:
                os.rmdir(d)
            except OSError as err:
                left.append(f'{d} ({"not empty" if err.errno in (errno.ENOTEMPTY, errno.EEXIST) else err})')
        return say(f'not copied: {e}' + (f'; cleanup incomplete: {", ".join(left)}' if left else ''), 1)
    return say(f'copied {task} to {target}' + (' (also .gitignore)' if gitignore else ''))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--location', required=True)
    p.add_argument('--task', required=True)
    try:
        a = p.parse_args()
    except SystemExit:
        return 2
    return run(Path(a.location), Path(a.task))


if __name__ == '__main__':
    sys.exit(main())
