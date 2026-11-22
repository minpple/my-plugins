"""One place for the words and shapes my-agent files share (architecture 4.7 "single source of formats").

The L4 hooks and scripts and the monitor (`monitor/monitor/`, which puts this folder on sys.path) read files with
these values; the agent definitions and L1 files write them. `test_schema` checks that each definition still
spells the words its parser looks for.
"""
import hashlib
import json
import re
import shlex
from pathlib import Path

# --- agents (plugin.json lists the same ten; frontmatter `level:` and the folder say the same level) ---

AGENTS = {
    'scope-reviewer': 'L2', 'architect': 'L2', 'plan-reviewer': 'L2', 'verifier': 'L2', 'reviewer': 'L2', 'gate-analyst': 'L2',
    'explorer': 'L3', 'researcher': 'L3', 'writer': 'L3', 'coder': 'L3',
}
LEVEL_FOLDER = {'L2': 'l2-design-judge', 'L3': 'l3-workers'}
UNIT_AGENTS = ('researcher', 'writer', 'coder')           # agents that run a plan.md work unit (E: unit stops)
BEFORE_APPROVAL = ('explorer', 'scope-reviewer', 'architect', 'plan-reviewer')   # G1b allow list (4.4, Q6)

# --- verdicts: the first line of each judge's file and last message ---

VERIFY_PASS = 'Verdict: ALL PASS'
VERIFY_FAIL = 'Verdict: FAIL'
PLAN_READY = 'READY FOR APPROVAL'
PLAN_REVISE = 'REVISE'
SCOPE_READY = 'READY FOR CONFIRMATION'   # scope-review.md; its other verdict is PLAN_REVISE
PLAN_SKIPPED = 'SKIPPED'          # L1 writes `SKIPPED <reason>` when the profile skips Plan Review
REVIEW_PASS = 'BLOCKER 0'
REVIEW_PREFIX = 'BLOCKER '
WORKER_DONE = 'DONE'
WORKER_PARTIAL = 'PARTIAL'
APPLIED_AFTER_REVIEW = 'Applied after review'    # review.md section L1 adds after a fix that skips re-Verify


def verify_failed(first_line) -> bool:
    return isinstance(first_line, str) and first_line.startswith(VERIFY_FAIL)


def plan_review_skipped(first_line) -> bool:
    return isinstance(first_line, str) and (first_line == PLAN_SKIPPED or first_line.startswith(PLAN_SKIPPED + ' '))


# --- run-log kinds written by the L4 hooks ---

GUARD = 'guard'                                        # run-log kind of a guard deny (scope-guard, plan-approved-check)
GUARD_FIELDS = ('hook', 'agent', 'id', 'tool', 'decision', 'why', 'cwd')   # guard: field order; why = the reason as printed, cwd = the hook input's cwd (older lines end at why)

# --- status values ---

INTAKE_STATUS = ('active', 'done', 'aborted')          # intake.md `Status:` (first word)
UNIT_STATUS = ('pending', 'running', 'done', 'stale')  # plan.md work unit `Status:`
UNIT_FINISHED = ('done', 'stale')                      # every unit ends in one of these (check-run)
END = END_OK, END_PARTIAL, END_ERROR = ('ok', 'partial', 'error')   # stop: end=
INTERRUPTED = (END_PARTIAL, END_ERROR)                 # an end that counts as a worker stop (E)
GATES = ('G1a', 'G1b', 'G2', 'G3', 'E')
POPUP_TAGS = GATES + ('Q',)                            # Q: an L1 popup that is not a gate
PEOPLE_POPUPS = ('G1a', 'G1b', 'G3', 'E', 'Q')         # L1 popups (G2 is Claude Code's permission window)

# --- models ---

FAMILY = re.compile(r'(opus|sonnet|haiku|fable)')


def family(model):
    """`claude-sonnet-5-5` / `sonnet` / `opus[1m]` → the family, or None."""
    m = FAMILY.search(model or '')
    return m.group(1) if m else None


# Codex model ids captured in an earlier probe run; not part of FAMILY (Claude only).
# The Codex default is the id the probe session used; the model a role runs on when no preset sets one.
CODEX_DEFAULT = 'gpt-6-luna'
CODEX_FAMILY = re.compile(r'(gpt-6-luna|gpt-5\.6-luna|gpt-5\.6-terra|codex-auto-review|gpt-reserve)')


