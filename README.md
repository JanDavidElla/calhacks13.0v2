# calhacks13.0v2

A voice or text shopping assistant. Ask for something like "a PC setup for $600" or
"Christmas stuff for my apartment, $200", and the server plans a shopping list with Grok,
searches Amazon through Apify, and returns one product per item with links, images, and
an explanation of why the products work together.

## Structure

- `client/` — React + Vite + TypeScript
- `server/` — FastAPI, managed with [uv](https://docs.astral.sh/uv/)

## Setup

Server dependencies and API keys:

```sh
cd server
uv sync
cp .env.example .env
```

Fill in `server/.env` with your own keys (never commit this file):

- `XAI_API_KEY` from [console.x.ai](https://console.x.ai) → API Keys
- `APIFY_API_TOKEN` from [console.apify.com](https://console.apify.com) → Settings → API & Integrations

Client dependencies:

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

Run the client (http://localhost:5173):

```sh
cd client
npm run dev
```

The Vite dev server proxies `/api/*` to the FastAPI server, so call `fetch('/api/...')` from the client.

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
| 502 | xAI or Apify failed (`detail` explains) |

The `Server-Timing` response header shows how long each stage took (`stt`, `plan`, `search`, `pick`).

### `POST /api/compatibility`

JSON `{"parts": [...]}` with at least two parts (the `parts` from a build response can be sent
as-is, e.g. after swapping one). Returns whether they work together and why. Takes about 6s.

## Testing

Automated tests use fake APIs, so they're free and take under a second:

```sh
cd server
uv run pytest
```

The live evaluation sends real text and voice requests to a running server and reports
format, quality, latency, error rate, and throughput. It spends real credit (about $1 of
Apify for the full set), so it asks before running:

```sh
cd server
uv run server                                   # in one terminal
uv run python -m evals.run_eval                 # in another
uv run python -m evals.run_eval --only reject   # free subset: rejections only
```

Other tools in `server/evals/`:

- `make_audio.py` regenerates the voice test files (macOS only)
- `compare_models.py` compares Grok models on saved Amazon results (xAI credit only)
- `compare_captcha.py` A/B tests Apify's CAPTCHA solver

## Costs

Each build uses about $0.18–0.20 of Apify credit and under $0.01 of xAI. The Apify free plan
includes $5 per month. Off-topic and over-budget requests are rejected before any Apify search.
