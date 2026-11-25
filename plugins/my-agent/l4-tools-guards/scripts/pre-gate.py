#!/usr/bin/env python3
"""The calls before a gate popup in one script: cost (G3), the `ask` line, the report text, the findings table, the pointer.

usage: pre-gate.py --gate G1-A|G1-B|G3 --task TASK_FOLDER q=TEXT rec=TEXT [--report-text FILE] [--data-dir DIR] [--task-dir DIR]

Every input is checked before the first write: `prose=`, `other=` and `pre=` are refused as run-log.py refuses them (exit 1,
nothing written, nothing opened); a --report-text file that is missing or lacks `### Overview`, `### Takeaway` or a
`| Item | Value |` table gives exit 3, nothing written. Then, in order, each through its own script:
1. `run-log.py ask gate=<gate> q= rec=` is written first (a failing `ask` leaves no cost line, prints its line, exits with its code);
2. G3 only: `run-log.py cost` (without cost data its one `run-log: no cost line (...)` line is printed and the call goes on);
   the printed order is the cost text, then the ask text, but the run-log order is `ask` then `cost` (so a failing `ask`
   leaves no cost line); the gate report cuts stretches at `cost` lines, so the G3 `ask` ends the review stretch;
3. the report text as it is (when given);
4. the findings heading (`### Scope Review findings` G1-A, `### Plan Review findings` G1-B, `### Review findings` G3) and
   the `findings.py` output; on a `findings: FAIL` line only that line is printed;
5. the `open-html.py --report <task> --pointer` line.
exit: 0 the gate can go on (also without cost data, with a findings FAIL or a missing judgment file), 1 refused input or no
active task, 2 bad arguments, 3 invalid report text.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_active  # noqa: E402
import ma_data  # noqa: E402

HERE = Path(__file__).resolve().parent
OPEN_HTML = HERE.parents[1] / 'monitor' / 'open-html.py'
FINDINGS = {'G1-A': ('### Scope Review findings', 'scope-review'), 'G1-B': ('### Plan Review findings', 'plan-review'),
            'G3': ('### Review findings', 'review')}
REFUSED = ('prose', 'other', 'pre')
TABLE = re.compile(r'(?m)^\|\s*Item\s*\|\s*Value\s*\|')


def run(script, *args):
    r = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.rstrip('\n'), r.stderr.strip()


def report_problem(path):
    """The cause when the report text file is not usable, else None."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError as exc:
        return f'cannot read the report text {path}: {exc}'
    lines = text.splitlines()
    for heading in ('### Overview', '### Takeaway'):
        if heading not in lines:
            return f'the report text lacks `{heading}`'
    if not TABLE.search(text):
        return 'the report text lacks a `| Item | Value |` table'
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--gate', required=True, choices=sorted(FINDINGS))
    ap.add_argument('--task', required=True)
    ap.add_argument('fields', nargs='*', metavar='key=value')
    ap.add_argument('--report-text')
    ap.add_argument('--data-dir')
    ap.add_argument('--task-dir')
    try:
        args = ap.parse_intermixed_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    given = {}
    for item in args.fields:
        key, sep, value = item.partition('=')
        if not sep or not key:
            print(f'pre-gate: {item!r} is not key=value', file=sys.stderr)
            return 2
        given[key] = value
    if not {'q', 'rec'} <= set(given) or set(given) - {'q', 'rec'} - set(REFUSED):
        print('pre-gate: needs q= and rec= (and nothing else)', file=sys.stderr)
        return 2
    bad = [f'{k}={given[k]}' for k in REFUSED if k in given]
    if bad:
        print(f'pre-gate: prose=, other= and pre= go on the answer line, not on ask (got {" ".join(bad)})', file=sys.stderr)
        return 1
    task = Path(args.task).resolve()
    active = ma_active.find_active(str(task), ma_data.data_dir(args.data_dir), sub=args.task_dir)
    if active is None:
        print(f'pre-gate: no active my-agent task for {task}')
        return 1
    if args.report_text:
        problem = report_problem(args.report_text)
        if problem:
            print(f'pre-gate: {problem}')
            return 3
    extra = [a for k, v in (('--data-dir', args.data_dir), ('--task-dir', args.task_dir)) if v for a in (k, v)]
    log = HERE / 'run-log.py'
    # `ask` is written first so a failing `ask` leaves no cost line; the cost text is still printed before the ask text
    code, ask_out, ask_err = run(log, 'ask', f'gate={args.gate}', f'q={given["q"]}', f'rec={given["rec"]}', '--cwd', str(task), *extra)
    if code:
        print(ask_out or ask_err)
        return code
    if args.gate == 'G3':
        _, out, err = run(log, 'cost', '--cwd', str(task), *extra)
        print(out or err)
    print(ask_out or ask_err)
    if args.report_text:
        print(Path(args.report_text).read_text(encoding='utf-8').rstrip('\n'))
    heading, name = FINDINGS[args.gate]
    _, out, err = run(HERE / 'findings.py', '--task', str(task), '--file', name)
    fails = [ln for ln in out.splitlines() if ln.startswith('findings: FAIL')]
    print(f'\n{heading}\n')
    print(fails[0] if fails else (out or err))
    pointer = ['--report', str(task), '--pointer'] + (['--data-dir', args.data_dir] if args.data_dir else [])
    _, out, err = run(OPEN_HTML, *pointer)
    print(f'\n{out or err}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