def codex_family(model):
    """`gpt-6-luna` → itself, any other Codex id the probe saw likewise; anything else None."""
    m = CODEX_FAMILY.search(model or '')
    return m.group(1) if m else None


# Antigravity model ids (Gemini families and tier names); not part of FAMILY (Claude) or CODEX_FAMILY (Codex).
ANTIGRAVITY_FAMILY = re.compile(r'(gemini-[a-z0-9._-]+)', re.I)


def antigravity_family(model):
    """`gemini-4-neon` / `gemini-3-pro` → the lowercased Gemini id, else None."""
    m = ANTIGRAVITY_FAMILY.search(model or '')
    return m.group(1).lower() if m else None


# --- run-log lines (4.7.2): `<YYYY-MM-DD HH:MM:SS> <kind>: <key=value ...>` ---

LINE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ([a-z][a-z0-9-]*):(?:\s+(.*))?$')
DELEGATE_STATES = ('on', 'off')   # `delegate: state=` (delegated approval); the last such line is the current state
ANSWERED_BY_L1 = 'L1'             # `answer: ... by=L1` is an answer L1 gave under delegated approval
PLAN_EDIT_GATE = 'G1b'            # `fix: ... before=G1b` is an L1 edit of plan.md before plan approval
STAMPED = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ')   # looks like a record, readable or not


def split_line(text: str):
    """(stamp, kind, fields) of a run-log line, or None (headings, old-style or broken lines)."""
    m = LINE_RE.match(text.strip())
    if not m:
        return None
    try:
        tokens = shlex.split(m.group(3) or '')
    except ValueError:
        return None
    fields = {}
    for tok in tokens:
        key, sep, value = tok.partition('=')
        if sep:
            fields[key] = value
    return m.group(1), m.group(2), fields


def unreadable_lines(text: str) -> list:
    """1-based numbers of lines that start like a record but do not parse."""
    return [i for i, line in enumerate(text.splitlines(), 1)
            if STAMPED.match(line.strip()) and split_line(line) is None]


# --- Markdown sections: a line-start `## <name>`, optionally followed by ` (<note>)` ---

def heading_name(line: str):
    """`## Completion criteria (general)` → `Completion criteria`; None for a line that is not a `## ` heading."""
    if not line.startswith('## '):
        return None
    return line[3:].strip().split(' (')[0]


def section_lines(text: str, *names):
    """Lines under the first `## <name>` heading up to the next `## ` heading, or None when there is none."""
    out, inside = None, False
    for line in (text or '').splitlines():
        name = heading_name(line)
        if name is not None:
            if inside:
                break
            inside = name in names
            if inside:
                out = []
            continue
        if inside:
            out.append(line)
    return out


def section(text: str, *names) -> str:
    """Body of the first `## <name>` section, or ''."""
    lines = section_lines(text, *names)
    return '\n'.join(lines) if lines is not None else ''


def has_section(text: str, name: str) -> bool:
    return section_lines(text, name) is not None


# --- plan.md markers and work units ---

APPROVED = re.compile(r'Approved\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})')   # under ## Approval, L1 only
PROTOTYPE = re.compile(r'(?m)^\s*(?:-\s*)?Prototype:\s*requested\s*$')  # under ## Prototype, L1 only
UNIT_HEAD = re.compile(r'^###\s+(u\d+)\b\s*(.*)$')                     # `### u1 <name>` under ## Work units
UNIT_STATUS_LINE = re.compile(r'^\s*(?:-\s*)?Status:\s*([a-z]+)')
UNIT_MARK = re.compile(r'(?m)^Work unit:\s*(u\d+)\b')                   # first prompt line L1 gives a unit's worker
MOCKUP_KIND = re.compile(r'^Kind:\s*(.*)$')                            # first line of ## Mock-up
DELIVERED_COMMIT = 'commit:'                                           # `Delivered: commit:<sha>` / deliver path=


def approved_at(text: str):
    """`YYYY-MM-DD HH:MM` of the Approved line under ## Approval, or None."""
    m = APPROVED.search(section(text, 'Approval'))
    return m.group(1) if m else None


def prototype_requested_text(text: str) -> bool:
    return bool(PROTOTYPE.search(section(text, 'Prototype')))


def units(text: str) -> list:
    """[(id, name, status)] of the `### u<n>` work units under ## Work units; status None when missing."""
    out = []
    for line in section_lines(text, 'Work units') or []:
        head = UNIT_HEAD.match(line)
        if head:
            out.append([head.group(1), head.group(2).strip(), None])
            continue
        st = UNIT_STATUS_LINE.match(line)
        if st and out and out[-1][2] is None:
            out[-1][2] = st.group(1)
    return [tuple(u) for u in out]


