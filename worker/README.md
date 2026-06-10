# JobFindr Stealth Scraping Worker

Node.js worker using `puppeteer-extra-plugin-stealth` for anti-bot bypass. Handles Google search discovery and general page scraping (Phase 2 career pages, Workday network capture).

## Setup

```bash
cd worker
npm install --ignore-scripts
node node_modules/puppeteer/install.mjs   # download Chrome (WSL/Linux)
```

Configure proxy credentials in the project root `.env` (see `.env.example`). **A residential proxy is strongly recommended** — Google blocks datacenter IPs without one.

## Run

```bash
npm start
# listens on http://127.0.0.1:3847
```

## Lean loading (save proxy bandwidth)

By default the worker blocks images, CSS, fonts, and media through the proxy. HTML and scripts still load, which is enough for Google search and most portfolio pages.

```env
BLOCK_CSS_IMAGES=true   # default; set false to load full pages
```

Check `requests_blocked` in `/metrics` traffic stats to see how many asset requests were skipped.

## API

### `GET /health`

```json
{ "status": "ok", "proxy_enabled": true }
```

### `GET /metrics`

Lifetime proxy traffic counters for the running worker process:

```json
{
  "proxy_enabled": true,
  "traffic": {
    "requests": 42,
    "bytes_downloaded": 1250000,
    "bytes_uploaded": 8500,
    "search_calls": 10,
    "scrape_calls": 2
  }
}
```

Decodo also tracks billing traffic in its own dashboard — these local counters are estimates based on request/response sizes through the browser.

### `POST /search`

Stealth Google search for ATS URL discovery.

```json
{ "query": "site:boards.greenhouse.io \"Stripe\"", "max_results": 5 }
```

Response:

```json
{
  "query": "...",
  "urls": ["https://boards.greenhouse.io/stripe"],
  "blocked": false,
  "proxy_enabled": true
}
```

### `POST /scrape`

General stealth page scrape with network capture (Workday JSON, Cloudflare pages).

```json
{ "url": "https://company.wd5.myworkdayjobs.com/careers", "capture_network": true }
```

Response:

```json
{
  "url": "...",
  "html": "<!DOCTYPE html>...",
  "network_responses": [
    { "url": "...", "status": 200, "content_type": "application/json", "body": "..." }
  ]
}
```

## Proxy configuration

**Option A** — full URL in root `.env`:

```
PROXY_URL=http://username:password@gate.decodo.com:7000
```

**Option B** — Decodo credentials (port rotation):

```
DECODO_USERNAME=your_user
DECODO_PASSWORD=your_pass
DECODO_HOST=gate.decodo.com
DECODO_START_PORT=10001
DECODO_END_PORT=10010
```

Each browser session picks a random port in the range for IP rotation.

The worker reads from the project root `.env` automatically.
