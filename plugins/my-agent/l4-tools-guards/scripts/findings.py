#!/usr/bin/env python3
"""Per-severity Found, Fixed and Open counts and the open items of a task's judgment file.

usage: findings.py --task TASK_FOLDER --file review|plan-review|scope-review

Prints `findings: <file name> (<n> round[s])`, the table `| Severity | Found | Fixed | Open |`, the line
`BLOCKER · <n> / SHOULD-FIX · <n> / NITPICK · <n>` (the open counts of the latest round) and the open items
(`- <severity> <where> <text>`, or `- none`).
review: all rounds (the archived copies, then the file), `Applied after review` lines and Review `fix` lines of the run-log.
plan-review, scope-review: all rounds of the current revision (the archived copies, one per `Run:`, then the file).
Each cell holds one number per round, oldest first, joined by `/` (one round: one number). Found(k) is every finding
round k lists (carried ones included). Open(k) of an earlier round is its findings that the next round lists again
(same severity and place); Open of the latest round is what it leaves open: not `applied` in `## Decisions` and
(plan-review) not named by a run-log `fix … before=G1-B` line written after the latest plan-reviewer call; a declined
finding stays open. Fixed(k) is Found(k) minus Open(k).
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


def tally(rounds, open_items):
    """{severity: (found, fixed, open)} with one number per round, oldest first. Found(k) is what round k lists; Open(k)
    is, for an earlier round, its findings the next round lists again (same severity and place) and, for the latest
    round, `open_items`; Fixed(k) is Found(k) minus Open(k)."""
    listed = [[(f[0], f[1]) for f in ma_schema.review_findings(text)] for text in rounds]
    counts = {sev: ([], [], []) for sev in ma_schema.SEVERITIES}
    for k, this in enumerate(listed):
        later = set(listed[k + 1]) if k + 1 < len(listed) else None
        left = [key for key in this if key in later] if later is not None else [(f[0], f[1]) for f in open_items]
        for sev in ma_schema.SEVERITIES:
            found = sum(1 for key in this if key[0] == sev)
            n_open = min(found, sum(1 for key in left if key[0] == sev))
            for cells, n in zip(counts[sev], (found, found - n_open, n_open)):
                cells.append(n)
    return counts


def output(header, counts, open_items):
    """`counts` is {severity: (found, fixed, open)}, each a list of per-round numbers; `open_items` are
    (severity, where, text, mark)."""
    out = [header, '| Severity | Found | Fixed | Open |', '|---|---|---|---|']
    out += [f'| {sev} | ' + ' | '.join('/'.join(map(str, cells)) for cells in counts[sev]) + ' |' for sev in ma_schema.SEVERITIES]
    out.append(' / '.join(f'{sev} · {counts[sev][2][-1]}' for sev in ma_schema.SEVERITIES))
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
        return output(header(name, totals), tally(ma_schema.review_rounds(task, text), open_items), open_items)
    if args.file == 'plan-review' and ma_schema.plan_review_skipped(first):
        print(f'findings: skipped ({first[len(ma_schema.PLAN_SKIPPED):].strip()})')
        return 0
    if not first.startswith(VERDICTS[args.file]):
        return fail(f'{path} has no verdict line ({" or ".join(VERDICTS[args.file])})')
    pairs = ma_logline.read(task / 'run-log.md') if args.file == 'plan-review' else []
    totals, open_items = ma_schema.judged_state(task, name, text, pairs)
    return output(header(name, totals), tally(ma_schema.judged_rounds(task, name, text), open_items), open_items)


if __name__ == '__main__':
    sys.exit(main())
