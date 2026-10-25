# calhacks13.0v2

A shopping assistant for Cal Hacks 13.0 that checks whether Amazon products work with the
rest of your setup. Tell it what you want, like "a gaming PC for $600", and it plans a
checklist of parts with a budget for each. As you shop, a Chrome extension scores each
product against the parts you've already picked, shows the reason for every point it takes
off, and suggests better-fitting options with the price difference. It works for anything
where products depend on each other: PCs, cameras and lenses, home theater, desk setups.

## Designed in Figma

The extension's side panel was designed in Figma and prototyped with Figma Make, then built
out into the working extension. [design/README.md](design/README.md) shows what changed from
the prototype to the product.

- [Figma Make prototype](https://www.figma.com/make/VhuHPyMfgSua6JD8af8xyC/Build-and-Update-Frontend?t=Ah3rObAIdUIzqdzF-1)
- [Figma Design file](https://www.figma.com/design/0gkGMWul9LlHS94bRzZEGq/Untitled?t=Ah3rObAIdUIzqdzF-1)

## Status

| Part | State |
|---|---|
| Server: `/api/build`, `/api/compatibility` | Working, on Claude |
| Server: `/api/plan`, `/api/evaluate`, `/api/alternatives` | Working, on Claude. Request and response shapes are in [docs/api-contract.md](docs/api-contract.md) |
| Chrome extension (`extension/`) | Skeleton: the side panel opens and shows the title of the Amazon product you're viewing |
| Website (`client/`) | Not started, still the Vite starter page. It's the demo backup if the extension has trouble |

## Structure

- `server/`: FastAPI with Claude (Anthropic SDK) and Apify, managed with [uv](https://docs.astral.sh/uv/)
- `extension/`: Chrome extension, WXT + React + TypeScript (see [extension/README.md](extension/README.md))
- `client/`: website, React + Vite + TypeScript
- `docs/api-contract.md`: the API the frontend and the server agree on
- `design/`: the Figma Make prototype the extension started from, kept for reference and not built

## Setup

Server dependencies and API keys:

```sh
cd server
uv sync
cp .env.example .env
```

Fill in `server/.env` with your own keys (never commit this file):

- `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com) → API Keys
- `APIFY_API_TOKEN` from [console.apify.com](https://console.apify.com) → Settings → API & Integrations
- `XAI_API_KEY` (optional, only for voice requests) from [console.x.ai](https://console.x.ai) → API Keys.
  Without it, voice requests return 503 and typed requests work as normal.

Extension and website dependencies (each folder installs its own):

```sh
cd extension
npm install
```

```sh
cd client
npm install
```

## Development

Run the server (http://127.0.0.1:8000, auto-reload; API docs at http://127.0.0.1:8000/docs):

```sh
cd server
uv run server
```

Run the extension:

```sh
cd extension
npm run dev
```

This opens a separate Chrome window with the extension loaded. Click the extension's toolbar
icon to open the side panel. To load it into your normal Chrome instead, see
[extension/README.md](extension/README.md).

Run the website (http://localhost:5173):

```sh
cd client
npm run dev
```

The Vite dev server proxies `/api/*` to the FastAPI server, so call `fetch('/api/...')` from the website.

Rehearse the demo with the demo cache. Live answers take up to 30 seconds and can change from
run to run, so add `DEMO_CACHE=true` to `server/.env`, restart the server, and run through the
demo once. Every answer to `/api/plan`, `/api/evaluate`, and `/api/alternatives` is saved in
`server/demo-cache.json`, and the same request replays it in under a second, even after a
restart. Products are matched by ASIN, so a price that changes overnight still replays.
Failures aren't saved, and anything new runs live. A replayed response shows `cache` in its
`Server-Timing` header. Delete the file to record again.

## API

### `POST /api/build`

Multipart form with exactly one of:

- `text`: the request as typed text
- `audio`: a voice recording (WAV, MP3, M4A, AAC, FLAC, OGG, ...)

Returns the transcript, budget, total, a summary, the chosen `parts` (each with an Amazon
`url`, `image`, price, and reason), and a `compatibility` section. A build takes about 40s.

| Status | Meaning |
|---|---|
| 200 | Build returned |
| 400 | Missing/both inputs, empty or unreadable audio, or a request that isn't shopping or can't fit its budget (`detail` explains) |
| 502 | Claude, Apify, or xAI speech to text failed (`detail` explains) |
| 503 | Audio sent, but the server has no `XAI_API_KEY` |

The `Server-Timing` response header shows how long each stage took (`stt`, `plan`, `search`, `pick`).

### `POST /api/compatibility`

JSON `{"parts": [...]}` with at least two parts (the `parts` from a build response can be sent
as-is, e.g. after swapping one). Returns whether they work together and why. Takes about 4s.

### Evaluate

`/api/plan`, `/api/evaluate`, and `/api/alternatives` power the extension: the checklist, the
score for one product, and better options. They're described in
[docs/api-contract.md](docs/api-contract.md), with example requests and responses. Claude
judges each product (does it match the request, does it work with the setup), and
`server/src/server/score.py` turns those verdicts into the 0–100 score in code.

## Testing

Server tests use fake APIs, so they're free and take under a second:

```sh
cd server
uv run pytest
```

Type check the extension, and type check, build, and lint the website:

```sh
cd extension
npm run compile
```

```sh
cd client
npm run build
npm run lint
```

The live evaluation sends real text and voice requests to a running server and reports
format, quality, latency, error rate, and throughput. It spends real credit (about $1 of
Apify for the full set), so it asks before running:

```sh
cd server
uv run server                                   # in one terminal
uv run python -m evals.run_eval                 # in another
uv run python -m evals.run_eval --only reject   # rejections only: no Apify, a few cents of Claude
```

Other tools in `server/evals/`:

- `make_audio.py` regenerates the voice test files (macOS only)
- `compare_models.py` compares Grok models on saved Amazon results. It was written for Grok
  and doesn't work since the switch to Claude
- `compare_captcha.py` A/B tests Apify's CAPTCHA solver

## Working together

- Each person works in their own folder: `server/`, `extension/`, or `client/`.
- Run `git pull` before `git push`.
- If the API needs to change, update [docs/api-contract.md](docs/api-contract.md) first, so
  the frontend and the server stay in sync.

## Costs

Each build uses about $0.18–0.20 of Apify credit. Claude's cost per build hasn't been measured
yet (Claude Opus 5.5 is $4 per million input tokens and $20 per million output tokens). The
Apify free plan includes $5 per month. Off-topic and over-budget requests are rejected before
any Apify search.
