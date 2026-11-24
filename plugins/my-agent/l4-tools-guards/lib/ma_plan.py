"""Read the markers L1 writes into plan.md (architecture 4.4 G1b): the `Approved` line under `## Approval` and
the `Prototype: requested` line under `## Prototype`; and the `### u<n>` work units (4.8.2). Shapes: ma_schema."""
from pathlib import Path

import ma_schema


def read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return ''


def approved_text(text: str) -> bool:
    return ma_schema.approved_at(text) is not None


def prototype_text(text: str) -> bool:
    return ma_schema.prototype_requested_text(text)


def approved(plan_md: Path) -> bool:
    return approved_text(read(plan_md))


def prototype_requested(plan_md: Path) -> bool:
    return prototype_text(read(plan_md))


def scope_prototype_requested(scope_md: Path) -> bool:
    """`Prototype: requested` under `## Prototype` in scope.md (the G1a prototype); same shape as plan.md's."""
    return prototype_text(read(scope_md))


def scope_confirmed(scope_md: Path) -> bool:
    """A `Confirmed ` line under `## Confirmation` in scope.md (G1a Confirm)."""
    return ma_schema.scope_confirmed(read(scope_md))


def scope_background_ids(scope_md: Path):
    """The `b<n>` IDs under `## Background research` in scope.md; None when the section is missing."""
    return ma_schema.background_ids(read(scope_md))


def units(plan_md: Path) -> list:
    return ma_schema.units(read(plan_md))


def gaps(task_dir: Path, plan_text=None) -> list:
    """Plan gaps of a task folder (`ma_schema.plan_gaps`); `plan_text` stands in for plan.md as it would be written."""
    task_dir = Path(task_dir)
    plan = read(task_dir / 'plan.md') if plan_text is None else plan_text
    return ma_schema.plan_gaps(read(task_dir / 'scope.md'), plan, ma_schema.profile_of(read(task_dir / 'intake.md')),
                               records=task_dir.parent)
