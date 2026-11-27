Verdict: ALL PASS
Run: 1

## Criteria

- 1. PASS: `add(a, b)` returns the sum. `calc.py` holds `return a + b`, and `tests/check_calc.py` passed in the check record (`checks/kept/261120-100000/01.log`: Ran 4 tests, OK).
- 2. PASS: `docs/guide.md` documents `add` and its arguments `a` and `b` (read the file).
- 3. PASS: `README.md` names `docs/guide.md`, and `tests/check_readme.py` passed in the same run (`checks/kept/261120-100000/01.log`: Ran 4 tests, OK).

## Commands run

- python3 -m unittest discover -s tests -p 'check_*.py' → Ran 4 tests in 0.001s, OK (checks.md)
