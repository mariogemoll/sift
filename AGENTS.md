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
docs/        diagrams/ — SVG source, edited directly, embedded in README.md
docker-compose.yml
```

The diagrams are edited as SVG source. Each carries its own `<style>` with a
light and a `prefers-color-scheme: dark` palette, so it reads on either GitHub
theme; keep them in step with the code they depict.

They share no code and no build. The only thing crossing the boundary is HTTP,
described by `openapi.json`.

## Inside the backend — packages by topic

Code lives with its topic under `backend/src/sift/`, whether it is pure or
talks to the outside world:

```
api/  cli/   entry points
pipeline/    the harvester and the stage workers: the only place topics meet
storage/     SQLAlchemy models and repository functions
arxiv/       daily announcements, PDF download and extraction, the pacer
auth/        the passphrase, the session tokens it signs, the gate that checks them
judging/     questions, profile, scoring, the answer cache, text preparation,
             the Asker protocol and its adapters
types.py     the vocabulary the packages share: papers, batches, stages, pages
retry.py     what to do after a failure: try again later, or give up
settings.py  configuration from the environment
```

import-linter enforces the boundaries, from contracts in
`backend/pyproject.toml`:

- Each row imports only rows below it: entry points, then `pipeline`, then the
  topic packages (which may use one another), then `types`, then `retry`.
- **Pure modules import no third-party library, directly or through anything
  they import.** `types`, `retry`, `auth.passphrase` and every module in
  `judging` except `typesafe.py` are pure, so their tests need no database, no
  network and no API key.
- Judging, arXiv and auth never touch the database.
- Only `api` and `auth.gate` import FastAPI; only `judging.typesafe` imports the
  TypeSafe SDK.

A module that turns out to need I/O leaves the pure list, and the contract says
so, rather than moving to another package.

## Judging

Everything that talks to a model goes through one protocol:

```python
class Asker(Protocol):
    """A batch of requests in, one judgment per request out, in the same order."""
```

`FakeAsker` is the default and is deterministic, so the whole service runs with
no API key and no cost. `SIFT_ASKER=typesafe` selects Jev (`judging/typesafe.py`),
which needs `TYPESAFE_API_KEY`. An asker names its `model`, and the name is part
of the judgment cache key, so answers from one model are never read back as
another's; `SIFT_TYPESAFE_MODEL` is therefore a pinned version, not an alias.
The SDK runs with its own retries off: the pipeline's persisted, jittered retry
is the one policy.

What this deployment reads and how it ranks it is `backend/wishlist.toml`, in
the repository so a reader can see exactly what the model is asked: the arXiv
`categories` to harvest, a `background`, weighted `[[want]]` interests,
`[[dealbreaker]]` gates, and thresholds. The service refuses to start without a
category it can harvest. `POST /batches` takes a date and queues one batch per
category. Verdicts are filed under the wishlist's `name`, so a second wishlist
would rank the same papers separately.

Two rules the scoring deliberately keeps:

- Weights and thresholds live in `judging/scoring.py` rather than in the questions,
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

New papers come from arXiv's daily announcement of each category, as its RSS
feed (`rss.arxiv.org/rss/<category>`): the papers new to the category that day
and those cross-listed into it, with titles, authors and abstracts. Replacements
of older papers are in the feed too and are skipped. One request per category;
a day without an announcement is an empty one, not an error; an unknown category
is a 400 and terminal.

Two other routes were tried and do not work from where the service runs, which
is worth knowing before reaching for them again:

- The search API (`export.arxiv.org/api/query`) answers 406 to Python HTTP
  clients — any TLS handshake from Python's OpenSSL that offers ALPN, which
  httpx always does — while curl and `urllib` get through.
- OAI-PMH (`oaipmh.arxiv.org/oai`) can list any window of days, but from AWS its
  CDN answers large `ListRecords` requests with an empty 406 in milliseconds —
  cs.AI and cs.CL every time, fresh addresses and long pauses included — while
  the same requests succeed from elsewhere.

That is arXiv's filtering, not a bug to work around by disguising the client.
The feed covers what this service is for: the papers announced today.

## Batches and workers

`POST /batches` only queues: one batch per wishlist category, each to fetch that
category's latest announcement. Workers do the fetching, and every API process
runs one (`SIFT_WORKER=false` turns it off). They coordinate through the
`batches` table alone, with no queue in between:

- A step claims the oldest due batch with `SELECT … FOR UPDATE SKIP LOCKED`, so
  concurrent workers never take the same one, and stamps it with a lease: a
  fresh UUID and an expiry.
- It fetches the feed with no transaction open, taking a turn from the arXiv
  pacer, then records the papers and one item per paper in one transaction
  guarded by the lease UUID.
- A worker that dies or hangs simply stops renewing. Once its lease expires the
  next claim asks again; the dead worker's late writes no longer match the lease
  and are refused.
- Failures are sorted and retried like every other request to arXiv
  (`arxiv/failures.py`, `retry.py`): a refused request fails the batch at
  once, server trouble backs off with jitter, never sooner than a Retry-After,
  until the attempts run out.

At-least-once per batch, idempotent writes (papers on arXiv id, items on batch
and paper), no lost work. Asking for the same announcement twice costs nothing:
the papers exist, and every stage after is deduplicated. SQS or similar becomes
worth it when the database stops being a comfortable place to poll — not at
this scale.

## The funnel

Most papers are never worth reading, so most are never downloaded. Each
harvested paper becomes a batch item that waits for one stage at a time:

```
screen ──passes──▶ fetch ──▶ judge ──▶ done
   └──passed over───────────────────▶ done
