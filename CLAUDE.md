# Agent instructions

1. Read `docs/KNOWLEDGE.md` first. It maps every file, says where to edit for common changes, and lists the owner's rules.
2. **Keep `docs/KNOWLEDGE.md` up to date.** Any change to code, config, tests, structure or behaviour must update the relevant sections and add a line to its change log, in the same commit.
3. Work directly on the `develop` branch in this checkout. Do not create new branches or worktrees.
4. To test, build or check a change, follow the `utar-verify` skill (`.claude/skills/utar-verify/SKILL.md`): exact commands, known pitfalls and the pre-commit checklist.
5. Every change gets a change-log row in `docs/KNOWLEDGE.md` with its commit hash and files.
6. Bugs, failing tests, odd logs: follow the `systematic-debugging` skill (root cause before any fix).
   Before saying anything is done, fixed or passing: follow `verification-before-completion` and quote the
   command and its pass/fail counts.
7. Never contact the real UTAR server except `--test-real-server` when the owner asks. Never print personal
   data (name, IC, student ID, password) from `dist/UnitRegTimetable/logs`.

# Compact instructions

When compacting, keep: the owner's open requests and any decisions they made, files changed but not yet
committed, the last test commands with their pass/fail counts, commit hashes made this session, and any
`(pending)` change-log rows that still need a hash. Drop file dumps and full logs.
