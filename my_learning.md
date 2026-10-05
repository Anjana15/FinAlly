# My Learning: Building FinAlly with Claude Code

Notes on the Claude Code features, commands and workflow used to build this project.

---

## 1. Project setup with agents

- **`CLAUDE.md`** is loaded into every Claude Code session automatically. Use it for the project's rules: architecture, commands, conventions. Generate a first draft with `/init`, then keep it up to date as the project changes.
- **`planning/PLAN.md`** is the authoritative spec. Agents coordinate through files in `planning/`, so update them whenever a decision changes the contract.
- **Spec review loop:** write the plan → run `/doc-review PLAN.md` → answer the questions inline (as in §13) → fold the answers back into the main sections so there is one source of truth.
- **`README.md`** is for humans: what the project is, how to run it, how to configure it. `CLAUDE.md` is for the agent.

## 2. Where Claude Code customizations live

| What | Location | How it's triggered |
|---|---|---|
| Project instructions | `CLAUDE.md` | Always loaded |
| Settings, permissions, hooks | `.claude/settings.json` (shared), `.claude/settings.local.json` (personal, gitignored) | Always active |
| Slash commands (legacy format) | `.claude/commands/<name>.md` | `/<name> args` (`$ARGUMENTS` = args) |
| Skills | `.claude/skills/<name>/SKILL.md` | Claude loads it when the `description` matches the task, or you type `/<name>` |
| Subagents | `.claude/agents/<name>.md` | Claude delegates, or you ask: "use the reviewer agent to…" |
| Plugins | Directory with `.claude-plugin/plugin.json` | Installed via `/plugin` |
| Memory | `~/.claude/projects/<project>/memory/` | Claude saves facts across sessions |

**In this repo:**
- `/doc-review` → `.claude/commands/doc-review.md` (reviews a file in `planning/`)
- `cerebras` skill → `.claude/skills/cerebras/SKILL.md` (how to call LiteLLM → OpenRouter → Cerebras)
- `reviewer` agent → `.claude/agents/reviewer.md` (independent review of changes since the last commit)
- `/independent-reviewer:review` → plugin command; writes `independent_review.md`

### Skill file format

```markdown
---
name: cerebras
description: Use this to write code to call an LLM using LiteLLM and OpenRouter with the Cerebras inference provider
---
Instructions + code snippets...
```

The `description` matters most: it's how Claude decides when to use the skill.

### Subagent file format

```markdown
---
name: reviewer
description: Reviews code changes since the last commit for bugs and convention violations. Use after finishing a feature.
tools: Read, Grep, Glob, Bash
---
You are an independent code reviewer. Run `git diff HEAD`, review every change,
and write findings to planning/independent_review.md...
```

Subagents run with their own fresh context, so they're useful for independent reviews and big searches.

## 3. Plugins and marketplaces

A **plugin** bundles commands, skills, agents and hooks so you can share them. A **marketplace** is a catalog (`marketplace.json`) listing plugins.

```bash
/plugin                                   # interactive UI: browse, install, enable/disable
/plugin list                              # show installed plugins
/plugin marketplace add ./                # register a local marketplace (this repo → "finally-plugins")
/plugin marketplace add anthropics/claude-plugins-official
/plugin install independent-reviewer@finally-plugins
/reload-plugins                           # pick up changes without restarting (if available)
```

Installed from the official marketplace: `code-review`, `code-simplifier`, `context7` (up-to-date library docs), `feature-dev`, `frontend-design`, `ralph-loop`.

**Expected plugin layout:**

```
independent-reviewer/
├── .claude-plugin/
│   └── plugin.json          # REQUIRED manifest: {"name": "independent-reviewer", "version": "1.0.0", ...}
├── commands/                # optional: slash commands
├── agents/                  # optional: subagents
├── skills/                  # optional: skills
└── hooks/hooks.json         # optional: hooks
```

The marketplace file goes at the **marketplace root**: here, `.claude-plugin/marketplace.json` at the repo root. Its `source` points to each plugin directory.

## 4. Hooks and triggers

Claude Code hooks are not Git hooks. They are shell commands that the harness runs automatically when Claude reaches certain events. The hook is the command; the trigger is the event.

**Valid events:** `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Notification`, `Stop`, `SubagentStop`, `PreCompact`, `SessionStart`, `SessionEnd`.
There is **no `Pre-commit` event.** To act before a commit, use `PreToolUse` with a `Bash` matcher.

