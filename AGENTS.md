# AGENTS.md

Guidance for anyone — human or agent — working in this repository.

## What sift is

sift ranks a pile of documents against weighted criteria. Judgments come from a
model as typed answers and probabilities; the weights, thresholds and every gate
live in this code, not in a prompt. The shipped adapter reads arXiv preprints.

## Repository layout

```
backend/     the Python service — FastAPI, SQLAlchemy, Alembic, the CLI
frontend/    the React SPA — Vite, TypeScript
infra/       the AWS stack — Terraform
openapi.json the contract between them, generated from the backend
docker-compose.yml
```

They share no code and no build. The only thing crossing the boundary is HTTP,
described by `openapi.json`.

## Inside the backend — a fan, not a stack

Three tiers under `backend/src/sift/`, enforced by
`backend/scripts/check_layering.py` over the AST:

```
core/        pure domain: types, scoring, questions, profile.
             stdlib only, imports nothing else in the package

branches — each owns one heavy dependency, NONE may import another:
  judge/     the Asker protocol and its adapters
  storage/   SQLAlchemy models and repository functions
  ingest/    listing, fetching, text extraction

convergence — may import anything below:
  pipeline/  the batch runner and its state machine
  api/       the FastAPI application
  cli/       the command line
  mcp/       a read-only MCP server

settings.py is a root module anything may import.
```

A stack forces an ordering between siblings that have none, and then people
import sideways and the layering rots. The sibling ban gives the convergence
tier a definition instead of making it a leftover bucket: a module that needs
two capabilities belongs there by construction, and a module reaching sideways
for a fact is telling you that fact belongs in `core`.

The practical payoff is that importing `core` pulls in neither SQLAlchemy nor a
model SDK, so its tests stay fast.

## Conventions

- Functions over classes. Small, independently testable units.
- **Repositories are module-level functions taking a session.** SQLAlchemy
  models are the only classes in `storage/`.
- `mypy --strict` is green. Keep it that way.
- `core/` is pure: no network, no I/O, no clock.
- Comments describe the code as it stands, and stand on their own.

## Judging

Everything that talks to a model goes through one protocol:

```python
class Asker(Protocol):
    """A batch of requests in, one judgment per request out, in the same order."""
```

`FakeAsker` is the default and is deterministic, so the whole service runs with
no API key and no cost. `SIFT_ASKER` selects a live adapter instead.

Two rules the scoring deliberately keeps:

- Weights and thresholds live in `core/scoring.py` rather than in the questions,
  so changing how much something counts never means asking the model again.
- A dealbreaker is a gate, not a low weight — no amount of strength elsewhere
  should be able to average it away.

## Rate limits

arXiv asks for [one request every three seconds on a single
connection](https://info.arxiv.org/help/api/tou.html), and forbids rehosting
PDFs. So fetching is serialized with a minimum interval while judging runs in
parallel under its own budget — the pipeline has per-stage limiters, not one
global semaphore — and object storage holds extracted text, never the source
PDF.

## Running it

`.python-version` at the repo root selects the pyenv virtualenv for the whole
tree, so there is nothing to activate per directory. It names the virtualenv
`sift`, not a version number, which is why uv is pointed at the interpreter
explicitly rather than left to discover it.

```sh
docker compose up -d db          # Postgres on localhost:5433

cd backend
uv pip install --python "$(pyenv which python)" -e '.[service]' --group dev
python -m alembic upgrade head
python -m uvicorn sift.api.app:app --reload

cd ../frontend
pnpm install && pnpm dev         # http://localhost:5173
```

The dev server proxies `/api` to the API, so the browser only ever talks to its
own origin — the arrangement a CDN or load balancer will reproduce.

## Migrations

From `backend/`:

```sh
python -m alembic revision --autogenerate -m "what changed"
ruff format migrations/versions/   # the generated body is not formatted
python -m alembic upgrade head
```

`migrations/script.py.mako` is the template new migrations are stamped from; it
is customized so they come out under `mypy --strict` without hand-editing.
Always read what `--autogenerate` produced before applying it.

## The TypeScript client

`openapi.json` at the repo root is a build artifact of the backend, checked in,
and `frontend/src/api/schema.ts` is generated from it. Both are verified in CI,
so an API change that outruns the client is a diff in a pull request rather than
a runtime surprise.

```sh
cd backend  && python scripts/export_openapi.py   # FastAPI -> openapi.json
cd frontend && pnpm run generate                  # openapi.json -> schema.ts
```

## Deployment

The stack runs on AWS in `eu-west-2`, described by Terraform in `infra/`:
CloudFront in front of an S3 bucket for the SPA and an application load
balancer for `/api/*`, a Fargate service, and RDS Postgres. The prefix split at
the edge reproduces the dev server's proxy, so the browser is same-origin in
both places.

Deploying is a separate, manually triggered workflow — CI on every push says
whether `main` is deployable, `Deploy` says to deploy it. It builds the image,
registers a task definition revision, runs migrations as a one-off task, rolls
the service and publishes the site. GitHub Actions authenticates by OIDC; there
are no AWS keys in the repository.

`infra/README.md` has the runbook: first deployment, wiring up CI, attaching a
custom domain, and tearing the whole thing down.

## Checks

```sh
cd backend                                # needs `docker compose up -d db`
pytest
mypy
ruff check .
ruff format --check .
python scripts/check_layering.py
python scripts/export_openapi.py --check

cd ../frontend
pnpm run typecheck && pnpm run build
```
