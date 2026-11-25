#!/usr/bin/env python3
"""Back to Execute in one call: archive the judgments, set the named work units back to pending, set the phase, write the step line.

usage: back-execute.py --task TASK_FOLDER --units u2 [u3 ...] --back REASON --model MODEL_ID [--data-dir DIR] [--task-dir DIR]

Checked before anything is written: `verify.md` has a `Run:` line; at least one of `verify.md`, `review.md`,
`changed-files.md` exists; at least one unit is named; every named unit is a `### u<n>` heading of `plan.md` with a
`- Status:` line; `.active` has a `phase:` line. A failed check prints one line naming the cause and exits 1.
Then, in order, each printed when done:
1. `archive.py --name run<N> --only verify.md review.md changed-files.md`;
2. `plan.md`: `- Status: pending` for the named units; when the plan's last unit is `my-agent:writer`, the plan has 2 or
   more units and a named unit is earlier, the last unit too;
3. `phase: 3` in `.active`;
4. `run-log.py step n=3A name=Execute back=<reason> archive=<folder> --model ...` (it writes the cost line itself).
A failure after the first write prints `back-execute: written: <list>; failed: <step>: <cause>` and exits 3.
exit: 0 done, 1 refused before writing, 2 bad arguments, 3 failed after writing.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_active  # noqa: E402
import ma_data  # noqa: E402
import ma_schema  # noqa: E402

HERE = Path(__file__).resolve().parent
JUDGMENTS = ('verify.md', 'review.md', 'changed-files.md')
UNIT = re.compile(r'^### (u\d+)\b', re.M)
STATUS = re.compile(r'^- Status:.*$', re.M)
WRITER = 'my-agent:writer'


def refuse(cause):
    print(f'back-execute: {cause}')
    return 1


def sections(text):
    """[(unit id, start, end)] of the `### u<n>` sections of a plan, in order."""
    out = []   # [id, start, end]; the open unit ends at the next `## ` or `### ` heading outside a fenced code block
    fence = False
    pos = 0
    for line in text.splitlines(keepends=True):
        if re.match(r'\s*(```|~~~)', line):
            fence = not fence
        elif not fence and re.match(r'#{2,3} ', line):
            if out and out[-1][2] is None:
                out[-1][2] = pos
            m = UNIT.match(line)
            if m:
                out.append([m.group(1), pos, None])
        pos += len(line)
    for s in out:
        if s[2] is None:
            s[2] = len(text)
    return [tuple(s) for s in out]


def pending_plan(text, units):
    """The plan text with `- Status: pending` for `units` (and the last writer unit, by the rule), or (None, cause)."""
    secs = sections(text)
    ids = [s[0] for s in secs]
    named = set(units)
    if secs and WRITER in text[secs[-1][1]:secs[-1][2]] and len(secs) >= 2 \
            and any(ids.index(u) < len(ids) - 1 for u in named):
        named.add(ids[-1])
    for unit, start, end in reversed(secs):
        if unit in named:
            body, n = STATUS.subn('- Status: pending', text[start:end], count=1)
            if not n:
                return None, f'{unit} has no Status line'
            text = text[:start] + body + text[end:]
    return text, None


def write_plan(path, text):
    Path(path).write_text(text, encoding='utf-8')


def call(script, *args):
    r = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--task', required=True)
    ap.add_argument('--units', nargs='*', default=[])
    ap.add_argument('--back', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--data-dir')
    ap.add_argument('--task-dir')
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    task = Path(args.task).resolve()
    verify = task / 'verify.md'
    run = ma_schema.RUN_LINE.search(verify.read_text(encoding='utf-8', errors='replace')) if verify.is_file() else None
    if not run:
        return refuse(f'{verify} has no `Run:` line')
    if not any((task / n).is_file() for n in JUDGMENTS):
        return refuse('nothing to archive')
    if not args.units:
        return refuse('no work unit named (--units u<n> ...)')
    plan = task / 'plan.md'
    try:
        plan_text = plan.read_text(encoding='utf-8')
    except OSError as exc:
        return refuse(f'cannot read {plan}: {exc}')
    have = [s[0] for s in sections(plan_text)]
    missing = [u for u in args.units if u not in have]
    if missing:
        return refuse(f'{", ".join(missing)} not a work unit of {plan}')
    new_plan, cause = pending_plan(plan_text, args.units)
    if cause:
        return refuse(cause)
    active = ma_active.find_active(str(task), ma_data.data_dir(args.data_dir), sub=args.task_dir)
    active_file = active.task_dir.parent / '.active' if active else None
    if active is None or active.task_dir != task:
        return refuse(f'no active my-agent task for {task}')
    active_text = active_file.read_text(encoding='utf-8', errors='replace')
    if not re.search(r'^phase:', active_text, re.M):
        return refuse(f'{active_file} has no `phase:` line')
    written = []

    def fail(step, why):
        print(f'back-execute: written: {"; ".join(written) or "nothing"}; failed: {step}: {why}')
        return 3

    code, out = call('archive.py', '--task', str(task), '--name', f'run{run.group(1)}', '--only', *JUDGMENTS)
    if code:
        print(out)
        return 1 if code == 1 else (2 if code == 2 else 3)
    folder = out.splitlines()[-1]
    written.append(folder)
    print(f'archive: {folder}')
    try:
        write_plan(plan, new_plan)
    except OSError as exc:
        return fail('plan.md', exc)
    written.append('plan.md')
    print(f'plan.md: Status pending for {" ".join(args.units)}')
    try:
        active_file.write_text(re.sub(r'^phase:.*$', 'phase: 3', active_text, count=1, flags=re.M), encoding='utf-8')
    except OSError as exc:
        return fail('.active', exc)
    written.append('.active')
    print('.active: phase: 3')
    extra = [a for k, v in (('--data-dir', args.data_dir), ('--task-dir', args.task_dir)) if v for a in (k, v)]
    code, out = call('run-log.py', 'step', 'n=3A', 'name=Execute', f'back={args.back}', f'archive={folder}',
                     '--model', args.model, '--cwd', str(task), *extra)
    if code:
        return fail('run-log', out or f'exit {code}')
    print(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
