"""One task folder → the report JSON of the Report tab (thirteen keys). Only reads files; a missing source gives a null key."""
import re
from pathlib import Path

from .mdfiles import read_intake
from .runlog import read_lines

import ma_gate_report
import ma_schema

SENTENCE = re.compile(r'^(.*?[.!?])(?:\s|$)')
TALLY_COST = 'Cost and tokens per stretch'
PICKED = {'yes': 'yes', 'no': 'no', 'delegated': 'delegated', 'typed (Other)': 'typed', 'prose reply': 'typed'}
GATE_MARKS = ('G1-A', 'G1-B', 'G3')
REVIEW_BODY_SEVS = ('SHOULD-FIX', 'NITPICK')   # the severities listed one by one at G3 (a BLOCKER stops the task earlier)
STATUS_WORD = {'done': 'done', 'stopped': 'aborted'}   # task status → verdict status; anything else is running
QUESTION_LINE = re.compile(r'^-\s*(b\d+):\s*(.+?)\s+—\s+\S')   # `- b<n>: <question> — <what it decides>`
NOT_FOUND = '- Not found:'
REVISION_TO = {'1': 2, '2': 3}   # `revision … to=` is the phase to go back to; the Report shows the step


def _text(path: Path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None


def _iso(ts):
    return ts.strftime('%Y-%m-%dT%H:%M:%S')


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _intake_fields(text):
    out = {}
    for line in (text or '').splitlines():
        key, sep, val = line.partition(':')
        if sep and key.strip() in ('Request', 'Follows') and key.strip() not in out:
            out[key.strip()] = val.strip()
    return out


def follows_of(intake_text):
    """The task id after `Follows:` in an intake.md text, or None."""
    return _intake_fields(intake_text).get('Follows') or None


def _overview(task, task_dir, intake, scope, plan, lines, followed_by, ko):
    delivered = base = None
    for l in lines:
        if l.kind == 'deliver' and l.f.get('path'):
            delivered = l.f['path']
        elif l.kind == 'base' and l.f.get('commit') and base is None:
            base = l.f['commit'][:7]
    if delivered is None:
        shown = (read_intake(task_dir / 'intake.md') or {}).get('delivered') or []
        delivered = shown[-1] if shown else None
    fields = _intake_fields(intake)
    background, purpose = ma_schema.overview_texts(scope, plan)
    out = {'task': task.get('id') or task_dir.name, 'profile': task.get('profile'), 'status': task.get('status'),
           'delivered': delivered, 'base': base, 'follows': fields.get('Follows') or None,
           'followed_by': list(followed_by), 'request': fields.get('Request') or None,
           'background': background, 'purpose': purpose}
    for key in ('background', 'purpose'):
        if key in ko:
            out[key + '_ko'] = ko[key]
    return out


def _ko(task_dir, scope, plan):
    """{key: Korean text} of the task's Korean copy items that still match their English source (`report-ko.json`)."""
    items = ma_schema.ko_copy(_text(task_dir / ma_schema.KO_COPY))
    return ma_schema.ko_current(ma_schema.ko_sources(scope, plan), items) if items else {}


def _cost_from_tally(text):
    """[{steps, span, usd, tokens}] from the stretch table of gate-tally.md, or None when it has no such section."""
    body = ma_schema.section_lines(text, TALLY_COST)
    if body is None:
        return None
    out = []
    for line in body:
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) != 4 or not line.strip().startswith('|') or not cells[0][:1].isdigit():
            continue
        try:
            usd = float(cells[2])
        except ValueError:
            usd = None
        steps = '' if cells[1] == '-' else cells[1]
        out.append({'steps': steps, 'span': cells[0].replace('–', '-'), 'usd': usd, 'tokens': _int(cells[3].replace(',', ''))})
    return out


