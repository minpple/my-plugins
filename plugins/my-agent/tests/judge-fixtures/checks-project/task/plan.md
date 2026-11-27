# Plan: calc mul

## Work units

### u1 Add mul

- Agent: `my-agent:coder`
- Files to change:
  - `calc.py`
  - `tests/check_calc.py`
- Change: add `mul(a, b)`, which returns `a * b`, and its test.
- Check commands: `python3 -m unittest discover -s tests -p 'check_*.py'` (criterion 1)
- Parallel group: group 1
- Completion criteria: 1
- Status: done

## Approval

- Approved 2026-10-25 09:30 G1-B
