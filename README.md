# calhacks13.0v2

## Structure

- `client/` — React + Vite + TypeScript
- `server/` — FastAPI, managed with [uv](https://docs.astral.sh/uv/)

## Development

Run the server (http://127.0.0.1:8000, auto-reload):

```sh
cd server
uv run server
```

Run the client (http://localhost:5173):

```sh
cd client
npm install
npm run dev
```

The Vite dev server proxies `/api/*` to the FastAPI server, so call `fetch('/api/...')` from the client.