def _cost_from_lines(lines):
    stamped = [(l.raw.strip()[11:16], l.kind, l.f) for l in lines]
    return [{'steps': ', '.join(names), 'span': f'{start}-{end}', 'usd': None if usd is None else round(usd, 2), 'tokens': tokens}
            for start, end, names, usd, tokens in ma_gate_report.segments(stamped)]


def _questions(scope):
    """[(id, question)] of the well-formed `- b<n>: <question> — <what it decides>` lines under `## Background research`
    of scope.md; a line not in this form is left out. Empty without the section."""
    out = []
    for line in ma_schema.section_lines(scope, 'Background research') or []:
        m = QUESTION_LINE.match(line.strip())
        if m:
            out.append((m.group(1), m.group(2).split(' — ')[0].strip()))
    return out


def _not_found(task_dir):
    """Number of lines starting with `- Not found:` in the `*.md` notes directly in the task's background folder
    (0 without them)."""
    total = 0
    for path in sorted((task_dir / 'background').glob('*.md')):
        total += sum(1 for l in (_text(path) or '').splitlines() if l.startswith(NOT_FOUND))
    return total


def _background_research(questions, lines, status):
    """The question group: [{id, question, state, secs}] from the `call:` and `stop:` lines with `unit=<id>`,
    or None without questions."""
    if not questions:
        return None
    out = []
    for qid, text in questions:
        calls = [l for l in lines if l.kind == 'call' and l.f.get('unit') == qid]
        stops = [l for l in lines if l.kind == 'stop' and l.f.get('unit') == qid]
        if not calls:
            state = 'pending'
        elif len(calls) > len(stops):
            state = 'running' if status == 'running' else 'stopped'
        else:
            state = 'done' if stops[-1].f.get('end') == 'ok' else 'stopped'
        out.append({'id': qid, 'question': text, 'state': state,
                    'secs': sum(_int(l.f.get('secs')) for l in stops) if stops else None})
    return out


def _timeline(task_dir, lines):
    steps, gates, backs, cur, starts, g3_asks = [], [], [], None, [], []
    g3_ask = g3_answer = wait_step = wait_by = None
    verifiers, stopped = [], {}   # (row, id) of each verifier start; id -> the time of its stop
    for l in lines:
        if l.kind == 'start' and l.f.get('agent', '').removeprefix('my-agent:') == 'verifier' and steps:
            verifiers.append((len(steps) - 1, l.f.get('id')))
        elif l.kind == 'stop' and l.f.get('id'):
            stopped[l.f['id']] = l.ts
        if l.kind == 'step' and l.f.get('n'):
            n = ma_schema.step_index(l.f['n'])
            if l.f.get('back'):
                backs.append({'from': cur, 'to': 5, 'at': _iso(l.ts), 'why': l.f['back'], 'row': len(steps) - 1 if steps else None})
            steps.append({'n': n, 'name': l.f.get('name', ''), 'start': _iso(l.ts)})
            starts.append(l.ts)
            cur = n
        elif l.kind == 'revision' and (ma_schema.gate_name(l.f.get('before')) == ma_schema.PLAN_EDIT_GATE or l.f.get('to') in REVISION_TO):
            to = 3 if ma_schema.gate_name(l.f.get('before')) == ma_schema.PLAN_EDIT_GATE else REVISION_TO[l.f['to']]
            backs.append({'from': cur, 'to': to, 'at': _iso(l.ts), 'why': l.f.get('why', ''),
                          'row': len(steps) - 1 if steps else None})
        elif l.kind == 'ask' and ma_schema.gate_name(l.f.get('gate')) in GATE_MARKS:
            if ma_schema.gate_name(l.f['gate']) == 'G3':
                g3_asks.append(l.ts)
            if not any(g['id'] == ma_schema.gate_name(l.f['gate']) for g in gates):
                gates.append({'id': ma_schema.gate_name(l.f['gate']), 'at': _iso(l.ts)})
                if ma_schema.gate_name(l.f['gate']) == 'G3':
                    g3_ask, wait_step = l.ts, cur
        elif l.kind == 'answer' and ma_schema.gate_name(l.f.get('gate')) == 'G3' and g3_ask is not None:
            g3_answer, wait_by = l.ts, l.f.get('by')
    end = g3_ask or (lines[-1].ts if lines else None)
    cost = _cost_from_tally(_text(task_dir / 'gate-tally.md'))
    if cost is None:
        cost = _cost_from_lines(lines)
    wait = {'step': wait_step, 'from': _iso(g3_ask), 'until': _iso(g3_answer)} if g3_ask and g3_answer else None
    if wait and wait_by == ma_schema.ANSWERED_BY_L1:
        wait['by'] = 'L1'
    held = {}   # 4A row -> the stop of a verifier started in its round after the 4B line (overlapping 4A and 4B)
    for row, vid in verifiers:
        stop = stopped.get(vid)
        for i in (row - 1, row):
            if stop and 0 <= i < len(steps) - 1 and (steps[i]['n'], steps[i + 1]['n']) == (7, 8):
                held[i] = max(held.get(i, stop), stop)
    chart_end = _rows(steps, starts, g3_asks, lines[-1].ts if lines else None, held)
    slots = {}
    for b in backs:
        b['slot'] = None
        if b['row'] is not None:
            b['slot'] = slots[b['row']] = slots.get(b['row'], -1) + 1
    return {'end': _iso(end) if end else None, 'chart_end': chart_end, 'slots': max(slots.values(), default=-1) + 1,
            'steps': steps, 'gates': gates, 'backs': backs, 'wait': wait, 'cost': cost}


