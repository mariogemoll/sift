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

## Getting in

One shared passphrase guards the interface; there are no accounts. The server
holds an scrypt hash of it (`SIFT_PASSPHRASE_HASH`, from `sift passphrase`) and
signs a session cookie whose key is derived from that hash:

```
signing key = HMAC(scrypt hash, "sift session v1")
```

That is one secret rather than two, and rotating the passphrase invalidates every
session already issued, because the key moves with the hash.

- `POST /auth/session` verifies the phrase and sets an HttpOnly, SameSite=Strict
  cookie; `DELETE` clears it; `GET` reports whether the caller holds one.
- The cookie carries its own signed expiry, so there is no session table.
- Routers that read data name `gate.guard`; `/health` stays open because the load
  balancer polls it and it reveals nothing.
- No hash configured means nobody gets in, not everybody. A deploy that loses the
  secret locks you out rather than opening the doors.

The cost of guessing is scrypt's cost, deliberately. There is no lockout: a
per-IP one behind CloudFront would mean trusting `X-Forwarded-For`, and a global
one would let a stranger lock the owner out.

## Rate limits

arXiv asks for [one request every three seconds on a single
connection](https://info.arxiv.org/help/api/tou.html). So fetching is
serialized with a minimum interval while judging runs in parallel under its own
budget — the pipeline has per-stage limiters, not one global semaphore.

The same terms allow storing and using the content of e-prints for personal use
or research, and forbid serving it: most papers carry arXiv's non-exclusive
license, which lets arXiv redistribute them and nobody else. So sift keeps the
extracted text it judges, discards the PDF once the text is out, and links to
arXiv for the paper itself rather than showing it.

## Listing papers

Metadata comes from arXiv's OAI-PMH interface (`oaipmh.arxiv.org/oai`), not the
search API at `export.arxiv.org/api/query`. The search API answers 406 to Python
HTTP clients — any TLS handshake from Python's OpenSSL that offers ALPN, which
httpx always does, HTTP/2 included — while curl and `urllib` get through. That
is arXiv's filtering, not a bug to work around by disguising the client, and
OAI-PMH is arXiv's recommended channel for bulk metadata anyway.

Two consequences. A window selects records by datestamp, the day a record last
changed, so it catches revised papers as well as new ones. And a response is one
page with a resumption token when more match. There is no reliable total:
`completeListSize` turns out to be the size of the page in hand, so a batch
reports pages and papers so far, and is done when a page arrives without a token.

## Batches and workers

`POST /batches` only queues. Workers harvest, and every API process runs one
(`SIFT_WORKER=false` turns it off). They coordinate through the `batches` table
alone, with no queue in between:

- A step claims the oldest due batch with `SELECT … FOR UPDATE SKIP LOCKED`, so
  concurrent workers never take the same one, and stamps it with a lease: a
  fresh UUID and an expiry.
- It fetches one listing page with no transaction open, then records the page —
  papers, items, the next resumption token — in one transaction guarded by the
  lease UUID, and releases the batch with `not_before` set one page interval
  ahead. That interval is what paces a harvest.
- A worker that dies or hangs simply stops renewing. Once its lease expires the
  next claim takes the batch and resumes from the last recorded token; the dead
  worker's late writes no longer match the lease and are refused.
- Failures are counted per batch: retryable ones back off and try again, a
  request arXiv rejects fails the batch at once.

At-least-once per page, idempotent writes (papers on arXiv id, items on batch
and paper), no lost work. SQS or similar becomes worth it when the database
stops being a comfortable place to poll — not at this scale.

## Fetching full text

`ingest/fetch.py` downloads a paper's PDF from `arxiv.org/pdf/<id>` and extracts
its text with pypdf; the PDF itself is never kept. The units underneath each
handle one way the network can misbehave:

- `ingest/pacing.py` — a `Pacer` per host hands out one turn at a time, starting
  no sooner than the interval after the previous turn ended. A Retry-After holds
  the whole pacer, not just the request that was refused.
- `ingest/pdf.py` — the body is streamed against a byte cap, and a deadline
  bounds the whole download. httpx's own timeouts are per read, so a server
  trickling one byte at a time would otherwise never trip them.
- `ingest/failures.py` — sorts what went wrong into `Retryable` (5xx, 408, 425,
  429, broken connections) or `Terminal` (404, 410, other 4xx, not a PDF, over
  the cap, no text layer).
- `core/retry.py` — decides what comes next, with no clock or randomness: a
  terminal failure gives up at once without spending attempts; a retryable one
  waits an exponential backoff with full jitter, never less than the server's
  Retry-After, until attempts run out.

Extracted text belongs in Postgres, in its own table beside `papers`, not in
object storage. That lets the text, the item's state change and the lease check
commit in one transaction; with a bucket, the object is written before the row
commits, so a worker dying in between — or one whose lease has already expired —
leaves an object no row points to. A paper's text is on the order of 100 KB and
Postgres compresses large values, so thousands of papers fit comfortably inside
the storage the database is allocated anyway. S3 becomes the better place when
the text outgrows that allocation (per gigabyte it is several times cheaper than
RDS storage) or when something other than the database needs to read it; then
the object is keyed by content hash, so a retried write is harmless, and the row
holds only the key.

## Running it

`.python-version` at the repo root selects the pyenv virtualenv for the whole
tree, so there is nothing to activate per directory. It names the virtualenv
`sift`, not a version number, which is why uv is pointed at the interpreter
explicitly rather than left to discover it.

```sh
docker compose up -d db          # Postgres on localhost:5433

cd backend
cp .env.example .env             # the dev passphrase is "sift"
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
