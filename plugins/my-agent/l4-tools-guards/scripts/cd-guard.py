#!/usr/bin/env python3
"""Keep the session out of the coder worktrees of a task location (architecture 4.6 "Session folder guard").

usage: cd-guard.py --location TASK_LOCATION --task TASK_FOLDER
       cd-guard.py --remove --location TASK_LOCATION --task TASK_FOLDER

Adds the deny rule `Cd(/<resolved location>/.claude/worktrees/agent-*/**)` to
`<location>/.claude/settings.local.json` (`permissions.deny`), creating the file when it is missing and keeping
everything else in it. Claude Code checks `Cd(...)` rules on every move of a session's folder (`/cd` and a host's
move request), so a move into `agent-<id>` is refused; a coder starts in its worktree and is not affected, and
`task-<id>` worktrees do not match. In a git repository that does not ignore the file yet, the line
`.claude/settings.local.json` is added to the clone's `info/exclude`, so the file stays out of the task's commit.

Prints one line: `cd-guard: present`, or `cd-guard: added <rule> to <file> (<startup warning note>)` (then ` (new file: …)`
when the file was created and `; excluded from git` when the exclude line was written), or `cd-guard: not added: <cause>`.
The note says Claude Code may warn at startup that the rule matches no tool (`Cd` is not a model-callable tool) and that
the rule still works.
When it really adds the rule it first writes `<TASK_FOLDER>/cd-guard.json` (`{"file": …, "rule": …}`) and then the settings
file, so a rule is never there without a record. `present` (the rule was already there, for example the person's own)
writes no record.

`--remove` takes one occurrence of the recorded rule out of `permissions.deny` of the recorded `file` (`<location>/.claude/settings.local.json`
when the record has none) and keeps every other key and entry
(an empty `deny` list too). It never deletes the record and touches nothing else in the task folder. It prints one line:
`cd-guard: removed <rule> from <file>`, `cd-guard: nothing to remove (<no record | rule not in file | file absent>)`, or
`cd-guard: not removed: <cause>` (invalid JSON, not a JSON object, a `deny` that is not a list, a failed write; the file
stays as it was).
exit: 0 added, present, removed or nothing to remove, 1 not added or not removed (the settings file is left as it was),
2 bad arguments.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

FILE = Path('.claude') / 'settings.local.json'
WARNING = ' (Claude Code may warn at startup that this rule matches no tool; the rule still works)'
NEW = ' (new file: Claude Code may read it only in sessions started after this)'
RULE_BREAKERS = '()*?[]{}\n'


def rule_for(location: Path) -> str:
    return f'Cd(/{location.as_posix()}/.claude/worktrees/agent-*/**)'


RECORD = 'cd-guard.json'


def fail(cause: str, verb: str = 'added') -> int:
    print(f'cd-guard: not {verb}: {cause}')
    return 1


def write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + '.tmp')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def remove(location: Path, task: Path) -> int:
    """Take the recorded rule out of the settings file; every other entry stays."""
    def no(cause):
        return fail(cause, 'removed')
    try:
        record = json.loads((task / RECORD).read_text(encoding='utf-8'))
        rule, file = record['rule'], record.get('file')
        if not isinstance(rule, str) or not rule or not (file is None or isinstance(file, str) and file):
            raise ValueError
    except FileNotFoundError:
        print('cd-guard: nothing to remove (no record)')
        return 0
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return no(f'{task / RECORD} cannot be read as a record')
    path = Path(file) if file else location / FILE   # where the rule was written
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        print('cd-guard: nothing to remove (file absent)')
        return 0
    except (OSError, UnicodeDecodeError, ValueError):
        return no(f'{path} cannot be read as JSON')
    if not isinstance(data, dict):
        return no(f'{path} is not a JSON object')
    permissions = data.get('permissions', {})
    if not isinstance(permissions, dict) or not isinstance(permissions.get('deny', []), list):
        return no(f'`permissions.deny` in {path} is not a list')
    deny = permissions.get('deny', [])
    if rule not in deny:
        print('cd-guard: nothing to remove (rule not in file)')
        return 0
    deny.remove(rule)
    try:
        write_json(path, data)
    except OSError as e:
        return no(f'cannot write {path} ({e.strerror or e})')
    print(f'cd-guard: removed {rule} from {path}')
    return 0


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
    ap.add_argument('--task', required=True)
    ap.add_argument('--remove', action='store_true')
    args = ap.parse_args()
    verb = 'removed' if args.remove else 'added'
    if os.name == 'nt':
        return fail('not supported on Windows', verb)
    try:
        location = Path(args.location).expanduser().resolve()
        task = Path(args.task).expanduser().resolve()
    except (OSError, RuntimeError):
        return fail(f'cannot resolve {args.location} or {args.task}', verb)
    if not location.is_dir():
        return fail(f'{location} is not a folder', verb)
    if args.remove:
        return remove(location, task)
    if not task.is_dir():
        return fail(f'{task} is not a folder')
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
    try:
        write_json(task / RECORD, {'file': str(path), 'rule': rule})   # the record first
        write_json(path, data)
    except OSError as e:
        return fail(f'cannot write {path} ({e.strerror or e})')
    excluded = exclude_from_git(location)
    print(f'cd-guard: added {rule} to {path}{WARNING}' + (NEW if new else '') + ('; excluded from git' if excluded else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
