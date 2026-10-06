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
/install-github-app   # install the Claude GitHub App + add the @claude and PR-review workflows (§9)
/sandbox              # view/change Bash sandbox settings (§8)
/reload-plugins       # reload plugins without restarting
& <prompt>            # send the prompt to a remote/cloud session (§8)
! <cmd>               # run a shell command and put its output in the conversation
# <text>              # quickly add a note to memory
Shift+Tab             # cycle permission modes (incl. plan mode)
Esc / Esc Esc         # interrupt / rewind to an earlier message
```

### Remote / cloud sessions

```bash
claude --remote       # run a Claude Code session in a cloud sandbox (§8)
# web: https://claude.ai/code
```

### Plugin validation

```bash
claude plugin validate <plugin-dir>   # check plugin.json / marketplace.json
```

### Project commands (real, after the agent-teams build)

```bash
# Backend (inside the Claude sandbox first: export UV_CACHE_DIR=$TMPDIR/uv-cache)
cd backend && uv sync
cd backend && uv run pytest                                   # all backend tests
cd backend && uv run pytest tests/db/test_trades.py::<name>   # one test
cd backend && LLM_MOCK=true uv run uvicorn app.main:app --port 8000   # dev server; serves frontend/out if built
cd backend && uv run python market_demo.py [--serve]          # market data only

# Frontend
cd frontend && npm install && npm run build   # static export -> frontend/out
cd frontend && npm test                       # Vitest unit tests
cd frontend && npm run lint                   # tsc --noEmit
cd frontend && npm run dev                    # :3000, proxies /api to :8000

# Docker / scripts
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
scripts/start_mac.sh [--build] [--no-open]    # stop: scripts/stop_mac.sh (Windows: .ps1); FINALLY_PORT overrides 8000