def _rows(steps, starts, g3_asks, last, held=None):
    """Add end, secs, left and width to every row; return the chart end (ISO), the latest row end, or None without rows.
    A row ends at the next row's start; the last row at the latest G3 ask at or after its start, else at the last
    run-log line. A row never ends before it starts. `held` maps a 4A row to the stop of the round's verifier: when
    that is later than the 4B start (the two judges run together), the 4A row ends there and the rows overlap."""
    if not steps:
        return None
    ends = [max(starts[i], starts[i + 1], (held or {}).get(i, starts[i])) for i in range(len(steps) - 1)]
    tail = [t for t in g3_asks if t >= starts[-1]]
    ends.append(max(starts[-1], max(tail) if tail else (last or starts[-1])))
    t0 = starts[0]
    top = max(ends)
    span = max(1.0, (top - t0).total_seconds())
    for s, a, b in zip(steps, starts, ends):
        left = round(100 * (a - t0).total_seconds() / span, 3)
        right = round(100 * (b - t0).total_seconds() / span, 3)
        s.update(end=_iso(b), secs=int((b - a).total_seconds()), left=left, width=round(right - left, 3))
    return _iso(top)


def _short(text):
    m = SENTENCE.match(text)
    return m.group(1) if m else text


def _criteria(scope, plan, verify, ko=None):
    rows = ma_schema.criteria(scope) or ma_schema.criteria(plan)
    if not rows:
        return None
    verdicts = {n: (v, e) for n, v, e in ma_schema.verify_rows(verify)}
    out = []
    for n, text, _tag in rows:
        item = {'n': n, 'short': _short(text), 'title': text,
                'verdict': verdicts.get(n, (None, None))[0], 'evidence': verdicts.get(n, (None, None))[1]}
        if ko and f'c{n}' in ko:
            item.update(title_ko=ko[f'c{n}'], short_ko=_short(ko[f'c{n}']))
        out.append(item)
    return out


def _units(plan, lines, ko=None):
    units = ma_schema.unit_details(plan)
    if not units:
        return None
    secs = {}
    for l in lines:
        if l.kind == 'stop' and l.f.get('unit'):
            secs[l.f['unit']] = secs.get(l.f['unit'], 0) + _int(l.f.get('secs'))
    out = [{'id': u['id'], 'title': u['name'], 'status': u['status'], 'group': u['group'],
            'secs': secs.get(u['id'], 0), 'criteria': u['criteria'], 'files': u['files']} for u in units]
    for u in out:
        if ko and u['id'] in ko:
            u['title_ko'] = ko[u['id']]
    return out