def unit_of_prompt(prompt):
    """`u1` from a `Work unit: u1 …` line in a worker's prompt, or None."""
    m = UNIT_MARK.search(prompt or '')
    return m.group(1) if m else None


# --- report parsers (monitor Report tab; each returns None or [] for a missing or empty text) ---

CRITERION_LINE = re.compile(r'^\s*(\d+)\.\s+(.*\S)\s*$')
CHECK_TAG = re.compile(r'\s*\[check:\s*([^\]]*?)\s*\]\s*$')
VERIFY_ROW = re.compile(r'^\s*-\s*(\d+)\.\s+([A-Z]+)\b\s*(.*)$')
RUN_LINE = re.compile(r'(?m)^Run:\s*(\d+)\s*$')
REVIEW_BLOCKERS = re.compile(r'^BLOCKER\s+(\d+)\b')
SEVERITIES = ('BLOCKER', 'SHOULD-FIX', 'NITPICK')
FINDING_LINE = re.compile(r'^-\s*(BLOCKER|SHOULD-FIX|NITPICK)\s+(\S+)\s*(.*)$')
FINDING_MARK = re.compile(r'\s*\((new|carried)\)\s*$')
IMPROVEMENT_LINE = re.compile(r'^-\s*\[(L\d),\s*([a-z]+)\]\s*(.*\S)\s*$')
SUMMARY_ITEM = re.compile(r'^\s*\d+\.\s+(.*\S)\s*$')
UNIT_KEY = re.compile(r'^(?:-\s*)?([A-Z][A-Za-z ]*?):\s*(.*)$')
PATH_TOKEN = re.compile(r'[\w./\-]+\.\w+(?::\d+)?')
LINE_SUFFIX = re.compile(r':\d+$')


def criteria(text: str) -> list:
    """[(n, text without the `[check: …]` tag, tag or None)] from `## Completion criteria` (scope.md, or plan.md for a small task)."""
    rows = []
    for line in section_lines(text, 'Completion criteria') or []:
        m = CRITERION_LINE.match(line)
        if m:
            rows.append([int(m.group(1)), m.group(2)])
        elif rows and line.strip() and line[:1].isspace():
            rows[-1][1] += ' ' + line.strip()
    out = []
    for n, body in rows:
        tag = CHECK_TAG.search(body)
        out.append((n, CHECK_TAG.sub('', body) if tag else body, tag.group(1) if tag else None))
    return out


def purpose(text: str):
    """The paragraph under `## Purpose and users` (scope.md) or `## Scope summary` (plan.md), or None."""
    joined = ' '.join(l.strip() for l in section_lines(text, 'Purpose and users', 'Scope summary') or [] if l.strip())
    return joined or None


def verify_rows(text: str) -> list:
    """[(n, verdict, evidence)] of the `- <n>. PASS|FAIL <evidence>` rows before the first `## ` heading of verify.md."""
    out = []
    for line in (text or '').splitlines():
        if heading_name(line) is not None:
            break
        m = VERIFY_ROW.match(line)
        if m:
            out.append((int(m.group(1)), m.group(2), m.group(3).strip()))
    return out


def run_number(text: str):
    """The `Run: <n>` of a verify.md, plan-review.md or scope-review.md, or None."""
    m = RUN_LINE.search(text or '')
    return int(m.group(1)) if m else None


def review_blockers(text: str):
    """The n of the `BLOCKER n` first line of review.md, or None."""
    for line in (text or '').splitlines():
        if line.strip():
            m = REVIEW_BLOCKERS.match(line.strip())
            return int(m.group(1)) if m else None
    return None


def review_findings(text: str) -> list:
    """[(severity, where, text, mark)] of the `## Findings` bullets of review.md; mark is `new`, `carried` or None."""
    out = []
    for line in section_lines(text, 'Findings') or []:
        m = FINDING_LINE.match(line.strip())
        if m:
            body = m.group(3).strip()
            mark = FINDING_MARK.search(body)
            out.append((m.group(1), m.group(2), FINDING_MARK.sub('', body) if mark else body, mark.group(1) if mark else None))
    return out


