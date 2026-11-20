#!/usr/bin/env python3
"""Per-severity Found, Fixed and Open counts and the open items of a task's judgment file.

usage: findings.py --task TASK_FOLDER --file review|plan-review|scope-review

Prints `findings: <file name>` (review adds ` (<n> round[s])`), the table `| Severity | Found | Fixed | Open |`, the line
`BLOCKER <n> · SHOULD-FIX <n> · NITPICK <n> (open)` and the open items (`- <severity> <where> <text>`, or `- none`).
review: the counts of the Report tab (all rounds, `Applied after review` lines and Review `fix` lines of the run-log).
plan-review, scope-review: the findings of the current file; fixed = `applied` in `## Decisions` (plan-review also a
run-log `fix … before=G1b` line); a declined finding stays open.
A plan-review.md that starts with `SKIPPED <reason>` prints `findings: skipped (<reason>)`.
exit: 0 counted (also with no finding) or skipped, 1 `findings: FAIL <cause>` (file missing or unreadable, no `BLOCKER <n>`
first line for review, no verdict line for the others), 2 bad arguments.
"""
import argparse
import sys
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


def first_line(text):
    return next((l.strip() for l in text.splitlines() if l.strip()), '')


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
        totals, open_items = ma_schema.review_state(task, text, ma_logline.read(task / 'run-log.md'))
        counts = {sev: (totals[sev]['found'], totals[sev]['fixed'], totals[sev]['open']) for sev in ma_schema.SEVERITIES}
        rounds = totals['rounds']
        return output(f'findings: {name} ({rounds} round{"" if rounds == 1 else "s"})', counts, open_items)
    if args.file == 'plan-review' and ma_schema.plan_review_skipped(first):
        print(f'findings: skipped ({first[len(ma_schema.PLAN_SKIPPED):].strip()})')
        return 0
    if not first.startswith(VERDICTS[args.file]):
        return fail(f'{path} has no verdict line ({" or ".join(VERDICTS[args.file])})')
    pairs = ma_logline.read(task / 'run-log.md') if args.file == 'plan-review' else []
    found, fixed, open_items = ma_schema.judged_counts(text, pairs)
    counts = {sev: (found[sev], fixed[sev], found[sev] - fixed[sev]) for sev in ma_schema.SEVERITIES}
    return output(f'findings: {name}', counts, open_items)


if __name__ == '__main__':
    sys.exit(main())