any stage ──attempts run out, or a terminal failure──▶ dead
```

- **screen** asks the wishlist's questions of the title and abstract, which come
  with the listing. A paper passes if no dealbreaker blocks it and its fit
  reaches `screen_threshold`.
- **fetch** downloads and extracts the PDF, unless the paper's text is stored.
- **judge** asks merit, integrity and the same criteria of the text, with the
  reference list and what follows it cut away and the rest capped
  (`judging/text.py`): the model's input is bounded, and unrelated text costs
  accuracy.

Stages claim items exactly as the harvest claims batches — `SKIP LOCKED`, a
lease, writes guarded by it — and each is limited on its own: the screen and the
judge by how many workers run them, the fetch by the arXiv pacer. Every stage is
safe to repeat: answers are cached by a hash of all the model was given, text is
stored once per paper, and a verdict is written in place, so a paper in two
overlapping batches costs lookups, not a second download or a second answer. A
screen never replaces a full verdict.

With the fake asker, PDFs are not downloaded (`SIFT_DOWNLOAD` overrides): its
answers ignore the text, so a download would load arXiv for nothing. The judge
then reads the abstract, and nothing is stored in place of the text, so a later
run with a real model still fetches the paper.

The funnel exists for arXiv's sake, not the model bill's. Jev input costs cents
per thousand papers; three seconds per PDF makes a few thousand papers hours.

## Fetching full text

`arxiv/fetch.py` downloads a paper's PDF from `arxiv.org/pdf/<id>` and extracts
its text with pypdf; the PDF itself is never kept. The units underneath each
handle one way the network can misbehave:

- `arxiv/pacing.py` — a `Pacer` per host hands out one turn at a time, starting
  no sooner than the interval after the previous turn ended. A Retry-After holds
  the whole pacer, not just the request that was refused. One pacer serves both
  the announcements and the PDFs, since both go to arXiv. It is per process: several
  processes divide `SIFT_ARXIV_INTERVAL_SECONDS` between them.
- `arxiv/extract.py` — pypdf's text is cleaned before anything stores it:
  surrogate pairs it splits are rejoined, lone ones replaced, NUL dropped.
- `arxiv/pdf.py` — the body is streamed against a byte cap, and a deadline
  bounds the whole download. httpx's own timeouts are per read, so a server
  trickling one byte at a time would otherwise never trip them.
- `arxiv/failures.py` — sorts what went wrong into `Retryable` (5xx, 408, 425,
  429, broken connections) or `Terminal` (404, 410, other 4xx, not a PDF, over
  the cap, no text layer).
- `retry.py` — decides what comes next, with no clock or randomness: a
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

The deployed service judges with Jev; its TypeSafe key sits in Secrets
Manager beside the passphrase hash, both from the gitignored `terraform.tfvars`.

`infra/README.md` has the runbook: first deployment, wiring up CI, attaching a
custom domain, and tearing the whole thing down.

## Checks

```sh
cd backend                                # needs `docker compose up -d db`
pytest
mypy
ruff check .
ruff format --check .
lint-imports
python scripts/export_openapi.py --check

cd ../frontend
pnpm run typecheck && pnpm run build
```
