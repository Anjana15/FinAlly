---
description: Independent review of all changes since the last commit, written to independent_review.md
---
Write a detailed, independent code review of all changes since the last commit.

1. Run `git status` and `git diff HEAD` to collect every change, including untracked files.
2. Review each change for bugs, logic errors, security issues, missing tests, and deviations from CLAUDE.md and planning/PLAN.md.
3. Write the review to `independent_review.md` at the repository root: a short summary, then findings ordered by severity, each with file:line, the problem, and a suggested fix. Finish with best-practice suggestions.

Do not modify any other files.
