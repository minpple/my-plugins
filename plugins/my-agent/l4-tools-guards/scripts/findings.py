#!/usr/bin/env python3
"""Per-severity Found, Fixed and Open counts and the open items of a task's judgment file.

usage: findings.py --task TASK_FOLDER --file review|plan-review|scope-review

Prints `findings: <file name> (<n> round[s])`, the table `| Severity | Found | Fixed | Open |`, the line
`BLOCKER <n> · SHOULD-FIX <n> · NITPICK <n> (open)` and the open items (`- <severity> <where> <text>`, or `- none`).
review: the counts of the Report tab (all rounds, `Applied after review` lines and Review `fix` lines of the run-log).
plan-review, scope-review: all rounds of the current revision (the archived copies, one per `Run:`, then the file).
Open is what the latest round leaves open: not `applied` in `## Decisions` and (plan-review) not named by a run-log
`fix … before=G1b` line written after the latest plan-reviewer call; a declined finding stays open. Fixed is the rest.
A plan-review.md that starts with `SKIPPED <reason>` prints `findings: skipped (<reason>)`.
review also fails when review.md is older than the latest `start:` line of the reviewer in the run-log: the reviewer
returned its judgment without writing the file, so the file is an earlier run's.
exit: 0 counted (also with no finding) or skipped, 1 `findings: FAIL <cause>` (file missing or unreadable, no `BLOCKER <n>`
first line for review, a review.md older than the latest reviewer call, no verdict line for the others), 2 bad arguments.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_logline  # noqa: E402
import ma_schema  # noqa: E402

FILES = {'review': 'review.md', 'plan-review': 'plan-review.md', 'scope-review': 'scope-review.md'}
VERDICTS = {'plan-review': (ma_schema.PLAN_READY, ma_schema.PLAN_REVISE),
            'scope-review': (ma_schema.SCOPE_READY, ma_schema.PLAN_REVISE)}


def fail(cause):
    print(f'findings: FAIL {cause}')
    return 1


REVIEWER = 'my-agent:reviewer'


def latest_call(log, agent):
    """(stamp text, epoch seconds) of the last `start:` line of `agent` in the run-log, or None."""
    try:
        text = Path(log).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    stamps = [p[0] for p in map(ma_schema.split_line, text.splitlines()) if p and p[1] == 'start' and p[2].get('agent') == agent]
    try:
        return (stamps[-1], time.mktime(time.strptime(stamps[-1], '%Y-%m-%d %H:%M:%S'))) if stamps else None
    except (ValueError, OverflowError):
        return None


def first_line(text):
    return next((l.strip() for l in text.splitlines() if l.strip()), '')


def header(name, totals):
    rounds = totals['rounds']
    return f'findings: {name} ({rounds} round{"" if rounds == 1 else "s"})'


def tally(totals):
    return {sev: (totals[sev]['found'], totals[sev]['fixed'], totals[sev]['open']) for sev in ma_schema.SEVERITIES}


def output(header, counts, open_items):
    """`counts` is {severity: (found, fixed, open)}; `open_items` are (severity, where, text, mark)."""
    out = [header, '| Severity | Found | Fixed | Open |', '|---|---|---|---|']
    out += [f'| {sev} | {counts[sev][0]} | {counts[sev][1]} | {counts[sev][2]} |' for sev in ma_schema.SEVERITIES]
    out.append(' · '.join(f'{sev} {counts[sev][2]}' for sev in ma_schema.SEVERITIES) + ' (open)')
    out += [f'- {sev} {where} {body}'.rstrip() for sev, where, body, _mark in open_items] or ['- none']
    print('\n'.join(out))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--task', required=True, help='absolute task folder')
    ap.add_argument('--file', required=True, choices=sorted(FILES))
    args = ap.parse_args(argv)
    task, name = Path(args.task), FILES[args.file]
    path = task / name
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return fail(f'{path} is missing')
    except (OSError, UnicodeDecodeError) as exc:
        return fail(f'{path} cannot be read ({type(exc).__name__})')
    first = first_line(text)
    if args.file == 'review':
        if ma_schema.review_blockers(text) is None:
            return fail(f'{path} does not start with its blocker-count line (BLOCKER <n>)')
        call = latest_call(task / 'run-log.md', REVIEWER)
        if call and path.stat().st_mtime < call[1]:
            return fail(f'{path} is older than the latest reviewer call ({call[0]}): the reviewer wrote no file')
        totals, open_items = ma_schema.review_state(task, text, ma_logline.read(task / 'run-log.md'))
        return output(header(name, totals), tally(totals), open_items)
    if args.file == 'plan-review' and ma_schema.plan_review_skipped(first):
        print(f'findings: skipped ({first[len(ma_schema.PLAN_SKIPPED):].strip()})')
        return 0
    if not first.startswith(VERDICTS[args.file]):
        return fail(f'{path} has no verdict line ({" or ".join(VERDICTS[args.file])})')
    pairs = ma_logline.read(task / 'run-log.md') if args.file == 'plan-review' else []
    totals, open_items = ma_schema.judged_state(task, name, text, pairs)
    return output(header(name, totals), tally(totals), open_items)


if __name__ == '__main__':
    sys.exit(main())