def _review(text):
    if text is None:
        return None
    found = ma_schema.review_findings(text)
    applied = ma_schema.review_applied(text)
    blockers = ma_schema.review_blockers(text)
    out = []
    for sev, where, body, mark in found:
        item = {'sev': sev, 'where': where, 'text': body, 'applied': ma_schema.finding_applied(where, applied)}
        if mark:
            item['mark'] = mark
        out.append(item)
    return {'blockers': sum(1 for f in found if f[0] == 'BLOCKER') if blockers is None else blockers, 'findings': out}


def _plan_reviews(task_dir, lines):
    """One entry per distinct Run across archive/*/plan-review.md and plan-review.md; a later copy replaces an earlier one.
    `found` counts the findings of a run per severity; `fixed` those with an `applied` line in its Decisions or a
    run-log `fix … before=G1-B` line `Plan Review <SEVERITY> <where> …`."""
    files = sorted(task_dir.glob('archive/*/plan-review.md')) + [task_dir / 'plan-review.md']
    runs = {}
    for i, path in enumerate(files):
        text = _text(path)
        parsed = ma_schema.plan_review(text)
        if parsed:
            runs[parsed['run'] if parsed['run'] is not None else ('none', i)] = (parsed, text)
    if not runs:
        return None
    pairs = [(l.kind, l.f) for l in lines]
    out = []
    ordered = sorted(runs.values(), key=lambda r: (r[0]['run'] is None, r[0]['run'] or 0))
    for parsed, text in ordered:
        # the latest run takes only the `fix` lines written after its plan-reviewer call (as findings.py does)
        found, fixed, _open = ma_schema.judged_counts(text, ma_schema.pairs_of_round(pairs) if text is ordered[-1][1] else pairs)
        out.append({'run': parsed['run'], 'verdict': parsed['verdict'], 'blockers': parsed['blockers'],
                    'should_fix': parsed['should_fix'], 'nitpicks': parsed['nitpicks'], 'found': found, 'fixed': fixed})
    return out


def _decisions(lines):
    """Rows of `ma_gate_report.decisions` with the time of the answer line (or of the ask when unanswered)."""
    pairs = [(l, (l.raw.strip()[11:16], l.kind, l.f)) for l in lines if l.kind in ('ask', 'answer')]
    at, prev = {}, []
    for i in range(len(pairs)):
        rows = ma_gate_report.decisions([p for _, p in pairs[:i + 1]])
        for j, row in enumerate(rows):
            if j >= len(prev) or prev[j][3] != row[3] or prev[j][5] != row[5] or j not in at:
                at[j] = pairs[i][1][0]
        prev = rows
    rows = ma_gate_report.decisions([p for _, p in pairs])
    if not rows:
        return []
    return [{'n': j + 1, 'at': at.get(j, ''), 'gate': r[0], 'q': r[1], 'choice': r[3], 'picked': PICKED.get(r[4], r[4])}
            for j, r in enumerate(rows)]


def _gate_report(text, decisions):
    if text is None:
        return None
    recommended = None
    if decisions is not None:
        yes = sum(1 for d in decisions if d['picked'] == 'yes')
        recommended = {'picked': yes, 'counted': yes + sum(1 for d in decisions if d['picked'] == 'no')}
    return {'recommended': recommended, 'summary': ma_schema.gate_report_summary(text),
            'improvements': [{'level': a, 'strength': b, 'text': c} for a, b, c in ma_schema.gate_report_improvements(text)]}


