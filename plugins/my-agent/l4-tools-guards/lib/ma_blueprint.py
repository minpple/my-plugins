"""The project blueprint (architecture 4.7.5): the committed record of a project's current state, kept across tasks.

Folder: `<task location>/docs/blueprint/` with three files, each the current state (a task rewrites the entries it
changed; the history is in git):
- `features.md`: one `## <name>` entry per deliverable, with `- Purpose:`, `- Tasks:` and `- Updated:` lines and its
  completion criteria as numbered lines `<n>. <criterion> [check: <kind>] → <evidence>`.
- `decisions.md`: the sections `## Constraints`, `## Non-goals` and `## Decisions`; each item is one line
  `- <text> — <why> (<task-id>)`.
- `backlog.md`: open items, one line each: `- [review|check|next] <text> (<task-id>)`.

No blueprint is kept when the task location is the data folder (a task outside any project): `root()` gives None.
`check()` reads the three files and returns the entry counts and the format problems; a missing file counts 0.
"""
import re
from pathlib import Path
from typing import List, Optional, Tuple

import ma_data
from ma_path import same

DIR = 'docs/blueprint'
FEATURES, DECISIONS, BACKLOG = FILES = ('features.md', 'decisions.md', 'backlog.md')
TITLES = {FEATURES: '# Features', DECISIONS: '# Decisions', BACKLOG: '# Backlog'}
FEATURE_KEYS = ('Purpose', 'Tasks', 'Updated')            # required lines of a features.md entry
DECISION_SECTIONS = ('Constraints', 'Non-goals', 'Decisions')
BACKLOG_TAGS = ('review', 'check', 'next')

TASK_ID = r'\d{6}-[a-z0-9]+(?:-[a-z0-9]+)*'
TASK_REF = re.compile(r'\((' + TASK_ID + r')\)\s*$')      # an item line ends with the task that set it
TASK_LIST = re.compile(r'^' + TASK_ID + r'(?:,\s*' + TASK_ID + r')*$')
HEAD = re.compile(r'^##\s+(.*\S)\s*$')
KEY_LINE = re.compile(r'^-\s+([A-Z][A-Za-z]*):\s*(.*)$')
CRITERION = re.compile(r'^\d+\.\s+\S')
EVIDENCE = re.compile(r'\s→\s+\S')
ITEM = re.compile(r'^-\s+\S')
BACKLOG_ITEM = re.compile(r'^-\s+\[([a-z]+)\]\s+\S')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def root(location, data_dir=None) -> Optional[Path]:
    """`<location>/docs/blueprint`, or None when `location` is the data folder (no project, no blueprint)."""
    location = Path(location)
    try:
        if same(location.resolve(), ma_data.data_dir(data_dir).expanduser().resolve()):
            return None
    except OSError:
        pass
    return location / DIR


def _lines(path: Path) -> Optional[List[str]]:
    try:
        return path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return None


def _title(name: str, lines: List[str], problems: List[str]) -> None:
    first = next((l for l in lines if l.strip()), '')
    if first.strip() != TITLES[name]:
        problems.append(f'{name}:1 the first line is not `{TITLES[name]}`')


def check_features(lines: List[str], problems: List[str]) -> int:
    count, entry, keys, criteria, start = 0, None, set(), 0, 0

    def close():
        if entry is None:
            return
        for key in FEATURE_KEYS:
            if key not in keys:
                problems.append(f'{FEATURES}:{start} entry `{entry}` has no `- {key}:` line')
        if not criteria:
            problems.append(f'{FEATURES}:{start} entry `{entry}` has no numbered criterion')

    for n, line in enumerate(lines, 1):
        head = HEAD.match(line)
        if head:
            close()
            count, entry, keys, criteria, start = count + 1, head.group(1), set(), 0, n
            continue
        if entry is None:
            continue
        key = KEY_LINE.match(line)
        if key:
            name, value = key.group(1), key.group(2).strip()
            keys.add(name)
            if name == 'Tasks' and not TASK_LIST.match(value):
                problems.append(f'{FEATURES}:{n} `- Tasks:` is not a list of task IDs')
            if name == 'Updated' and not DATE.match(value):
                problems.append(f'{FEATURES}:{n} `- Updated:` is not a date (YYYY-MM-DD)')
        elif CRITERION.match(line):
            criteria += 1
            if not EVIDENCE.search(line):
                problems.append(f'{FEATURES}:{n} the criterion has no ` → <evidence>`')
    close()
    return count


def check_decisions(lines: List[str], problems: List[str]) -> int:
    count, section, seen = 0, None, []
    for n, line in enumerate(lines, 1):
        head = HEAD.match(line)
        if head:
            section = head.group(1)
            seen.append(section)
            if section not in DECISION_SECTIONS:
                problems.append(f'{DECISIONS}:{n} unknown section `## {section}`')
            continue
        if section is not None and ITEM.match(line):
            count += 1
            if not TASK_REF.search(line):
                problems.append(f'{DECISIONS}:{n} the item does not end with `(<task-id>)`')
    for name in DECISION_SECTIONS:
        if seen.count(name) != 1:
            problems.append(f'{DECISIONS}:1 section `## {name}` appears {seen.count(name)} times (need 1)')
    return count


def check_backlog(lines: List[str], problems: List[str]) -> int:
    count = 0
    for n, line in enumerate(lines, 1):
        if not ITEM.match(line):
            continue
        count += 1
        tag = BACKLOG_ITEM.match(line)
        if not tag or tag.group(1) not in BACKLOG_TAGS:
            problems.append(f'{BACKLOG}:{n} the item does not start with one of [{"], [".join(BACKLOG_TAGS)}]')
        if not TASK_REF.search(line):
            problems.append(f'{BACKLOG}:{n} the item does not end with `(<task-id>)`')
    return count


CHECKS = {FEATURES: check_features, DECISIONS: check_decisions, BACKLOG: check_backlog}


def check(folder) -> Tuple[dict, List[str]]:
    """({file name: entry count}, problems) for the blueprint folder `folder`; a missing file counts 0, no problem."""
    counts, problems = {}, []
    for name in FILES:
        lines = _lines(Path(folder) / name)
        if lines is None:
            counts[name] = 0
            continue
        _title(name, lines, problems)
        counts[name] = CHECKS[name](lines, problems)
    return counts, problems