def review_applied(text: str) -> list:
    """The bullet lines (without the dash) under `## Applied after review` in review.md."""
    return [l.strip()[1:].strip() for l in section_lines(text, APPLIED_AFTER_REVIEW) or [] if l.strip().startswith('-')]


def finding_applied(where: str, applied_lines) -> bool:
    """A finding is applied when an `Applied after review` line names its `<file>:<line>` or its file path
    (a path in the line may be cut at the front)."""
    file = LINE_SUFFIX.sub('', where)
    for line in applied_lines:
        for tok in PATH_TOKEN.findall(line):
            if tok == where or where.endswith('/' + tok):
                return True
            if not LINE_SUFFIX.search(tok) and (file == tok or file.endswith('/' + tok)):
                return True
    return False


def plan_review(text: str):
    """{verdict, run, blockers, should_fix, nitpicks} of a plan-review.md or scope-review.md, or None when the text is empty."""
    lines = [l for l in (text or '').splitlines() if l.strip()]
    if not lines:
        return None
    counts = {s: 0 for s in SEVERITIES}
    for line in section_lines(text, 'Findings') or []:
        m = FINDING_LINE.match(line.strip())
        if m:
            counts[m.group(1)] += 1
    return {'verdict': lines[0].strip(), 'run': run_number(text), 'blockers': counts['BLOCKER'],
            'should_fix': counts['SHOULD-FIX'], 'nitpicks': counts['NITPICK']}


def gate_report_summary(text: str) -> list:
    """The numbered items under `## Summary` of gate-report.md."""
    return [m.group(1) for m in map(SUMMARY_ITEM.match, section_lines(text, 'Summary') or []) if m]


def gate_report_improvements(text: str) -> list:
    """[(level, strength, text)] of the `- [L1, weak] …` bullets under `## Suggested improvements`."""
    lines = (l.strip() for l in section_lines(text, 'Suggested improvements') or [])
    return [m.groups() for m in map(IMPROVEMENT_LINE.match, lines) if m]


def criterion_numbers(line: str) -> list:
    """Criterion numbers of a plan unit's `Completion criteria:` value: the integers outside parentheses, sorted, once each."""
    out, depth = [], 0
    for ch in line or '':
        depth = depth + 1 if ch == '(' else max(0, depth - 1) if ch == ')' else depth
        out.append(' ' if depth or ch in '()' else ch)
    return sorted({int(n) for n in re.findall(r'(?<![\w.])\d+(?![\w.])', ''.join(out))})


def unit_details(text: str) -> list:
    """[{id, name, status, group, files, criteria}] of the `### u<n>` units under ## Work units
    (files: the backticked paths of `Files to change:`, on its line or in its nested bullets)."""
    units, in_files = [], False
    for line in section_lines(text, 'Work units') or []:
        head = UNIT_HEAD.match(line)
        if head:
            units.append({'id': head.group(1), 'name': head.group(2).strip(), 'status': None, 'group': None,
                          'files': [], 'criteria': []})
            in_files = False
            continue
        if not units:
            continue
        unit = units[-1]
        key = None if line[:1].isspace() else UNIT_KEY.match(line)
        if key:
            name, value = key.groups()
            in_files = name == 'Files to change'
            if name == 'Status' and unit['status'] is None and value.split():
                unit['status'] = value.split()[0]
            elif name == 'Parallel group':
                unit['group'] = value.strip() or None
            elif name == 'Completion criteria':
                unit['criteria'] = criterion_numbers(value)
            elif in_files:
                unit['files'] += re.findall(r'`([^`]+)`', value)
        elif in_files and re.match(r'\s+-\s', line):
            m = re.search(r'`([^`]+)`', line)
            if m:
                unit['files'].append(m.group(1))
    return units


# --- plan gaps (the approval check of plan-lint.py and the G1b hook; architecture 4.4 "Plan gaps") ---

CHECK_TAGS = ('command', 'file', 'URL', 'person')
COVERS = re.compile(r'\(criteri(?:on|a)\s+(\d+(?:\s*(?:,|and)\s*\d+)*)\)')   # `(criterion 2)`, `(criteria 2, 3)`
PROFILE_LINE = re.compile(r'(?m)^Profile:\s*([a-z]+)')


def profile_of(intake_text):
    """`dev` from the `Profile: dev` line of intake.md, or None."""
    m = PROFILE_LINE.search(intake_text or '')
    return m.group(1) if m else None