**Correct format** (note the nested `hooks` array and `"type": "command"`):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "cd backend && uv run ruff format ." }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "echo 'Claude finished'" }
        ]
      }
    ]
  }
}
```

- `matcher` is a regex on the tool name (`Bash`, `Write|Edit`, `.*`).
- The hook receives JSON on stdin (tool name, input, session info).
- **Exit code 2** from a `PreToolUse` hook *blocks* the tool call, and stderr is shown to Claude. Use this for safety rules.
- Hooks can live in `.claude/settings.json` or in a plugin's `hooks/hooks.json`.
- Use `/hooks` to inspect them, or ask Claude: "add a hook that…" (the `update-config` skill).

Uses: formatting/linting after edits, running tests, blocking risky commands, notifications, enforcing repo conventions.

## 5. Commands used

### Claude Code slash commands

```
/init                 # generate CLAUDE.md from the codebase
/doc-review PLAN.md   # custom command: review a planning doc
/plugin, /plugin list # manage plugins
/code-review          # review the current diff (add --fix to apply fixes)
/simplify             # quality cleanup of changed code
/security-review      # security review of pending changes
/feature-dev          # guided feature development
/ralph-loop           # keep re-running a prompt until a task is done
/context              # see what's using the context window
/compact, /clear      # shrink or reset the conversation
/model, /fast         # switch model / toggle fast mode
/memory               # edit memory/CLAUDE.md files
/hooks, /agents       # inspect hooks / manage subagents
! <cmd>               # run a shell command and put its output in the conversation
# <text>              # quickly add a note to memory
Shift+Tab             # cycle permission modes (incl. plan mode)
Esc / Esc Esc         # interrupt / rewind to an earlier message
```

### Project commands (planned, see CLAUDE.md)

```bash
cd backend && uv sync && uv run pytest
cd backend && uv add litellm pydantic                 # deps for the cerebras skill
cd frontend && npm install && npm run build
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
docker compose -f test/docker-compose.test.yml up     # E2E with LLM_MOCK=true
```

### Git

```bash
git status
git diff HEAD                 # what changed since the last commit (what a reviewer should read)
git add -A && git commit -m "..."
git check-ignore -v <file>    # check whether a file is gitignored
```

## 6. Key lessons

- **Spec first, code second.** A reviewed plan with resolved questions saves agents from guessing.
- **One source of truth.** When a review answers a question, edit the spec itself; don't leave the answer only in an appendix.
- **Give agents contracts, not internals.** The plan fixes the API endpoints, the env vars and the directory boundaries, and leaves each agent to decide its own internal structure.
- **Make the app testable without secrets.** `LLM_MOCK=true` and the market simulator let E2E tests run with no API keys.
- **Skills are on-demand docs.** Use a skill like `cerebras` to keep Claude from guessing at a third-party API.
- **Use a fresh context for review.** A subagent or plugin reviewer doesn't share the author's assumptions.
- **Commit often.** Small commits make `git diff HEAD` reviews useful and mistakes easy to undo.

## 7. Fixes applied (2026-10-05)

1. **Reviewer plugin rebuilt.** The broken `hooks/hooks.json` is gone: `Pre-commit` isn't a hook event, and hooks can only run shell commands. The plugin now provides the `/independent-reviewer:review` command (`commands/review.md`), which writes `independent_review.md`.
2. **Plugin manifest fixed.** `test_plugin.json` became `.claude-plugin/plugin.json` with a kebab-case name, and the duplicate `marketplace.json` inside the plugin directory was removed. Both pass `claude plugin validate`.
3. **`.claude/agents/reviewer.md` filled in.** It now has frontmatter and a read-only review prompt.
4. **`.claude/settings.json` set to `{}`.**
5. **Database files gitignored.** `.gitignore` now covers `db/*.db` (plus journal/WAL files), and `db/.gitkeep` was added.
6. **`.env.example` added.** It contains no real keys.

**Still to do:**
- Run `/reload-plugins` (or restart Claude Code) so the reinstalled plugin is picked up.
- Commit `CLAUDE.md`, `planning/`, `.claude/`, the plugin and the config files to create a review baseline.
- Delete the old `my-learning.md`, which this file replaces.
- Fold the high-priority decisions from `planning/REVIEW.md` into `PLAN.md`.
