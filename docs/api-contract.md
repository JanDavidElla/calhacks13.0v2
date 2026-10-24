# API contract: the Evaluate flow

This is the agreement between the frontend (Chrome extension and website) and the server.
The frontend can be built now against the example responses below. When an endpoint is
marked ready, swap the mock for a real `fetch`. If either side needs a change, update this
file first so both sides stay in sync.

| Endpoint | Status |
|---|---|
| `POST /api/plan` | Not built yet: use the example as mock data |
| `POST /api/evaluate` | Not built yet: use the example as mock data |
| `POST /api/alternatives` | Not built yet: use the example as mock data |

The request and response shapes are already defined in `server/src/server/models.py`.

## The flow

1. **Plan.** The user types what they want ("a gaming PC for $600"). `/api/plan` returns a
   checklist of parts, each with a budget and an Amazon search link.
2. **Shop.** The user opens a part's search link and lands on a product page.
3. **Evaluate.** The user clicks Evaluate. The extension reads the page and calls
   `/api/evaluate`, which returns a 0–100 score and the checks behind it.
4. **Improve.** At the same time, the frontend calls `/api/alternatives` to get up to 3
   options that score higher, with the price difference. A conflict can also be fixed by
   changing the *other* part (see "Fixing the other part" below).
5. **Add.** The user adds a product to their setup. Every later Evaluate checks against it.

**The frontend keeps the user's state.** The server stores nothing between requests. Keep the
plan and the setup (the products the user added) in `chrome.storage.local` (extension) or page
state (website), and send the setup with every request.

**The website version** works without the extension: show the checklist, and for each part
call `/api/alternatives` without a `product` to list the best-scoring options to add.

## Shared shapes

**Product**

```json
{
  "asin": "B0CPU00001",
  "title": "Intel Core i5-13600K Desktop Processor 14 cores LGA 1700",
  "price": 219.99,
  "url": "https://www.amazon.com/dp/B0CPU00001",
  "image": "https://m.media-amazon.com/images/I/example.jpg",
  "stars": 4.7,
  "details": "Socket LGA 1700. 14 cores (6P+8E). Works with Intel 600 and 700 series motherboards."
}
```

`image`, `stars`, and `details` can be `null`. `details` is the page's bullet points and spec
table as plain text, at most 4,000 characters. Search results never include it.

**Setup entry**: one product the user added, and which checklist part it fills.

```json
{"category": "Motherboard", "product": { ...Product... }}
```

**Check**: one reason behind a score.

```json
{
  "kind": "compatibility",
  "status": "fail",
  "parts": ["CPU", "Motherboard"],
  "reason": "The i5-13600K uses the LGA 1700 socket, but this is an AMD AM5 board.",
  "points": -40
}
```

- `kind`: `compatibility`, `budget`, or `reviews`
- `status`: `pass`, `warn`, or `fail` (suggested colors: green, amber, red)
- `parts`: the checklist categories the check covers
- `points`: 0 or negative, what this check took off the score

## Score rules

The score starts at 100 and adds every check's `points`, with a floor of 0. The server
calculates it in code, so the same checks always give the same score. The point values may
be tuned, but the shapes won't change.

| Check | pass | warn | fail |
|---|---|---|---|
| compatibility, one per pair of parts that depend on each other | works together: 0 | the listings don't confirm a detail: −10 | definite conflict: −40 |
| budget, only when `max_price` is sent | at or under budget: 0 | up to 25% over: −10 | more than 25% over: −20 |
| reviews | 4.0 stars or more: 0 | 3.5 to 3.9, or no rating: −5 | under 3.5: −15 |

When the setup is empty, or nothing in it depends on the product (decor, gifts), there are no
compatibility checks. Show something like "Nothing to check against yet" in that case.

## `POST /api/plan`

Turns a request into the checklist. Same input as `/api/build`: a multipart form with exactly
one of `text` or `audio`.

```sh
curl -F "text=a gaming PC for \$600" http://127.0.0.1:8000/api/plan
```

For voice, send the recording as `audio` instead of `text`. In the extension, record with
`MediaRecorder` and send what it produces (Chrome records WebM): the server will accept it,
so don't convert it. The `transcript` in the response is what the server heard, so show it
to the user. If voice isn't set up on the server, the response is a 503.

Response:

```json
{
  "transcript": "a gaming PC for $600",
  "budget": 600,
  "parts": [
    {
      "category": "CPU",
      "search_query": "AMD Ryzen 5 7600 processor",
      "max_price": 180,
      "search_url": "https://www.amazon.com/s?k=AMD+Ryzen+5+7600+processor&rh=p_36%3A-27000"
    },
    {
      "category": "Motherboard",
      "search_query": "B650 AM5 micro ATX motherboard",
      "max_price": 120,
      "search_url": "https://www.amazon.com/s?k=B650+AM5+micro+ATX+motherboard&rh=p_36%3A-18000"
    }
  ]
}
```

Expected time: a few seconds (one Claude call, no Amazon search).

## `POST /api/evaluate`

Scores one product against the setup. JSON body:

```json
{
  "category": "CPU",
  "product": {
    "asin": "B0CPU00001",
    "title": "Intel Core i5-13600K Desktop Processor 14 cores LGA 1700",
    "price": 219.99,
    "url": "https://www.amazon.com/dp/B0CPU00001",
    "image": "https://m.media-amazon.com/images/I/example.jpg",
    "stars": 4.7,
    "details": "Socket LGA 1700. 14 cores (6P+8E). Works with Intel 600 and 700 series motherboards."
  },
  "setup": [
    {
      "category": "Motherboard",
      "product": {
        "asin": "B0MOBO0001",
        "title": "MSI MAG B650 TOMAHAWK WiFi AM5 Motherboard DDR5",
        "price": 179.99,
        "url": "https://www.amazon.com/dp/B0MOBO0001",
        "image": null,
        "stars": 4.6,
        "details": null
      }
    }
  ],
  "max_price": 180
}
```

