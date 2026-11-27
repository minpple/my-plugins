"""Check commands, working-tree fingerprint and check-record status (shared by check-commands.py and changed-files.py).

The check record `<task folder>/checks.md` is written only by `check-commands.py`:

    # Check record: <task-id>
    Fingerprint: head=<40 hex | none> files=<12 hex> paths=<n>
    Taken: <YYYY-MM-DD HH:MM:SS>
    Result: <n> run, <f> failed, <k> not run

    - 01 `<command>` (<source>) → exit <code> | <summary> | <secs> s | checks/01.log
    - 02 `<command>` (<source>) → timeout after <n> s | <summary> | <n> s | checks/02.log
    - 03 `<command>` (<source>) → not run (scope: Environment: <reason>)

    ## Fingerprint paths
    - <path relative to the git root> <12 hex | deleted>

The second line is `Fingerprint: none (not a git location)`, `Fingerprint: none (tree changed by the run: <n> paths)` or
`Fingerprint: none (git status failed after the run)` when there is no fingerprint; then there is no `## Fingerprint paths`
section.

The fingerprint is taken from `git status --porcelain=v1 -z -uall` (every changed, deleted or untracked file, both paths of a
rename), without the task records folder; each path is hashed with `file_fp`; `files=` is the first 12 hex characters of sha1
over the sorted lines `<path>\\t<fp>\\n`; `head=` is `git rev-parse HEAD` or `none`. Git-ignored files are not in it.

`status` compares the record with the current tree: `current`, `stale (HEAD moved)`, `stale (<n> paths differ: <paths>)`,
`missing`, `no fingerprint`, or `not needed (no check commands)`.
"""
import hashlib
import math
import re
import subprocess
from pathlib import Path

import ma_schema

MIN_LIMIT = 60        # seconds: the floor of a command's time limit
DEFAULT_LIMIT = 600   # seconds: the limit when `explore.md` gives no duration

BACKTICK = re.compile(r'`([^`]+)`')
DURATION = re.compile(r'\((\d+(?:\.\d+)?)\s*s\)')
ENVIRONMENT = re.compile(r'(?m)^\s*-\s*Environment:\s*(.+?)\s*$')
NOT_RUN_HERE = re.compile(r'^not run here\s*\((.*)\)$')
REPLACED_BY = re.compile(r'^replaced by\s+(.+)$')
FAILS_BEFORE = re.compile(r'^fails before the task\s*\((.*)\)$')
FP_LINE = re.compile(r'^Fingerprint: head=(none|[0-9a-f]{40}) files=([0-9a-f]{12}) paths=(\d+)$')
FP_NONE = re.compile(r'^Fingerprint: none \((.*)\)$')
RAN_LINE = re.compile(r'^Ran \d+ tests? in [\d.]+s')
RECORD_LINE = re.compile(
    r'^- (\d{2,}) `(.+?)` \((.+?)\) → (?:'
    r'exit (-?\d+) \| (.*) \| (\d+) s \| (checks/\d+\.log)'
    r'|timeout after (\d+) s \| (.*) \| (\d+) s \| (checks/\d+\.log)'
    r'|not run \(scope: Environment: (.*)\))$')
PATH_LINE = re.compile(r'^- (.+) ([0-9a-f]{12}|deleted)$')


# --- fingerprint ---

def file_fp(path: Path) -> str:
    """First 12 hex characters of sha1 of the file's bytes; `deleted` when it cannot be read."""
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return 'deleted'


