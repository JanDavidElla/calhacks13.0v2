---
name: clean-code
description: Use whenever writing, editing, or refactoring code in this repo (client/ React + Vite, server/ FastAPI + uv). Enforces clean-code standards, making edits one at a time with an explanation and verified output so the user can review and accept each step, and the git commit/push workflow.
---

# Clean code, one edit at a time

The user is learning and wants to review every change. Work in small,
reviewable steps and show them proof that each one works.

## Workflow for every task

1. **Plan first.** Before touching files, list the edits you intend to make
   as a short numbered list (file + one-line purpose). Keep each edit small
   enough to review in under a minute.
2. **One edit per step.** Make exactly one logical edit (one file, or one
   tightly coupled change), then stop and present it:
   - **What:** the file and the change (`path/to/file:line`)
   - **Why:** one or two sentences on the reasoning
   - **Output:** run something that proves it works and show the real
     result: a test, `curl`, type check, lint, or build. Never invent output.
     If nothing can be run yet, say so.
3. **Wait for approval.** End the step by asking the user to accept, reject,
   or change it. Don't start the next edit until they reply.
4. **Teach briefly.** If the change uses a concept the user may not know
   (a hook, a dependency, a FastAPI feature), add one short "Concept" note.

## Clean-code standards

- Match the style, naming, and patterns already in the surrounding code.
- Small, single-purpose functions and components with descriptive names.
- No dead code, commented-out code, or unused imports.
- Comment only the non-obvious *why*, not the *what*.
- Handle errors at boundaries (API routes, fetch calls). Don't swallow them.
- Don't add dependencies or abstractions the task doesn't need.

### Client (`client/`, React + TypeScript)
- Function components and hooks. Type props explicitly, and avoid `any`.
- Call the API with relative paths (`fetch('/api/...')`); Vite proxies them.
- Verify with `npm run build` (type check + build) and `npm run lint`.

### Server (`server/`, FastAPI + uv)
- Add dependencies with `uv add <pkg>`, never `pip install`.
- Prefix routes with `/api`. Use type hints and Pydantic models for
  request/response bodies.
- Verify by running `uv run server` and `curl`-ing the endpoint.

## Committing and pushing

Only commit or push when the user asks. When they do, walk them through it:

1. `git status` and `git diff` to show what changed.
2. If on `main`, suggest a feature branch: `git switch -c <short-name>`.
3. `git add <files>`, then `git commit -m "<imperative summary>"`.
   Explain what each command does as you run it.
4. `git push -u origin <branch>`, then offer to open a PR with `gh pr create`.