`setup` and `max_price` are optional. Without `max_price`, there's no budget check.

Response:

```json
{
  "score": 50,
  "checks": [
    {
      "kind": "compatibility",
      "status": "fail",
      "parts": ["CPU", "Motherboard"],
      "reason": "The i5-13600K uses the LGA 1700 socket, but the MSI B650 Tomahawk is an AMD AM5 board, so the CPU can't be installed.",
      "points": -40
    },
    {
      "kind": "budget",
      "status": "warn",
      "parts": ["CPU"],
      "reason": "$39.99 over this part's $180 budget.",
      "points": -10
    },
    {
      "kind": "reviews",
      "status": "pass",
      "parts": ["CPU"],
      "reason": "Rated 4.7 out of 5.",
      "points": 0
    }
  ]
}
```

Expected time: about 4–8 seconds (one Claude call). Show a loading state.

## `POST /api/alternatives`

Finds better options for one part: searches Amazon, scores every result against the setup,
and returns up to 3, highest score first. JSON body: the part from the plan, plus the setup,
plus the product to beat.

```json
{
  "category": "CPU",
  "search_query": "AMD Ryzen 5 7600 processor",
  "max_price": 180,
  "setup": [
    {
      "category": "Motherboard",
      "product": {
        "asin": "B0MOBO0001",
        "title": "MSI MAG B650 TOMAHAWK WiFi AM5 Motherboard DDR5",
        "price": 179.99,
        "url": "https://www.amazon.com/dp/B0MOBO0001",
        "image": null,
        "stars": 4.6,
        "details": null
      }
    }
  ],
  "product": {
    "asin": "B0CPU00001",
    "title": "Intel Core i5-13600K Desktop Processor 14 cores LGA 1700",
    "price": 219.99,
    "url": "https://www.amazon.com/dp/B0CPU00001",
    "image": "https://m.media-amazon.com/images/I/example.jpg",
    "stars": 4.7,
    "details": null
  }
}
```

With `product`, only options that score higher than it come back. Without it, the best
options for the part come back (the website flow).

Response:

```json
{
  "alternatives": [
    {
      "product": {
        "asin": "B0CPU00002",
        "title": "AMD Ryzen 5 7600 6-Core AM5 Desktop Processor",
        "price": 169.0,
        "url": "https://www.amazon.com/dp/B0CPU00002",
        "image": "https://m.media-amazon.com/images/I/example2.jpg",
        "stars": 4.8,
        "details": null
      },
      "score": 100,
      "checks": [
        {
          "kind": "compatibility",
          "status": "pass",
          "parts": ["CPU", "Motherboard"],
          "reason": "The Ryzen 5 7600 is an AM5 CPU, so it fits the MSI B650 Tomahawk.",
          "points": 0
        },
        {
          "kind": "budget",
          "status": "pass",
          "parts": ["CPU"],
          "reason": "$11.00 under this part's $180 budget.",
          "points": 0
        },
        {
          "kind": "reviews",
          "status": "pass",
          "parts": ["CPU"],
          "reason": "Rated 4.8 out of 5.",
          "points": 0
        }
      ],
      "price_difference": -50.99
    }
  ]
}
```

`price_difference` is this option's price minus the product to beat (negative means cheaper).
It's `null` when no `product` was sent. An empty list means nothing scored higher: show
something like "This is already the best fit we found."

Expected time: the slowest call, because it runs an Amazon search and then a Claude call.
Expect 20–40 seconds until we measure it. Start it at the same time as `/api/evaluate`, and
show the score first.

### Fixing the other part

When a `compatibility` check fails, its `parts` names both sides, for example
`["CPU", "Motherboard"]`. To offer "keep this CPU, change the motherboard", call
`/api/alternatives` for the Motherboard part from the plan. In `setup`, swap the motherboard
for the CPU being evaluated, and send the current motherboard as `product`.

## Errors

Every error body is `{"detail": "a message you can show the user"}`.

| Status | Meaning |
|---|---|
| 400 | The request isn't shopping, can't fit its budget, or has missing inputs |
| 422 | The JSON doesn't match the shapes above (`detail` says which field) |
| 502 | Claude or the Amazon search failed: offer a retry |
| 503 | Voice was sent, but voice isn't set up on the server: ask the user to type instead |

## Notes for the extension

**Reading the product page.** These Amazon selectors work today, but Amazon changes its pages,
so check them on a live page:

| Field | Where |
|---|---|
| `asin` | the URL, `/dp/<ASIN>` |
| `title` | `#productTitle` |
| `price` | `#corePrice_feature_div .a-price .a-offscreen`, without the `$` |
| `image` | `#landingImage`, its `src` |
| `stars` | `#acrPopover`, its `title` ("4.7 out of 5 stars") |
| `details` | text of `#feature-bullets` plus `#productDetails_techSpec_section_1` or `#prodDetails` |
| `url` | `https://www.amazon.com/dp/<ASIN>`, without tracking parameters |

**Calling the server.** Call `http://127.0.0.1:8000/api/...` from the side panel or the service
worker, not from the content script, because content scripts run as amazon.com and hit CORS.
The permission for this (`host_permissions`) is already set in `extension/wxt.config.ts`.

**Recording voice.** Chrome may not show the microphone permission prompt inside a side
panel, so check this early. The usual workaround is to open a small extension page in a tab
once, ask for the microphone there, and after that the side panel can record.

**The website** calls `fetch('/api/...')`. The Vite dev server forwards those calls to the
server (see the README).