def _git(root, *args):
    """Raw stdout of a git command in `root`, or None when git fails."""
    try:
        res = subprocess.run(['git', '-C', str(root), '-c', 'core.quotepath=false', *args],
                             capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def git_root(location):
    """The git top-level folder of `location`, or None when it is not a git location."""
    out = _git(location, 'rev-parse', '--show-toplevel')
    return Path(out.decode('utf-8', 'surrogateescape').strip()) if out and out.strip() else None


def fingerprint(location, records_folder):
    """{'head', 'files', 'paths': {path: fp}} of the working tree at `location`, or None when it is not a git location.
    Paths under `records_folder` (the task's own records folder) are left out."""
    root = git_root(location)
    if root is None:
        return None
    out = _git(root, 'status', '--porcelain=v1', '-z', '-uall')
    if out is None:
        return None
    try:
        skip = Path(records_folder).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        skip = None
    tokens = out.decode('utf-8', 'surrogateescape').split('\0')
    paths, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if len(tok) < 4:
            continue
        paths.append(tok[3:])
        if 'R' in tok[:2] or 'C' in tok[:2]:   # a rename or copy lists its source path next
            if i < len(tokens) and tokens[i]:
                paths.append(tokens[i])
            i += 1
    paths = {p: file_fp(root / p) for p in paths if not (skip and (p == skip or p.startswith(skip + '/')))}
    head = _git(root, 'rev-parse', 'HEAD')
    head = head.decode().strip() if head and head.strip() else 'none'
    lines = ''.join(f'{p}\t{paths[p]}\n' for p in sorted(paths))
    return {'head': head, 'files': hashlib.sha1(lines.encode('utf-8', 'surrogateescape')).hexdigest()[:12],
            'paths': paths}


def differing_paths(before: dict, after: dict) -> list:
    """Sorted paths whose hash differs between two `paths` dicts (a path missing on one side counts)."""
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


# --- check commands ---

def applies(profile, plan_text) -> bool:
    """True in the dev profile, and in the general profile when the plan has a `my-agent:coder` unit."""
    if profile == 'dev':
        return True
    if profile != 'general':
        return False
    in_units = False
    for line in ma_schema.section_lines(plan_text, 'Work units') or []:
        if ma_schema.UNIT_HEAD.match(line):
            in_units = True
        elif in_units and re.match(r'^\s*-\s*Agent:.*my-agent:coder', line):
            return True
    return False


def unit_commands(plan_text) -> list:
    """[(unit id, [command])]: the backticked spans on a unit's `- Check commands:` line, plus the first span of each
    nested `  - ` bullet under it."""
    out, in_check = [], False
    for line in ma_schema.section_lines(plan_text, 'Work units') or []:
        head = ma_schema.UNIT_HEAD.match(line)
        if head:
            out.append((head.group(1), []))
            in_check = False
            continue
        if not out:
            continue
        key = None if line[:1].isspace() else ma_schema.UNIT_KEY.match(line)
        if key:
            in_check = key.group(1) == 'Check commands'
            if in_check:
                out[-1][1].extend(c.strip() for c in BACKTICK.findall(key.group(2)))
        elif in_check and re.match(r'\s+-\s', line):
            first = BACKTICK.search(line)
            if first:
                out[-1][1].append(first.group(1).strip())
    return out


def explore_commands(explore_text) -> list:
    """[(command, seconds or None)]: the first backticked span of each `- ` line under `## Check commands`, with the
    first `(<n> s)` duration after it."""
    out = []
    for line in ma_schema.section_lines(explore_text, 'Check commands') or []:
        if not line.startswith('- '):
            continue
        m = BACKTICK.search(line)
        if m:
            d = DURATION.search(line, m.end())
            out.append((m.group(1).strip(), float(d.group(1)) if d else None))
    return out


def environment(text) -> dict:
    """{command: (kind, value)} from the `- Environment:` lines: kind `not run` (value: reason), `replaced` (value: the
    replacement command) or `fails before` (value: the tests). Backticks are stripped."""
    out = {}
    for raw in ENVIRONMENT.findall(text or ''):
        raw = re.sub(r"\s*\(the person's choice\)\s*$", '', raw.replace('`', ''))   # the mark of a settled line
        parts = re.split(r'\s[—–]\s', raw, maxsplit=1)
        if len(parts) != 2:
            continue
        command, rest = parts[0].strip(), parts[1].strip()
        for pattern, kind in ((NOT_RUN_HERE, 'not run'), (REPLACED_BY, 'replaced'), (FAILS_BEFORE, 'fails before')):
            m = pattern.match(rest)
            if m:
                out[command] = (kind, m.group(1).strip())
                break
    return out


def time_limit(command, durations) -> int:
    """Twice the duration of the matching explore line, or twice the longest duration for another command; at least
    MIN_LIMIT; DEFAULT_LIMIT when no duration is given."""
    known = {c: d for c, d in durations if d is not None}
    if not known:
        return DEFAULT_LIMIT
    d = known.get(command)
    d = 2 * (d if d is not None else max(known.values()))
    return max(MIN_LIMIT, math.ceil(d))


def command_list(plan_text, explore_text, env_text) -> list:
    """The commands to run, in order, duplicates removed: [{command (as listed), run (as run), source, not_run (reason or
    None), limit}]. Unit commands come first in plan order, then the explore commands."""
    order, sources = [], {}
    for uid, cmds in unit_commands(plan_text):
        for c in cmds:
            if c not in sources:
                order.append(c)
            sources.setdefault(c, []).append(uid)
    durations = explore_commands(explore_text)
    for c, _d in durations:
        if c not in sources:
            order.append(c)
        if 'explore' not in sources.setdefault(c, []):
            sources[c].append('explore')
    env = environment(env_text)
    out = []
    for c in order:
        label = ', '.join(sorted(sources[c], key=lambda s: s != 'explore'))
        entry = {'command': c, 'run': c, 'source': label, 'not_run': None}
        kind, value = env.get(c, (None, None))
        if kind == 'not run':
            entry['not_run'] = value
        elif kind == 'replaced':
            entry['run'], entry['source'] = value, f'{label}; replaces `{c}`'
        elif kind == 'fails before':
            entry['source'] = f'{label}; fails before the task: {value}'
        entry['limit'] = time_limit(entry['run'], durations)
        out.append(entry)
    return out


def _read(path: Path, strict: bool) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''
    except (OSError, UnicodeDecodeError):
        if strict:
            raise
        return ''


def commands_for(task: Path, profile, plan_text, strict=False) -> list:
    """The command list of a task folder; [] when the script does not apply. `strict`: an unreadable explore.md or
    scope.md raises instead of counting as empty."""
    if not applies(profile, plan_text):
        return []
    explore = _read(task / 'explore.md', strict)
    scope = task / 'scope.md'
    env = _read(scope, strict) if scope.is_file() else plan_text
    return command_list(plan_text, explore, env)


# --- record ---

def parse_record(text):
    """{task, head, files, count, none_reason, taken, result, lines, paths} of a checks.md, or None when it does not
    parse. `lines` holds {n, command, source, kind (`exit`, `timeout`, `not run`), code (exit lines), limit (timeout
    lines), summary, secs, log, reason (not-run lines)}."""
    rows = (text or '').splitlines()
    if len(rows) < 4 or not rows[0].startswith('# Check record: '):
        return None
    rec = {'task': rows[0][len('# Check record: '):].strip(), 'head': None, 'files': None, 'count': None,
           'none_reason': None, 'lines': [], 'paths': {}}
    m = FP_LINE.match(rows[1])
    if m:
        rec['head'], rec['files'], rec['count'] = m.group(1), m.group(2), int(m.group(3))
    else:
        m = FP_NONE.match(rows[1])
        if not m:
            return None
        rec['none_reason'] = m.group(1)
    if not rows[2].startswith('Taken: ') or not rows[3].startswith('Result: '):
        return None
    rec['taken'], rec['result'] = rows[2][len('Taken: '):].strip(), rows[3][len('Result: '):].strip()
    in_paths = False
    for line in rows[4:]:
        if line.startswith('## '):
            in_paths = line.strip() == '## Fingerprint paths'
            continue
        if not line.strip():
            continue
        if in_paths:
            m = PATH_LINE.match(line)
            if not m:
                return None
            rec['paths'][m.group(1)] = m.group(2)
            continue
        m = RECORD_LINE.match(line)
        if not m:
            return None
        g = m.groups()
        item = {'n': g[0], 'command': g[1], 'source': g[2], 'code': None, 'limit': None, 'summary': None, 'secs': None,
                'log': None, 'reason': None}
        if g[3] is not None:
            item.update(kind='exit', code=int(g[3]), summary=g[4], secs=int(g[5]), log=g[6])
        elif g[7] is not None:
            item.update(kind='timeout', limit=int(g[7]), summary=g[8], secs=int(g[9]), log=g[10])
        else:
            item.update(kind='not run', reason=g[11])
        rec['lines'].append(item)
    return rec


def status(task: Path, location, profile, plan_text) -> str:
    """The check-record status of a task folder (see the module docstring); `location` is the task location."""
    if not commands_for(task, profile, plan_text):
        return 'not needed (no check commands)'
    try:
        rec = parse_record((task / ma_schema.CHECKS).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError):
        rec = None
    if rec is None:
        return 'missing'
    if rec['head'] is None:
        return 'no fingerprint'
    now = fingerprint(location, task)
    if now is None:
        return 'no fingerprint'
    if now['head'] != rec['head']:
        return 'stale (HEAD moved)'
    if now['files'] == rec['files']:
        return 'current'
    diff = differing_paths(rec['paths'], now['paths'])
    if not diff:
        return 'stale (0 paths differ: none)'   # the hash differs but the record lists no differing path
    return f'stale ({len(diff)} paths differ: {", ".join(diff[:5])})'
