# Contributing

Six people share this repository. These rules exist so that parallel work
merges cleanly and `main` always runs.

## The one hard rule

**Never push directly to `main`.**

`main` must always be in a state a teammate can clone and run. Every change
arrives through a pull request.

## Before you start a branch

Always branch from an up-to-date `main`. Branching from a stale `main` is the
most common cause of a painful merge.

```bash
git checkout main
git pull origin main
git checkout -b feature/your-description
```

## Branch naming

```
feature/<description>     new functionality
fix/<description>         bug fix
docs/<description>        documentation only
refactor/<description>    restructuring, no behaviour change
```

Use lowercase and hyphens. Name the *thing*, not the ticket.

Good:
```
feature/product-upload
feature/ocr-processing
feature/compliance-rule-engine
feature/rule-management
fix/image-validation-mime-check
docs/architecture-diagram
```

Avoid: `feature/raghav-work`, `fix/bug`, `feature/new-stuff`.

## Where does my feature go?

Check the ownership table in [ARCHITECTURE.md](ARCHITECTURE.md). Work inside
your app's directory.

**Announce before editing shared files** — post in the team channel first:

- `backend/config/settings.py`
- `backend/config/api_v1.py`
- `ml/labelextract/contracts.py` — the agreement between the ML and backend
  teams; changing it changes both sides at once
- `backend/apps/core/`
- `.env.example`

## Implementation workflow

1. Branch from an updated `main`.
2. Write the code and its tests together.
3. Run **all three** suites locally (see below).
4. Update documentation in the same commit as the behaviour it describes.
5. Push and open a pull request into `main`.
6. Get one review. Rule changes need a reviewer who has also read the source.
7. Merge once CI and the reviewer are happy.

## Testing before a PR

All three must pass:

```bash
cd backend  && pytest        # needs PostgreSQL running
cd ml       && pytest        # no database needed
cd frontend && npm run lint
cd frontend && npm test
cd frontend && npm run build
```

CI runs exactly these on every pull request (`.github/workflows/ci.yml`), plus
`manage.py check` and `makemigrations --check`. Running them locally first
saves a round trip.

A PR that adds behaviour without a test will be asked for one.

**Do not write tests that assert nothing.** `assert True`, or a test that only
checks a function returns without error, is worse than no test: it makes the
suite look like it covers something it does not. Test observable behaviour —
given this input, this specific output.

The tests in `apps/compliance/tests/test_engine.py` encode the project's
honesty guarantees. If one of them fails, do not adjust the assertion to make
it pass — work out which guarantee you broke.

## Documentation expectations

Update docs in the same commit as the code:

| You changed | Also update |
|---|---|
| An API endpoint | `docs/api.md` |
| An environment variable | `.env.example` (or `frontend/.env.example`) |
| A model or a table | `ARCHITECTURE.md` |
| The rule file format | `rules/SCHEMA.md` |
| Setup steps or a dependency | `README.md` |
| An ML interface | `ml/README.md` |

A docstring explaining *why* a non-obvious decision was made is worth more than
one restating what the code does.

## Environment variables

- Every variable the code reads must be documented in `.env.example` with a
  comment saying what it does and whether it is required.
- Never add a variable to `.env.example` that nothing reads.
- Backend variables go in the **root** `.env`. Frontend variables go in
  `frontend/.env`.
- Give a variable a safe default in `settings.py` only where a wrong default is
  harmless. `DJANGO_SECRET_KEY` and the database credentials deliberately have
  **no** default, so a missing value fails loudly at startup instead of
  silently running with a value shared across every machine.

## Secrets

**Never commit a secret.** Not in code, not in a test, not in a comment, not in
a commit message, not "temporarily".

That means: `.env`, passwords, API keys, tokens, private keys, database
credentials, service-account JSON.

`.gitignore` covers `.env` and key files, but treat it as a safety net, not a
control. Check what you are staging:

```bash
git status
git diff --cached
```