def unit_covers(plan_text: str) -> dict:
    """{unit id: criterion numbers named in `(criterion <n>)` marks on the unit's lines} under ## Work units."""
    out, current = {}, None
    for line in section_lines(plan_text, 'Work units') or []:
        head = UNIT_HEAD.match(line)
        if head:
            current = out.setdefault(head.group(1), set())
        elif current is not None:
            for group in COVERS.findall(line):
                current.update(int(n) for n in re.findall(r'\d+', group))
    return out


def in_records(path: str, records) -> bool:
    """True when a plan's `Files to change` path lies in the task records folder `records` (`<location>/<task_dir>`):
    an absolute path under it, a relative path that starts with its name, or one written with `<task_dir>`."""
    if '<task_dir>' in path:
        return True
    parts = [p.casefold() for p in Path(path).parts if p != '.']
    root = [p.casefold() for p in Path(records).parts]
    if Path(path).is_absolute():
        return parts[:len(root)] == root
    return bool(parts) and parts[0] == root[-1]


def plan_gaps(scope_text, plan_text, profile, records=None) -> list:
    """What keeps a plan from approval, one line each ([] for none). Formats only; plan-reviewer judges the content.
    Every completion criterion (scope.md, or plan.md without one) ends with one of the four check tags; in the dev
    profile every `[check: command]` criterion has a `(criterion <n>)` mark in a work unit that lists it. With
    `records` (the task records folder), no `Files to change` path lies in it: only a coder unit has that line, and
    scope-guard denies a coder every write there."""
    rows = criteria(scope_text) or criteria(plan_text)
    if not rows:
        return ['no numbered completion criteria']
    gaps = []
    for n, _text, tag in rows:
        if tag is None:
            gaps.append(f'criterion {n}: no check tag')
        elif tag not in CHECK_TAGS:
            gaps.append(f'criterion {n}: check tag `{tag}` is not one of {", ".join(CHECK_TAGS)}')
    if profile == 'dev':
        covers = unit_covers(plan_text)
        listed = {u['id']: set(u['criteria']) for u in unit_details(plan_text)}
        shown = set().union(*(covers[u] & listed.get(u, set()) for u in covers)) if covers else set()
        for n, _text, tag in rows:
            if tag == 'command' and n not in shown:
                gaps.append(f'criterion {n}: no test to add or check command marked `(criterion {n})` in a work unit that lists it')
    if records is not None:
        gaps += [f"{u['id']}: `{path}` is in the task records folder, which a coder cannot write "
                 '(a `Files to change` path must be in the task location)'
                 for u in unit_details(plan_text) for path in u['files'] if in_records(path, records)]
    return gaps


# --- gate view parsers (monitor Report tab; same rule: None or [] for a missing text, never raise) ---

LABEL_LINE = re.compile(r'^(?:-\s*)?(Background|Purpose):\s*(.*)$')
UNLABELED_SKIP = re.compile(r'^(?:Users:|-\s*Non-goals:|-\s*Deliverable location:)')
VERDICT_LINE = re.compile(r'^Verdict:\s*(ALL PASS|FAIL)\b')
DECISION_LINE = re.compile(r'^-\s*(BLOCKER|SHOULD-FIX|NITPICK)\s+(\S+)\s*(.*)$')
ABORTED_LINE = re.compile(r'(?m)^Status:\s*aborted\b(?:[ \t]+\d{4}-\d{2}-\d{2} \d{2}:\d{2})?[ \t]*(.*?)[ \t]*$')
MODELS_KEYS = ('agent', 'model', 'effort', 'note')


def _blocks(lines) -> list:
    """Blank-line separated groups of non-empty stripped lines."""
    out, cur = [], []
    for line in lines:
        if line.strip():
            cur.append(line.strip())
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def background_purpose(text):
    """(background, purpose) from `## Purpose and users` (scope.md) or `## Scope summary` (plan.md); a missing one is None.
    `Background:` / `Purpose:` labels pick the values; without labels the first paragraph is the background and the
    rest (without `Users:`, `- Non-goals:`, `- Deliverable location:` paragraphs) is the purpose."""
    blocks = _blocks(section_lines(text, 'Purpose and users', 'Scope summary') or [])
    items = []                                   # a bullet list is split into its bullets, a paragraph stays one item
    for block in blocks:
        if any(l.startswith('- ') for l in block):
            for l in block:
                if l.startswith('- ') or not items:
                    items.append([l])
                else:
                    items[-1].append(l)
        else:
            items.append(block)
    found = {}
    current = None
    for item in items:
        m = LABEL_LINE.match(item[0])
        if m:
            current = m.group(1)
            found.setdefault(current, []).append(' '.join([m.group(2)] + item[1:]).strip())
        else:
            current = None
    if found:
        return tuple(' '.join(found[k]).strip() or None if k in found else None for k in ('Background', 'Purpose'))
    kept = [' '.join(b) for b in blocks if not UNLABELED_SKIP.match(b[0])]
    if not kept:
        return None, None
    return kept[0], ' '.join(kept[1:]) or None