def _passed(verify, total=0):
    """PASS rows of verify.md within the first `total` criteria (verify.md may also judge `Scope change:` lines after them)."""
    return sum(1 for n, verdict, _e in ma_schema.verify_rows(verify) if verdict == 'PASS' and (not total or n <= total))


def _verdict(task, intake, scope, plan, verify, lines, timeline, delivered):
    if not lines:
        return None
    commit = reason = step = None
    for l in lines:
        if l.kind == 'deliver' and (l.f.get('path') or '').startswith(ma_schema.DELIVERED_COMMIT):
            commit = l.f['path'][len(ma_schema.DELIVERED_COMMIT):]
        elif l.kind == 'abort' and l.f.get('why'):
            reason = l.f['why']
        elif l.kind == 'step' and l.f.get('n'):
            step = {'n': ma_schema.step_index(l.f['n']), 'name': l.f.get('name', '')}
    status = STATUS_WORD.get(task.get('status'), 'running')
    if reason is None:
        reason = ma_schema.aborted_reason(intake)
    rows = ma_schema.criteria(scope) or ma_schema.criteria(plan)
    criteria = {'pass': _passed(verify, len(rows)), 'total': len(rows)} if rows and verify is not None else None
    g3 = next((l.ts for l in lines if l.kind == 'ask' and ma_schema.gate_name(l.f.get('gate')) == 'G3'), None)
    usd = [c['usd'] for c in timeline['cost'] if c['usd'] is not None]
    return {'status': status, 'delivered': delivered, 'commit': commit, 'tag': None, 'reason': reason or None,
            'step': step if status != 'done' else None, 'criteria': criteria,
            'secs': int(((g3 or lines[-1].ts) - lines[0].ts).total_seconds()), 'usd': round(sum(usd), 2) if usd else None}


def _waiting_gate(lines):
    """The latest ask line of G1-A, G1-B or G3 with no later answer of the same gate, or None."""
    waiting = None
    for i, l in enumerate(lines):
        if l.kind == 'ask' and ma_schema.gate_name(l.f.get('gate')) in GATE_MARKS \
                and not any(m.kind == 'answer' and ma_schema.gate_name(m.f.get('gate')) == ma_schema.gate_name(l.f['gate']) for m in lines[i + 1:]):
            waiting = l
    return waiting


def _gate_background(gate, questions, task_dir):
    """The `background_research` value of a G1-A or G1-B gate: question count with ids (G1-A) or not-found count (G1-B)."""
    if not questions:
        return None
    if gate['id'] == 'G1-A':
        return {'questions': len(questions), 'ids': [q for q, _t in questions]}
    return {'questions': len(questions), 'not_found': _not_found(task_dir)}


def _gate(task, task_dir, scope, plan, verify, review, lines, totals, open_items):
    if task.get('status') != 'running':
        return None
    ask = _waiting_gate(lines)
    if ask is None:
        return None
    gate = {'id': ma_schema.gate_name(ask.f['gate']), 'at': _iso(ask.ts), 'q': ask.f.get('q', '')}
    if gate['id'] == 'G1-A':
        rows = ma_schema.criteria(scope) or ma_schema.criteria(plan)
        gate.update(purpose=ma_schema.overview_texts(scope, plan)[1], criteria=len(rows),
                    non_goals=ma_schema.section_bullets(scope, 'Non-goals'))
    elif gate['id'] == 'G1-B':
        lead = ma_schema.plan_lead(plan)
        units = [{'id': u['id'], 'title': u['title'], 'group': u['group']} for u in _units(plan, lines) or []]
        proto = (task_dir / 'prototype' / 'index.html').is_file()
        gate.update(summary=None if lead is None or lead.startswith('Profile:') else lead, units=units,
                    groups=len({u['group'] for u in units if u['group']}),
                    estimate=ma_schema.section_bullets(plan, 'Estimate'), models=ma_schema.models_table(plan),
                    prototype=f"/api/tasks/{task.get('key')}/prototype" if proto else None)
    else:
        rows = ma_schema.verify_rows(verify)
        criteria = ma_schema.criteria(scope) or ma_schema.criteria(plan)
        gate['verify'] = None if verify is None else {
            'verdict': ma_schema.verify_verdict(verify), 'run': ma_schema.run_number(verify), 'pass': _passed(verify, len(criteria)),
            'total': len(criteria) or len(rows), 'failed': [n for n, verdict, _e in rows if verdict == 'FAIL']}
        gate['review'] = None if review is None else {
            'blockers': _review(review)['blockers'], 'totals': totals,
            'open': [{'sev': sev, 'where': where, 'text': body, 'mark': mark}
                     for sev, where, body, mark in open_items if sev in REVIEW_BODY_SEVS]}
    return gate


