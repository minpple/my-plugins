# Backlog

- [review] NITPICK tests/test_feature_pages.py:146 The regex that finds the card is tied to the card layout, so a layout change in the page gives a "no card" message that hides the cause → look for `coder-notes.md` inside one card block, or cut the card out with the file's existing helper (261117-notepads-learnings-handoff)
- [review] NITPICK plugins/my-agent/l1-orchestration/phases/build.md:16 The `Notes file` line name appears only in build.md; coder.md Input only says "when a notes file path is passed" → optional: also write a `Notes file` line in coder.md Input (261117-notepads-learnings-handoff)
- [review] NITPICK plugins/my-agent/l1-orchestration/phases/build.md:23 Item 4 "Coder notes" is one long entry of nearly ten sentences → optional: split it into sub-items when more content is added (261117-notepads-learnings-handoff)
- [review] NITPICK plugins/my-agent/l4-tools-guards/scripts/findings.py:64 `ma_logline.read` returns `[]` for an unreadable run-log, so the Fixed count is understated with no message; the Report tab behaves the same way (261120-g3-findings-auto)
- [review] NITPICK plugins/my-agent/l4-tools-guards/lib/ma_schema.py:661 `review_state` open items carry a `mark` field that `findings.py` ignores; harmless because `report.py` uses the same tuple shape (261120-g3-findings-auto)
- [review] NITPICK plugins/my-agent/l4-tools-guards/scripts/findings.py:68 Only plan-review handles a leading `SKIPPED <reason>`; a `scope-review.md` that starts with `SKIPPED` exits 1 with "no verdict line" (261120-g3-findings-auto)