def section_bullets(text, name) -> list:
    """The top-level `- ` bullet texts under `## <name>` (indented lines of a bullet are joined to it)."""
    out = []
    for line in section_lines(text, name) or []:
        if line.startswith('- '):
            out.append(line[2:].strip())
        elif out and line.strip() and line[:1].isspace():
            out[-1] += ' ' + line.strip()
    return out


def plan_lead(text):
    """The paragraph between the `# ` title line of a plan.md and its first `## ` heading, or None."""
    lead, titled = [], False
    for line in (text or '').splitlines():
        if not titled:
            titled = line.startswith('# ')
            continue
        if line.startswith('#'):
            break
        if line.strip():
            lead.append(line.strip())
        elif lead:
            break
    return ' '.join(lead) or None


def models_table(text):
    """{preset, rows: [{agent, model, effort, note}], recommendation} from `## Models` of a plan.md, or None without it."""
    lines = section_lines(text, 'Models')
    if lines is None:
        return None
    preset = recommendation = None
    rows = []
    for line in lines:
        s = line.strip()
        if s.startswith('|'):
            cells = [c.strip() for c in s.strip('|').split('|')]
            if not cells[0] or cells[0].lower() == 'agent' or re.fullmatch(r':?-+:?', cells[0]):
                continue
            cells += [''] * (len(MODELS_KEYS) - len(cells))
            rows.append(dict(zip(MODELS_KEYS, cells)))
        elif s.startswith('Preset:') and preset is None:
            preset = s[len('Preset:'):].strip() or None
        elif s.startswith('Recommendation:') and recommendation is None:
            recommendation = s[len('Recommendation:'):].strip() or None
    return {'preset': preset, 'rows': rows, 'recommendation': recommendation}


def verify_verdict(text):
    """`ALL PASS`, `FAIL` or None from the first non-empty line `Verdict: …` of verify.md."""
    for line in (text or '').splitlines():
        if line.strip():
            m = VERDICT_LINE.match(line.strip())
            return m.group(1) if m else None
    return None


def plan_review_decisions(text) -> list:
    """[(severity, where, outcome)] of the `## Decisions` bullets of plan-review.md; outcome is `applied`, `declined` or None."""
    out = []
    for line in section_lines(text, 'Decisions') or []:
        m = DECISION_LINE.match(line.strip())
        if m:
            tail = m.group(3).rpartition('→')[2].strip() if '→' in m.group(3) else ''
            outcome = 'applied' if tail.startswith('applied') else 'declined' if tail.startswith('declined') else None
            out.append((m.group(1), m.group(2), outcome))
    return out


def aborted_reason(intake_text):
    """The reason of `Status: aborted <YYYY-MM-DD HH:MM> <reason>` in intake.md, '' without a reason, None when not aborted."""
    m = ABORTED_LINE.search(intake_text or '')
    return m.group(1) if m else None


# --- changed-file map (`changed-files.py` writes it; the verifier and the reviewer read it, accept.md step 7) ---

CHANGED_FILES = 'changed-files.md'
CHANGED_COLUMNS = ('file', 'units', 'criteria', 'fingerprint', 'since')
REJUDGE_LINE = re.compile(r'(?m)^Re-judge:\s*(.*?)\s*$')
ALL_CRITERIA = 'all'


def changed_files_rows(text):
    """([{file, units, criteria, fingerprint, since}], the `Re-judge:` value or None) of a changed-files.md;
    ([], None) for a missing or empty text."""
    rows = []
    for line in (text or '').splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if not line.strip().startswith('|') or len(cells) != len(CHANGED_COLUMNS) or cells[0] in ('File', '') \
                or set(cells[0]) <= {'-'}:
            continue
        rows.append(dict(zip(CHANGED_COLUMNS, cells)))
    m = REJUDGE_LINE.search(text or '')
    return rows, (m.group(1) if m else None)