def _takeaway(verdict, criteria, units, verify, timeline, gate_report):
    scope = delivered = nxt = None
    if criteria:
        scope = {'criteria': len(criteria), 'pass': sum(1 for c in criteria if c['verdict'] == 'PASS'),
                 'units': len(units or []), 'units_done': sum(1 for u in units or [] if u['status'] == 'done'),
                 'verify_run': ma_schema.run_number(verify),
                 'plan_rewrites': sum(1 for b in (timeline or {}).get('backs', []) if b['to'] == 3)}
    if verdict:
        delivered = {k: verdict[k] for k in ('status', 'delivered', 'commit', 'step')}
    items = (gate_report or {}).get('improvements') or []
    if items:
        pick = next((i for i in items if i['strength'] == 'clear'), items[0])
        nxt = {'text': pick['text'], 'clear': sum(1 for i in items if i['strength'] == 'clear'),
               'weak': sum(1 for i in items if i['strength'] == 'weak')}
    if scope is None and delivered is None and nxt is None:
        return None
    return {'scope': scope, 'delivered': delivered, 'next': nxt}


def build_report(project, task_dir, task, followed_by):
    """The report JSON of one task: `project` (Path), `task_dir` (Path), `task` (the monitor's task dict), `followed_by` (task ids)."""
    task_dir = Path(task_dir)
    intake, scope, plan = (_text(task_dir / n) for n in ('intake.md', 'scope.md', 'plan.md'))
    verify, review, report = (_text(task_dir / n) for n in ('verify.md', 'review.md', 'gate-report.md'))
    has_log = (task_dir / 'run-log.md').is_file()
    lines = read_lines(task_dir / 'run-log.md')
    decisions = _decisions(lines) if has_log else None
    ko = _ko(task_dir, scope, plan)
    overview = _overview(task, task_dir, intake, scope, plan, lines, followed_by, ko)
    timeline = _timeline(task_dir, lines) if has_log else None
    criteria = _criteria(scope, plan, verify, ko) if scope is not None or plan is not None else None
    units = _units(plan, lines, ko) if plan is not None else None
    gate_report = _gate_report(report, decisions)
    totals, open_items = ma_schema.review_state(task_dir, review, [(l.kind, l.f) for l in lines])
    questions = _questions(scope)
    gate = _gate(task, task_dir, scope, plan, verify, review, lines, totals, open_items) if has_log else None
    if gate and gate['id'] in ('G1-A', 'G1-B'):
        gate['background_research'] = _gate_background(gate, questions, task_dir)
    verdict = _verdict(task, intake, scope, plan, verify, lines, timeline, overview['delivered']) if has_log else None
    return {
        'overview': overview,
        'timeline': timeline,
        'criteria': criteria,
        'units': units,
        'background_research': _background_research(questions, lines, task.get('status')) if scope is not None else None,
        'review': _review(review),
        'plan_review': _plan_reviews(task_dir, lines),
        'decisions': decisions,
        'gate_report': gate_report,
        'verdict': verdict,
        'gate': gate,
        'takeaway': _takeaway(verdict, criteria, units, verify, timeline, gate_report),
        'review_totals': totals,
    }
