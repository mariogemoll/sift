# sift

sift reads each day's new arXiv papers in the categories you care about and
ranks them against a written wishlist: what you want to read, how much each
interest counts, and what should rule a paper out.

A language model answers narrow questions about each paper ("how well does this
paper address *root-cause analysis across data sources*, on a scale of 0 to 3?",
"what is the probability that it is about predicting prices?"). The model never
produces the ranking. Weights, thresholds and dealbreakers live in code, so
changing how much something counts never means asking the model again.

## What happens when you ask for today's papers

![Sequence of one request: queue, harvest, screen, fetch, judge, watch](docs/diagrams/timeline.svg)

1. **Queue.** The button in the web app calls `POST /batches`, which only writes
   one row per wishlist category and returns.
2. **Harvest.** A worker picks up each batch, fetches that category's daily
   announcement from arXiv's RSS feed, and stores the papers. Each paper becomes
   an *item* that waits for its first stage.
3. **Screen.** Every paper is judged on its title and abstract alone. Most stop
   here.
4. **Fetch.** Papers that pass have their PDF downloaded and their text
   extracted. The text is kept and the PDF is discarded.
5. **Judge.** The full text, without its reference list, is judged again, now
   also for merit and for signs of a broken or manipulative document.
6. **Watch.** The web app refreshes every two seconds while anything is still
   moving, and shows the papers best first.

### The life of a paper

![States of an item and of a batch](docs/diagrams/lifecycle.svg)

Most papers are never worth reading, so most are never downloaded. The screen
exists for arXiv's sake: it asks for one request every three seconds, so
downloading thousands of PDFs would take hours, while the model's bill for
reading abstracts is cents.

Failures come in two kinds. A timeout or a 503 is retried after an exponential
backoff with jitter, and never sooner than the server's `Retry-After`. A 404 or
a file that is not a PDF gives up at once. After five failed attempts an item is
*dead* and keeps the reason.

### Surviving a crash

![A lease lets a second worker take over from a stalled one](docs/diagrams/lease.svg)

There is no message queue. Workers coordinate through Postgres: a worker claims
the oldest waiting item with `SELECT … FOR UPDATE SKIP LOCKED` and stamps it
with a *lease*, a random id plus an expiry. It does the slow work with no
transaction open, then records the result with an update that only matches if
its lease is still the current one. A worker that dies or stalls just stops
mattering: its lease runs out, someone else takes the item from its last
recorded stage, and any late write it makes matches nothing.

Every stage is safe to repeat. Model answers are cached under a hash of
everything the model was shown, text is stored once per paper, and verdicts are
overwritten rather than appended.

### How a paper gets its score

![Model answers flow into fit, total, gate and review, which make the verdict](docs/diagrams/scoring.svg)

- **Fit** is the weighted mean of the interest scores.
- **Total** is `0.4 × merit + 0.6 × fit` for a paper read in full, and fit alone
  at the screen, where there is no merit to judge.
- **A dealbreaker is a gate, not a low weight.** If any is likely enough, the
  paper is ineligible however well it scores elsewhere. It keeps its score, so
  you can still see what was rejected and how close it came.
- **Needs review** flags answers the model was unsure of, gates that landed near
  their threshold, and documents that look broken or contain text aimed at an
  automated reader.

The numbers above come from this deployment's
[`backend/wishlist.toml`](backend/wishlist.toml), which is checked in so anyone
can see exactly what the model is asked.

## How it is built

![The deployed system](docs/diagrams/system.svg)

The repository has three parts that share no code: the Python service in
`backend/`, the React app in `frontend/`, and the AWS stack in `infra/`. The
only thing between the app and the service is HTTP, described by
[`openapi.json`](openapi.json), from which the TypeScript client is generated.

In production, CloudFront sends `/api/*` to the service and everything else to
the built app in S3, so the browser only ever talks to one origin, exactly as it
does against the dev server. One Fargate service runs both the API and the
workers. Access is one shared passphrase; there are no accounts.

![Backend packages by topic](docs/diagrams/packages.svg)

Inside the backend, code is grouped by topic: `arxiv/`, `judging/`, `auth/`,
`storage/`, with `pipeline/` joining them and the API and CLI on top. Within a
topic, the logic is pure wherever it can be — the questions, the scoring, the
retry policy, the session signing — and import-linter checks that those modules
reach no third-party library, not even indirectly, so their tests need no
database and no network. It also checks that each heavy dependency stays where
it belongs: SQLAlchemy out of judging and arXiv, FastAPI in the API, the model
SDK in its one adapter.

## Running it locally

You need Docker, Python 3.13, Node with pnpm, and preferably pyenv.

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

By default the model is a deterministic fake, so the whole thing runs with no
API key and costs nothing. It doesn't download PDFs either, since its answers
ignore the text. Set `SIFT_ASKER=typesafe` and `TYPESAFE_API_KEY` to judge with
Jev.

## Checks

```sh
cd backend                       # needs the database running
pytest && mypy && ruff check . && ruff format --check .
lint-imports
python scripts/export_openapi.py --check

cd ../frontend
pnpm run typecheck && pnpm run build
```

## Further reading

- [`AGENTS.md`](AGENTS.md): conventions, and the reasoning behind each design
  decision, for anyone changing the code.
- [`infra/README.md`](infra/README.md): deploying, wiring up CI, a custom
  domain, and tearing it all down.
- [`docs/diagrams/`](docs/diagrams): the diagrams above, as SVG source edited directly rather than exported from a drawing tool
  that follows the viewer's light or dark theme.