# --- Korean copy of the report texts (`report-ko.py` lists what to translate; L1 writes it; the Report tab reads it) ---

KO_COPY = 'report-ko.json'


def overview_texts(scope, plan):
    """(background, purpose) from scope.md, else from the plan's `## Scope summary`; None where neither has it.
    A one-paragraph section without labels gives that paragraph as both."""
    for text in (scope, plan):
        background, purpose_text = background_purpose(text)
        if background or purpose_text:
            if purpose_text is None and background == purpose(text):
                purpose_text = background
            return background, purpose_text
    return None, None


def ko_sources(scope, plan) -> dict:
    """{key: English text} of the items the Korean copy covers, in Report order: `background`, `purpose`,
    `c<n>` (a criterion without its check tag) and `u<n>` (a work unit title)."""
    out = {}
    background, purpose_text = overview_texts(scope, plan)
    if background:
        out['background'] = background
    if purpose_text:
        out['purpose'] = purpose_text
    for n, text, _tag in criteria(scope) or criteria(plan):
        out[f'c{n}'] = text
    for unit in unit_details(plan):
        if unit['name']:
            out[unit['id']] = unit['name']
    return out


def text_sha(text) -> str:
    """The first 8 hex characters of the sha1 of the whitespace-collapsed text: the copy's tie to its English source."""
    return hashlib.sha1(' '.join(str(text or '').split()).encode('utf-8')).hexdigest()[:8]


def ko_copy(text) -> dict:
    """{key: {sha, ko}} of a report-ko.json text; {} for a missing or broken file, entries without both strings dropped."""
    try:
        items = json.loads(text or '').get('items')
    except (ValueError, AttributeError):
        return {}
    if not isinstance(items, dict):
        return {}
    return {k: v for k, v in items.items()
            if isinstance(v, dict) and isinstance(v.get('sha'), str) and isinstance(v.get('ko'), str) and v['ko'].strip()}


def ko_current(sources: dict, items: dict) -> dict:
    """{key: Korean text} of the copy items whose sha still matches their English source."""
    return {k: items[k]['ko'] for k, en in sources.items() if k in items and items[k]['sha'] == text_sha(en)}


# --- findings: Found, Fixed and Open of review.md, plan-review.md and scope-review.md (Report tab and findings.py) ---

PLAN_REVIEW_FIX = re.compile(r'^Plan Review (BLOCKER|SHOULD-FIX|NITPICK)\s+(.*)$')   # `fix: what=` of a plan edit before G1b


