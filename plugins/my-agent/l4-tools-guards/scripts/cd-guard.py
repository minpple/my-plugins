#!/usr/bin/env python3
"""Keep the session out of the coder worktrees of a task location (architecture 4.6 "Session folder guard").

usage: cd-guard.py --location TASK_LOCATION

Adds the deny rule `Cd(/<resolved location>/.claude/worktrees/agent-*/**)` to
`<location>/.claude/settings.local.json` (`permissions.deny`), creating the file when it is missing and keeping
everything else in it. Claude Code checks `Cd(...)` rules on every move of a session's folder (`/cd` and a host's
move request), so a move into `agent-<id>` is refused; a coder starts in its worktree and is not affected, and
`task-<id>` worktrees do not match. In a git repository that does not ignore the file yet, the line
`.claude/settings.local.json` is added to the clone's `info/exclude`, so the file stays out of the task's commit.

Prints one line: `cd-guard: present`, or `cd-guard: added <rule> to <file>` (with ` (new file: …)` when the file was
created and `; excluded from git` when the exclude line was written), or `cd-guard: not added: <cause>`.
exit: 0 added or present, 1 not added (the settings file is left as it was), 2 bad arguments.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

FILE = Path('.claude') / 'settings.local.json'
NEW = ' (new file: Claude Code may read it only in sessions started after this)'
RULE_BREAKERS = '()*?[]{}\n'


def rule_for(location: Path) -> str:
    return f'Cd(/{location.as_posix()}/.claude/worktrees/agent-*/**)'


def fail(cause: str) -> int:
    print(f'cd-guard: not added: {cause}')
    return 1


def git(location: Path, *args):
    try:
        return subprocess.run(['git', '-C', str(location), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def exclude_from_git(location: Path) -> bool:
    """True when the exclude line was written now. Nothing is written outside a git repository, when git already
    ignores the file, or when git cannot be asked."""
    ignored = git(location, 'check-ignore', '-q', FILE.as_posix())
    if ignored is None or ignored.returncode != 1:   # 0 ignored, 128 not a repository
        return False
    where = git(location, 'rev-parse', '--git-path', 'info/exclude')
    if where is None or where.returncode != 0 or not where.stdout.strip():
        return False
    path = Path(where.stdout.strip())
    path = path if path.is_absolute() else location / path
    try:
        before = path.read_text(encoding='utf-8') if path.exists() else ''
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(before + ('' if before.endswith('\n') or not before else '\n') + FILE.as_posix() + '\n',
                        encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--location', required=True)
    args = ap.parse_args()
    if os.name == 'nt':
        return fail('not supported on Windows')
    try:
        location = Path(args.location).expanduser().resolve()
    except (OSError, RuntimeError):
        return fail(f'cannot resolve {args.location}')
    if not location.is_dir():
        return fail(f'{location} is not a folder')
    if any(c in str(location) for c in RULE_BREAKERS):
        return fail(f'{location} has characters a permission rule cannot hold')
    rule, path, new = rule_for(location), location / FILE, False
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        data, new = {}, True
    except (OSError, UnicodeDecodeError, ValueError):
        return fail(f'{path} cannot be read as JSON')
    if not isinstance(data, dict):
        return fail(f'{path} is not a JSON object')
    permissions = data.setdefault('permissions', {})
    if not isinstance(permissions, dict) or not isinstance(permissions.setdefault('deny', []), list):
        return fail(f'`permissions.deny` in {path} is not a list')
    if rule in permissions['deny']:
        print('cd-guard: present')
        return 0
    permissions['deny'].append(rule)
    tmp = path.with_name(path.name + '.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    except OSError as e:
        return fail(f'cannot write {path} ({e.strerror or e})')
    excluded = exclude_from_git(location)
    print(f'cd-guard: added {rule} to {path}' + (NEW if new else '') + ('; excluded from git' if excluded else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