**If you commit a secret**, tell the team immediately. Do not just delete it in
a follow-up commit — it stays in the history and in everyone's clone. The
secret must be **rotated**, and rewriting history is a coordinated operation.

`frontend/.env` deserves its own warning: Vite compiles every `VITE_` variable
into the JavaScript bundle. Anything there is public. Never put a secret in it,
even one that "only the frontend uses".

## Dependencies

**Do not add a dependency until the code that imports it exists.**

For Python:
- Runtime dependency → `backend/requirements.txt`
- Test-only dependency → `backend/requirements-dev.txt`
- Pin a compatible minor range: `Package>=1.2,<1.3`

For the frontend:
- **npm only.** Do not use pnpm or yarn — `pnpm-lock.yaml` and `yarn.lock` are
  git-ignored to prevent competing lockfiles.
- Commit `package-lock.json` with your `package.json` change, always.
- `node_modules/` is never committed.

Adding a large ML or OCR framework (PyTorch, TensorFlow, transformers, OpenCV,
a Tesseract wrapper, EasyOCR, PaddleOCR) is a **team decision**, not an
individual one. It affects install time and disk usage for all six people.
Raise it before you install it.

**Never commit model weights or datasets.** `.gitignore` blocks the common
extensions and `ml/artifacts/`, `ml/models/`, `ml/data/`. Once a 200 MB file is
in Git history it is in every clone forever. See `ml/README.md` for the
intended artifact storage strategy.

## Legal content — the rule that has no exceptions

This project makes regulatory compliance determinations. A confidently wrong
legal claim is worse than an admitted gap.

- **Never invent a rule number or a legal provision.** If you are not certain,
  leave `legal_reference` blank and set `source_status: "unverified"`.
- **Never mark a rule `verified` without filling in `source_note`** naming who
  checked it, against what, and when. The loader rejects the file if you do.
- **Never state that a declaration is mandatory** without having read the
  authoritative text — not a summary, not a blog post, not a model's answer.
- **Never hardcode a legal assumption in Python.** Rules are data in `rules/`.

See [`rules/README.md`](rules/README.md) for the authoring workflow.

## Pull request expectations

A PR should:

- Do **one thing**. A 40-file PR that mixes a feature with a refactor cannot be
  reviewed properly.
- Have a description saying what changed and why, and how you tested it.
- Have all three test suites and the linter passing.
- Include tests for new behaviour.
- Include documentation updates.
- Contain no commented-out code, no debug prints, no `.env`.

Suggested description template:

```markdown
## What
Short summary of the change.

## Why
The problem this solves.

## How I tested it
- [ ] backend: pytest
- [ ] ml: pytest
- [ ] frontend: npm run lint
- [ ] frontend: npm test
- [ ] frontend: npm run build
- [ ] Manually verified: <what you clicked>

## Notes for the reviewer
Anything surprising, or a decision worth a second opinion.
```

## Code style

**JavaScript / JSX** — enforced by ESLint (`npm run lint`, `npm run lint:fix`).
CI fails on any error. The config deliberately omits a formatter and stylistic
rules about quotes and semicolons: those create diff noise without catching
bugs. What it does enforce catches real problems — `react-hooks/exhaustive-deps`
is an error, because a missing dependency produces a stale closure that never
throws and is miserable to debug.

Conventions the linter does not check: 2-space indent, single quotes,
semicolons, named exports for components, `.jsx` for files containing JSX.

**Python** — no linter configured. Match the file you are editing: PEP 8,
4-space indent, ~88 character lines, double quotes, type hints on function
signatures, docstrings on modules and non-obvious functions. Adding Ruff would
be a reasonable follow-up; it is not configured now because nothing in the
current code violates a rule it would catch.

**Both** — comments explain *why*, not *what*. A comment restating the code
goes stale; a comment explaining a decision keeps paying off.

## Getting help

Stuck on setup? Work through the Troubleshooting table in
[README.md](README.md), then check `curl http://localhost:8000/api/v1/health/`.
It reports the database, the extraction engine and the rule counts in one
request, and it is the fastest way to find which piece is actually broken.