def _read_text(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None


def review_rounds(task_dir, review):
    """The texts of the Review rounds: archived copies by folder name, then the current review.md; a copy equal to an
    earlier round or to the current file is skipped."""
    rounds = []
    for path in sorted(Path(task_dir).glob('archive/*/review.md')):
        text = _read_text(path)
        if text is not None and text != review and text not in rounds:
            rounds.append(text)
    if review is not None:
        rounds.append(review)
    return rounds


def review_fix_whats(pairs):
    """The `what` of run-log `fix` lines after the last `step: n=8` and the last reviewer `start:` line that are Review
    fixes (no `before=`, no `Scope change:`); `pairs` are the parsed run-log (kind, fields) pairs. A fix made before
    the latest reviewer call belongs to the round before it."""
    pairs = list(pairs)
    last = max((i for i, (kind, f) in enumerate(pairs) if (kind == 'step' and f.get('n') == '8')
                or (kind == 'start' and str(f.get('agent') or '').endswith(('my-agent:reviewer', 'my-agent-reviewer')))),
               default=-1)
    return [f.get('what') or '' for kind, f in pairs[last + 1:]
            if kind == 'fix' and not f.get('before') and not (f.get('what') or '').startswith('Scope change:')]


def review_state(task_dir, review, pairs):
    """(review_totals, open findings of the latest round as (sev, where, text, mark)); (None, []) without any round.
    `review` is the text of review.md or None; the totals hold `found`, `fixed` and `open` per severity and `rounds`."""
    rounds = review_rounds(task_dir, review)
    if not rounds:
        return None, []
    found = {sev: 0 for sev in SEVERITIES}
    seen = set()
    for text in rounds:
        this = set()
        for sev, where, _body, mark in review_findings(text):
            if not (mark == 'carried' and (sev, where) in seen):
                found[sev] += 1
            this.add((sev, where))
        seen |= this
    latest = rounds[-1]
    applied = review_applied(latest) + review_fix_whats(pairs)
    open_items = [f for f in review_findings(latest) if not finding_applied(f[1], applied)]
    totals = {}
    for sev in SEVERITIES:
        n_open = min(found[sev], sum(1 for f in open_items if f[0] == sev))
        totals[sev] = {'found': found[sev], 'fixed': found[sev] - n_open, 'open': n_open}
    totals['rounds'] = len(rounds)
    return totals, open_items


def plan_review_fixes(pairs):
    """[(severity, rest)] of the run-log `fix … before=G1b` lines `Plan Review <SEVERITY> <where> …`."""
    matches = [PLAN_REVIEW_FIX.match((f.get('what') or '').strip()) for kind, f in pairs
               if kind == 'fix' and f.get('before') == PLAN_EDIT_GATE]
    return [m.groups() for m in matches if m]


def pairs_of_round(pairs, role='plan-reviewer'):
    """The run-log pairs after the last `start:` line of the judge `role` (its current round); every pair when the
    log has no such line. A `fix` line of an earlier round names a finding of that round's file, not of this one."""
    pairs = list(pairs)
    last = max((i for i, (kind, f) in enumerate(pairs)
                if kind == 'start' and str(f.get('agent') or '').endswith(role)), default=-1)
    return pairs[last + 1:]


def judged_counts(text, pairs=()):
    """(found, fixed, open findings) of one plan-review.md or scope-review.md text. `found` and `fixed` are per severity.
    A finding is fixed when it has an `applied` outcome in `## Decisions` or when a run-log `fix … before=G1b` line
    (`pairs`; plan-review only) names it; a declined finding stays open."""
    decided = {(sev, where) for sev, where, outcome in plan_review_decisions(text) if outcome == 'applied'}
    fixes = plan_review_fixes(pairs)
    found = {sev: 0 for sev in SEVERITIES}
    fixed = dict(found)
    open_items = []
    for item in review_findings(text):
        sev, where = item[0], item[1]
        found[sev] += 1
        if (sev, where) in decided or any(f_sev == sev and finding_applied(where, [rest]) for f_sev, rest in fixes):
            fixed[sev] += 1
        else:
            open_items.append(item)
    return found, fixed, open_items


REVISION_ARCHIVE = re.compile(r'-rev\d+(?:-profile)?(?:-[b-z])?$')   # Revise this task, profile change: an earlier revision ends


def judged_rounds(task_dir, name, current):
    """The texts of the rounds of `name` (plan-review.md or scope-review.md) in the current revision, oldest first:
    the archived copies made after the latest revision or profile-change archive, one per `Run:` (a later copy
    replaces an earlier one), then `current`, the text of the file itself."""
    folders = sorted(p for p in Path(task_dir).glob('archive/*') if p.is_dir())
    cut = max((i for i, p in enumerate(folders) if REVISION_ARCHIVE.search(p.name)), default=-1)
    runs = {}
    for i, text in enumerate([_read_text(p / name) for p in folders[cut + 1:]] + [current]):
        if text is not None and text.strip():
            run = run_number(text)
            runs[('none', i) if run is None else ('run', run)] = text
    if current is None:
        return []
    now = run_number(current)
    older = [text for (kind, n), text in sorted(runs.items(), key=lambda kv: (kv[0][0] == 'none', kv[0][1]))
             if text != current and (kind == 'none' or now is None or n < now)]
    return older + [current]


def judged_state(task_dir, name, current, pairs=()):
    """(totals, open findings of the latest round) of plan-review.md or scope-review.md over the rounds of the current
    revision, in the shape of `review_state`. A finding with the severity and place of one in an earlier round is the
    same finding listed again and is counted once; open is what the latest round leaves open (`judged_counts`, with
    the `fix` lines of that round only), so a finding of an earlier round counts as fixed."""
    rounds = judged_rounds(task_dir, name, current)
    found = {sev: 0 for sev in SEVERITIES}
    seen = set()
    for text in rounds:
        this = [(f[0], f[1]) for f in review_findings(text)]
        for key in this:
            found[key[0]] += key not in seen
        seen |= set(this)
    _found, _fixed, open_items = judged_counts(current, pairs_of_round(pairs))
    totals = {}
    for sev in SEVERITIES:
        n_open = min(found[sev], sum(1 for f in open_items if f[0] == sev))
        totals[sev] = {'found': found[sev], 'fixed': found[sev] - n_open, 'open': n_open}
    totals['rounds'] = len(rounds)
    return totals, open_items