# E2E (LLM_MOCK=true, fresh DB each run)
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
docker compose -f test/docker-compose.test.yml down
cd test && npm ci && npx playwright test     # local run against BASE_URL; npm run report for the HTML report
```

### Git

```bash
git status
git diff HEAD                 # what changed since the last commit (what a reviewer should read)
git add -A && git commit -m "..."
git check-ignore -v <file>    # check whether a file is gitignored
git pull                      # bring in remote commits (e.g. the merged GitHub-app PR)
git log --oneline --graph -8  # see recent history, incl. merge commits
git log --stat -3             # which files each recent commit touched
git show --stat <commit>      # summary of one commit
ls -la                        # spot sandbox placeholders: they show as `crw-rw-rw- ... 1, 3` (§8)
```

## 6. Key lessons

- **Spec first, code second.** A reviewed plan with resolved questions saves agents from guessing.
- **One source of truth.** When a review answers a question, edit the spec itself; don't leave the answer only in an appendix.
- **Give agents contracts, not internals.** The plan fixes the API endpoints, the env vars and the directory boundaries, and leaves each agent to decide its own internal structure.
- **Make the app testable without secrets.** `LLM_MOCK=true` and the market simulator let E2E tests run with no API keys.
- **Skills are on-demand docs.** Use a skill like `cerebras` to keep Claude from guessing at a third-party API.
- **Use a fresh context for review.** A subagent or plugin reviewer doesn't share the author's assumptions.
- **Commit often.** Small commits make `git diff HEAD` reviews useful and mistakes easy to undo.
- **Contracts let agents run in parallel.** A binding contract (ownership, signatures, HTTP shapes, test ids) is what made the agent team work (§13).
- **Ignore rules can hide source.** Check `git check-ignore` before trusting `git add -A` (§14).

## 7. Fixes applied (2026-10-05)

1. **Reviewer plugin rebuilt.** The broken `hooks/hooks.json` is gone: `Pre-commit` isn't a hook event, and hooks can only run shell commands. The plugin now provides the `/independent-reviewer:review` command (`commands/review.md`), which writes `independent_review.md`.
2. **Plugin manifest fixed.** `test_plugin.json` became `.claude-plugin/plugin.json` with a kebab-case name, and the duplicate `marketplace.json` inside the plugin directory was removed. Both pass `claude plugin validate`.
3. **`.claude/agents/reviewer.md` filled in.** It now has frontmatter and a read-only review prompt.
4. **`.claude/settings.json` set to `{}`.**
5. **Database files gitignored.** `.gitignore` now covers `db/*.db` (plus journal/WAL files), and `db/.gitkeep` was added.
6. **`.env.example` added.** It contains no real keys.

**Follow-ups:**
- ✅ Committed `CLAUDE.md`, `planning/`, `.claude/`, the plugin and config files (commit `27f2fdb`) as the review baseline.
- ✅ Deleted the old `my-learning.md`.
- Run `/reload-plugins` (or restart Claude Code) so the reinstalled plugin is picked up.
- Fold the high-priority decisions from `planning/REVIEW.md` into `PLAN.md`.

## 8. Sandboxing

Claude Code can run every Bash command inside an OS-level sandbox (bubblewrap on Linux/WSL, Seatbelt on macOS). It is applied **per command**, not to the whole session.

- **Filesystem:** writes are allowed only in the project directory, `$TMPDIR` and a session scratchpad. Settings files, `.claude/skills`, `.claude/hooks` and dotfiles such as `.bashrc` and `.gitconfig` are write-protected, even inside the project.
- **Network:** traffic goes through a filtering proxy. Hosts that aren't allowlisted are refused, and the refusal is reported back to Claude.
- **Escape hatch:** a command that fails because of the sandbox can be retried with the sandbox disabled, which goes through the normal permission prompt.
- **`/sandbox`** shows and changes the sandbox settings.
- **Why it matters:** with a sandbox, auto/accept modes are much safer. Claude can work for a long time with few prompts while it can't touch credentials, other projects or system config.

**Gotcha seen in this repo:** bubblewrap protects some paths by mounting `/dev/null` over them. In the project directory that leaves stray entries such as `.bashrc`, `.gitconfig`, `.mcp.json`, `.idea`, `.vscode` and `.claude/hooks`, which `ls -la` shows as character devices (`crw-rw-rw- … 1, 3`). `git status` lists them as untracked. **Don't commit them.** Add them to `.gitignore` or ignore them.

### 4 ways to run Claude Code in an isolated (sandboxed/cloud) environment

| # | How | What happens |
|---|---|---|
| 1 | `& <prompt>` in the Claude Code CLI | A leading `&` hands the prompt off to a remote/cloud session instead of running it locally (tried here with `& what's 2+2`) |
| 2 | `claude --remote` | Starts a Claude Code session that runs remotely in a cloud sandbox rather than on your machine |
| 3 | GitHub (`@claude` via GitHub Actions) | Claude runs on a GitHub runner, isolated from your machine. See §9 |
| 4 | claude.ai/code (web) | Claude Code in the browser, working on a cloud copy of the repo. Results come back as a branch or PR |

On top of these, the **local Bash sandbox** described above isolates each command when Claude runs on your own machine.

The three market-data docs in §10 were written by Claude running inside the sandbox (commit `7bc8070`, "added documents through sandboxing").

## 9. GitHub integration (`/install-github-app`)

`/install-github-app` installs the Claude GitHub App on the repo, stores a `CLAUDE_CODE_OAUTH_TOKEN` secret, and opens a PR that adds two workflows. Here that was PR #1, merged as `ea0ad5a`.

| Workflow | Trigger | What it does |
|---|---|---|
| `.github/workflows/claude.yml` | `@claude` in an issue, an issue comment, a PR review or a PR review comment | Runs Claude Code on the request. For example, "@claude fix this bug" can make it push a branch and open a PR. |
| `.github/workflows/claude-code-review.yml` | PR opened, updated, marked ready or reopened | Runs `/code-review:code-review --comment` from the `code-review` plugin and posts inline review comments |

Both use `anthropics/claude-code-action@v1`. Useful knobs:
- `prompt:` — fixed instructions (otherwise Claude does what the `@claude` comment says).
- `claude_args:` — CLI flags, e.g. `--allowedTools "Bash(gh pr *)"`.
- `plugin_marketplaces:` / `plugins:` — load plugins in CI.
- `paths:` under `on.pull_request` — only review PRs that change certain files.
- `permissions:` — keep them minimal; `actions: read` lets Claude read CI results.

After the merge, run `git pull` locally so `main` includes the workflows.

## 10. Market data design docs (`planning/`)

These are written before any code, so the backend agent has a contract to follow:

- **`MARKET_INTERFACE.md`**: the unified Python API. It covers the data model, the in-memory price cache, the abstract source interface, the simulator and Massive implementations, and a factory that picks one from `MASSIVE_API_KEY`. It also says how consumers (SSE, trades, chat) use it and how to test it.
- **`MARKET_SIMULATOR.md`**: GBM with correlated moves and random shock events, seed prices, the engine and data source split, tunable parameters, and tests.
- **`MASSIVE_API.md`**: Massive (formerly Polygon.io) REST reference. It covers auth (prefer the header to the query param, so keys stay out of logs), multi-ticker snapshots, end-of-day aggregates, market status, how to pick "the price" from a snapshot, a free-tier polling strategy, and code examples.

**Lesson:** research third-party APIs into a reference doc once, then point agents at it. That's the same idea as the `cerebras` skill: don't let the agent guess at an external API.

## 11. Other small things

- **Commit hygiene:** after `/install-github-app` the remote got ahead (merge commit). Pull before continuing local work to avoid diverging history.
- **Switching branches with uncommitted edits:** git refuses if the other branch changes the same file. Use `git stash push -m "<why>" -- <file>`, then `git checkout <branch>`, then `git stash pop` (expect conflicts if both versions changed) or `git stash list` / `git stash show -p stash@{0}` to look first.
- **Sandbox-protected files don't switch branches.** `.claude/settings.json` is bind-mounted read-only by the sandbox, so `git checkout agent-teams` failed to update it ("Device or resource busy") and it shows as modified. Fix it from outside the sandbox: `! git checkout -- .claude/settings.json`, then restart Claude Code.

## 12. Issue → PR with `@claude` (market data backend)

1. Consolidate the three research docs into one build doc with complete code and tests: `planning/MARKET_DATA_DESIGN.md` (PR #2).
2. Open GitHub issue #3 mentioning `@claude` and pointing at that doc.
3. The action creates branch `claude/issue-3-<timestamp>`, implements `backend/app/market/` (interface, cache, simulator, Massive client/source, factory, SSE, tracking) with tests, and opens PR #4 as `claude[bot]`.
4. The review workflow comments; reply `@claude <fix>` to iterate; merge; `git pull`.

```bash
gh issue create --title "..." --body "@claude implement planning/MARKET_DATA_DESIGN.md"
gh pr list && gh pr checkout 4 && gh pr view 4 --comments
gh run list && gh run view <id> --log
```

**Lesson:** when the design doc already contains the code and the tests, an unattended agent (or a cheaper model) only has to copy, wire up and verify, so it rarely goes wrong.

## 13. Agent Teams (branch `agent-teams`, commit `72cb929`)

The whole v1 app (backend db/services/api/llm, Next.js frontend, Docker, scripts, Playwright E2E: 97 files, ~11.8k lines) was built in one session by an **agent team**: a lead plus teammates working in parallel.

**Enabling it** (`.claude/settings.json`, experimental):

```json
{
  "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" },
  "teammateMode": "in-process",
  "enabledPlugins": {
    "frontend-design@claude-plugins-official": true,
    "context7@claude-plugins-official": true,
    "playwright@claude-plugins-official": true
  }
}
```

- `teammateMode: "in-process"` runs the teammates inside the same Claude Code process, so there's no need for tmux/split panes.
- Teammates have their own context windows and talk to each other by messages; the lead coordinates.
- Restart Claude Code after changing `settings.json`.

**The team** (from `planning/TEAM_CONTRACT.md` §1):

| Teammate | Owns |
|---|---|
| lead | `planning/`, `CLAUDE.md`, `README.md`, coordination, **all commits** |
| db-engineer | `backend/app/db/**` + tests |
| backend-api | `main.py`, `api/**`, `services/**` (the one trade path), deps |
| llm-engineer | `backend/app/llm/**` (schema, prompt, LiteLLM client, mock, chat router) |
| frontend | `frontend/**` |
| devops | `Dockerfile`, `.dockerignore`, `scripts/**`, compose file, `.gitignore`, `.env.example` |
| integration-tester | `test/**` (Playwright), `planning/E2E_REPORT.md` |

`backend/app/market/**` was frozen: it already existed (from PR #4) with passing tests.

**What made it work: a binding contract written before anyone coded.** `planning/TEAM_CONTRACT.md` holds:
1. **File ownership:** only edit files you own; message the owner otherwise. Parallel agents never collide.
2. **Exact Python signatures** (`app.db`, `app.services`, `app.llm`), so dependants code against interfaces that don't exist yet.
3. **HTTP shapes**, including one error shape `{"error","detail"}` (return `JSONResponse`, not `HTTPException`, which would nest it under `detail`).
4. **Deterministic `LLM_MOCK` rules** ("buy 2 AAPL" → a trade, "add X" → watchlist change, else a fixed message), executed through the *real* trade path.
5. **Stable `data-testid`s** that the frontend must provide and the E2E tests use exclusively.
6. **Process:** unit tests come with your code; message lead + integration-tester with a one-line status when usable; bugs go to the owner, who replies "fixed: <summary>"; contract changes go in a **Changelog** at the bottom and are messaged to everyone affected.

**Integration testing as a teammate** (`planning/E2E_REPORT.md`):
- Run 1: backend only, while the frontend was still failing to build: 16/16 API tests passed.
- Run 2: full stack. 36/40 at first, but all 4 failures were *test* bugs (wording-based asserts, a race on history loading, `setOffline` not killing an EventSource, a race on `unroute`). Then 40/40 twice with 0 flaky.
- Run 3: the official Docker path: 40/40 in ~27 s.
- One real issue (E2E-001: quantities shown as `1e+06`) was filed to db-engineer and fixed the same day.

**Lessons:**
- Spend the first part of the session on the contract; it's what lets 6 agents work at once without stepping on each other.
- Tester-owned E2E with only contract selectors catches cross-team mismatches; when tests fail, check whether the *test* is wrong before blaming the app.
- One committer (the lead) keeps history clean.
- Update `CLAUDE.md` at the end so the next session sees the real commands (it now says "v1 build is complete").

**Sandbox notes for teams** (also in the contract §7 and E2E report):
- `export UV_CACHE_DIR=$TMPDIR/uv-cache`; `PLAYWRIGHT_BROWSERS_PATH=$TMPDIR/pw-browsers`; `npm_config_cache=$TMPDIR/npm-cache`.
- Background processes don't survive between sandboxed commands, so start the backend **in the same command** as `npx playwright test`.
- The Chromium download needs `storage.googleapis.com` and `cdn.playwright.dev` allowed.
- Port 8000 was taken by another container locally, so the local E2E wrapper uses `PORT` (default 8013) and `BASE_URL`.

## 14. Gotchas found

- **`frontend/src/lib/` was gitignored and left out of the Agent Teams commit (fixed in `df4eee5`).** The Python `.gitignore` template's `lib/` rule matches a `lib/` folder at any depth (`git check-ignore -v frontend/src/lib/api.ts` → `.gitignore:17:lib/`). 14 frontend files import `@/lib/...` (`api`, `format`, `prices`, `portfolio`, `treemap`, `types`), so a fresh clone of `72cb929` can't build. It still worked locally because the files existed on disk. Fix: anchor the rule to the repo root as `/lib/`, then `git add frontend/src/lib` and commit (frontend tests: 24/24 passing). **Lesson:** a passing local build doesn't prove the commit is complete; check from a fresh clone, or run `git status --ignored`.
- Before a big commit, check what's ignored and untracked: `git status --short --ignored`, `git status --short -uall | grep -v node_modules`, `git check-ignore -v <path>`.
- Stale `__pycache__`-only dirs on `main` (`backend/app/api`, `db`, `llm`, `services`) were leftovers of this build on another branch; they disappear once you're on `agent-teams`.
