# API contract: the Evaluate flow

This is the agreement between the frontend (Chrome extension and website) and the server.
The frontend can be built now against the example responses below. When an endpoint is
marked ready, swap the mock for a real `fetch`. If either side needs a change, update this
file first so both sides stay in sync.

| Endpoint | Status |
|---|---|
| `POST /api/plan` | Ready |
| `POST /api/evaluate` | Ready |
| `POST /api/alternatives` | Ready |
| `POST /api/other-stores` | Ready |
| `POST /api/replan` | Ready |

The request and response shapes are already defined in `server/src/server/models.py`.

## The flow

1. **Plan.** The user types what they want ("a gaming PC for $600"). `/api/plan` returns a
   checklist of parts, each with a budget and an Amazon search link. Until there's a plan,
   the extension shows only the request box.
2. **Shop.** The user opens a part's search link and lands on a product page. On a page that
   isn't a product, show something like "Open a product to evaluate it."
3. **Evaluate.** The user clicks Evaluate. The extension reads the page and calls
   `/api/evaluate`, which returns a 0–100 score and the checks behind it. The first product
   is scored too: on whether it matches the request, its price, and its reviews. As soon as
   the page opens, `/api/other-stores` also looks for the same product at other stores.
4. **Improve.** At the same time, the frontend calls `/api/alternatives` to get up to 3
   options that score higher, with the price difference. A conflict can also be fixed by
   changing the *other* part (see "Fixing the other part" below).
5. **Add.** The user adds a product to their setup. Every later Evaluate checks against it, and
   `/api/replan` updates the checklist: it skips parts the setup already takes care of and
   splits what's left of the budget across the rest.

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
  "ratings_count": 3120,
  "details": "Socket LGA 1700. 14 cores (6P+8E). Works with Intel 600 and 700 series motherboards."
}
```

`image`, `stars`, `ratings_count`, and `details` can be `null`. `ratings_count` is how many
customers gave the star rating. `details` is the page's bullet points and spec
table as plain text, at most 4,000 characters. The products in `/api/alternatives` include
it, read from their Amazon listings, so an alternative the user adds carries its specs too.

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

- `kind`: `match`, `compatibility`, `budget`, or `reviews`
- `status`: `pass`, `warn`, or `fail` (suggested colors: green, amber, red)
- `parts`: the checklist categories the check covers
- `points`: 0 or negative, what this check took off the score

## Score rules

The score starts at 100 and adds every check's `points`, with a floor of 0. The server
calculates it in code, so the same checks always give the same score. The point values may
be tuned, but the shapes won't change.

| Check | pass | warn | fail |
|---|---|---|---|
| match, one per product | the right kind of product for the part, and it meets every need the request states: 0 | the listing doesn't confirm a stated need: −10 | the wrong kind of product (e.g. an accessory), or it misses a stated need: −80 |
| compatibility, one per pair of parts that depend on each other | works together: 0 | the listings don't confirm a detail: −10 | definite conflict: −40 |
| budget, only when `max_price` is sent | at or under budget: 0 | up to 25% over: −10 | more than 25% over: −20 |
| reviews | 4.0 stars or more, from at least 50 ratings: 0 | 3.5 to 3.9, 4.0 or more from fewer than 50 ratings, or no rating: −5 | under 3.5: −15 |

A failed match costs the most: changing the other part can fix a conflict, but nothing
makes a lens cap a lens, so the wrong product scores 20 at most.

A good rating needs enough ratings behind it: 5 stars from 3 customers is a warning. When
`ratings_count` is `null`, the stars alone decide.

Checks come back in this order. The match check covers the needs in `request` ("quiet",
"white", "for a small room"), so send the user's request with every call.

When the setup is empty, or nothing in it depends on the product (decor, gifts), there are no
compatibility checks. Show something like "Nothing to check against yet" in that case. The
alternatives are the baseline for the first product: other options for the same part, scored
the same way.

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
  "budget_estimated": false,
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

`budget_estimated` is `true` when the request didn't state a budget, so Claude chose a typical
one. Without a budget, price can't be scored, so there's always one. When it's estimated, show
something like "We assumed about $600. Change it." To change it, call `/api/plan` again with
the budget added to the request ("a gaming PC, budget $1,500").

When the request is too broad to plan ("stuff for my house") or misses something that changes
the plan (a budget for a gaming PC), the response is a 400 whose `detail` is a question for the
user, such as "Which room are you shopping for?" The side panel shows it above an empty answer
box and sends the answer joined to the request ("A gaming PC, $800"). Themes ("Christmas decor
for my apartment, $200") are planned as usual.

Expected time: about 4–6 seconds (one Claude call, no Amazon search).

## `POST /api/evaluate`

Scores one product against the setup. JSON body:

```json
{
  "request": "a gaming PC for $600",
  "category": "CPU",
  "product": {
    "asin": "B0CPU00001",
    "title": "Intel Core i5-13600K Desktop Processor 14 cores LGA 1700",
    "price": 219.99,
    "url": "https://www.amazon.com/dp/B0CPU00001",
    "image": "https://m.media-amazon.com/images/I/example.jpg",
    "stars": 4.7,
    "ratings_count": 3120,
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
        "ratings_count": 1845,
        "details": null
      }
    }
  ],
  "max_price": 180
}
```

`request` is the `transcript` from `/api/plan`. `request`, `setup`, and `max_price` are
optional. Without `request`, the match check only asks whether this is the right kind of
product for the part. Without `max_price`, there's no budget check.

Response:

```json
{
  "score": 50,
  "checks": [
    {
      "kind": "match",
      "status": "pass",
      "parts": ["CPU"],
      "reason": "A 14-core desktop CPU is a strong fit for a gaming PC.",
      "points": 0
    },
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
      "reason": "Rated 4.7 out of 5 by 3,120 customers.",
      "points": 0
    }
  ]
}
```

Expected time: about 3–5 seconds (one Claude call). Show a loading state.

## `POST /api/alternatives`

Finds better options for one part: searches Amazon, scores every result against the setup,
and returns up to 3, highest score first. JSON body: the part from the plan, plus the setup,
plus the product to beat.

```json
{
  "request": "a gaming PC for $600",
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
        "ratings_count": 1845,
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
    "ratings_count": 3120,
    "details": null
  }
}
```

With `product`, only options that score higher than it come back. Without it, the best
options for the part come back (the website flow). A search result whose match check fails
(the wrong kind of product, or one that misses a stated need) never comes back.

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
        "ratings_count": 5210,
        "details": null
      },
      "score": 100,
      "checks": [
        {
          "kind": "match",
          "status": "pass",
          "parts": ["CPU"],
          "reason": "A 6-core desktop CPU is a good value pick for a gaming PC.",
          "points": 0
        },
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
          "reason": "Rated 4.8 out of 5 by 5,210 customers.",
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

**Show only alternatives that beat the score on screen.** This call judges the product to
beat again, in its own Claude call, so its bar can be a few points off the `/api/evaluate`
score the user sees. If the product shows 100 and the bar here was 90, an alternative at 95
would come back as "better". When the evaluate score is in, hide any alternative whose
`score` isn't above it, and treat an empty result as "already the best fit".

Expected time: the slowest call, because it runs an Amazon search and then a Claude call.
Expect about 15–30 seconds: 18 for CPUs in testing (11 for the search, 8 for Claude), and 31
for a case judged against two parts. Start it at the same time as `/api/evaluate`, and show
the score first.

### Fixing the other part

When a `compatibility` check fails, its `parts` names both sides, for example
`["CPU", "Motherboard"]`. To offer "keep this CPU, change the motherboard", call
`/api/alternatives` for the Motherboard part from the plan. In `setup`, swap the motherboard
for the CPU being evaluated, and send the current motherboard as `product`.

## `POST /api/other-stores`

Looks for the product the user is viewing at other stores. Bright Data searches Google
Shopping, then Claude keeps only the listings of the exact same product, not a different
model, a bundle, or a PC that contains it. Only new listings from stores shoppers know count
(Walmart, Target, Best Buy, Newegg and the others in `server/src/server/stores.py`), not
marketplace sellers or unknown sites. JSON body: the product.

```json
{
  "product": {
    "asin": "B0BTTZFQTP",
    "title": "GIGABYTE B550M K AMD AM4 Micro-ATX Motherboard",
    "price": 74.99,
    "url": "https://www.amazon.com/dp/B0BTTZFQTP",
    "image": null,
    "stars": 4.4,
    "ratings_count": 1157,
    "details": null
  }
}
```

Response, cheapest first, at most 3:

```json
{
  "offers": [
    {
      "store": "Newegg",
      "title": "Gigabyte b550m k AMD AM4 microATX Motherboard",
      "price": 74.99,
      "url": "https://www.google.com/search?ibp=oshop&q=Gigabyte+b550m+k"
    }
  ]
}
```

`url` is Google Shopping's page for the listing, which links to the store. An empty list means
no known store has the same product. Show the cheapest offer with its difference from the
Amazon price, e.g. "Also at Newegg · $74.99 · same price".

**Treat it as optional.** Google often shows Bright Data a captcha, so the search fails often
(3 of 7 live calls in testing), even though the server retries once with other words. On an
error, show a short note like "Other stores didn't answer this time." instead of the message.

**Always live.** With `DEMO_CACHE` on, this call still searches every time and is never
saved: Bright Data's prize rules disqualify a demo that shows saved web data.

Expected time: 5–30 seconds for the search plus about 2 for Claude; each search gives up after
30 seconds. Start it when the product page opens, since it doesn't need the score.

The server needs `BRIGHTDATA_API_KEY` in `server/.env` and a Bright Data SERP API zone named
`serp_api1` (or `BRIGHTDATA_SERP_ZONE` set to the zone's name).

## `POST /api/replan`

Updates the checklist for what the user chose. Claude looks at each open part (one nothing in
the setup was bought for) and decides whether a setup item already does its job, like an
iMac's built-in screen for Monitor, or makes it unnecessary, like a graphics card for a Mac.
What's left of the budget is then split across the parts still needed. JSON body: the plan as
`/api/plan` returned it, plus the setup.

```json
{
  "request": "a home office desk setup for $1,500",
  "budget": 1500,
  "parts": [
    {"category": "Desktop computer", "search_query": "desktop computer", "max_price": 750},
    {"category": "Monitor", "search_query": "27 inch monitor", "max_price": 280},
    {"category": "Monitor arm", "search_query": "monitor arm", "max_price": 50},
    {"category": "Desk", "search_query": "standing desk", "max_price": 400}
  ],
  "setup": [
    {
      "category": "Desktop computer",
      "product": {
        "asin": "B0CM5JV268",
        "title": "Apple iMac 24-inch, M3 chip, 8GB RAM, 256GB SSD, Blue",
        "price": 1149,
        "url": "https://www.amazon.com/dp/B0CM5JV268"
      }
    }
  ]
}
```

**Always send the parts as `/api/plan` first returned them**, not an earlier replan's. Budgets
are split from the original shares, so sending updated ones would shrink them twice. Extra
fields, such as each part's `search_url`, are ignored.

Response:

```json
{
  "parts": [
    {
      "category": "Desk",
      "search_query": "standing desk",
      "max_price": 331.0,
      "search_url": "https://www.amazon.com/s?k=standing+desk&rh=p_36%3A-49650"
    }
  ],
  "filled": [
    {"category": "Monitor", "asin": "B0CM5JV268", "reason": "Your iMac has a built-in 24-inch screen."}
  ],
  "not_needed": [
    {"category": "Monitor arm", "asin": "B0CM5JV268", "reason": "The iMac's built-in stand doesn't attach to a monitor arm."}
  ],
  "remaining": 351.0
}
```

- `parts`: still to buy, each with its share of the budget that's left and a search link for it
- `filled`: done by a setup item bought for another part; `asin` is that item
- `not_needed`: the setup's choices made the part unnecessary
- `remaining`: the plan's budget minus the setup's total, negative when over budget

Only the budget the plan gave its parts is split, so a plan that left some of its budget
unspent keeps that slack in `remaining`. Over budget, every part's `max_price` is 0, but its
search link keeps the first budget so it still finds something. A part is only skipped for a
setup item Claude names by ASIN, so a made-up answer keeps the part on the list.

Show what changed above the checklist, with each skipped part's `reason`; the side panel puts
it in a card on the List tab. With an empty setup, nothing changes, so there's no need to call.

To score a product against what a setup item fills, send the item's skipped parts as its
`covers` in `/api/evaluate`'s setup: `{"category": "Desktop computer", "covers": ["Monitor"], "product": ...}`.

Expected time: one Claude call at the same effort as `/api/plan`, and none when the setup is
empty or every part is on it.

## Errors

Every error body is `{"detail": "a message you can show the user"}`.

| Status | Meaning |
|---|---|
| 400 | The request isn't shopping, can't fit its budget, is too broad (`detail` is a question to ask), or has missing inputs |
| 422 | The JSON doesn't match the shapes above (`detail` says which field) |
| 502 | Claude, the Amazon search, or the Google Shopping search failed: offer a retry (for `/api/other-stores`, show its short note) |
| 503 | Voice was sent, but voice isn't set up on the server: ask the user to type instead. For `/api/other-stores`: Bright Data isn't set up, so show its short note |

## Notes for the extension

**Reading the product page.** These Amazon selectors work today, but Amazon changes its pages,
so check them on a live page:

| Field | Where |
|---|---|
| `asin` | the URL, `/dp/<ASIN>` |
| `title` | `#productTitle` |
| `price` | the first price block found, tried in order: `.priceToPay` or an `.a-price` that isn't `.a-text-price` (the crossed-out list price) in `#corePriceDisplay_desktop_feature_div`, `#corePrice_feature_div`, or `#apex_desktop`, then the older `#tp_price_block_total_price_ww`, `#priceblock_dealprice`, `#priceblock_ourprice`, and `#price_inside_buybox`. Use its `.a-offscreen` text, or its `.a-price-whole` and `.a-price-fraction` when that's empty, without the `$` or `,` |
| `image` | `#landingImage`, its `src` |
| `stars` | `#acrPopover`, its `title` ("4.7 out of 5 stars") |
| `ratings_count` | `#acrCustomerReviewText`, its digits ("(11,781)", or "11,781 ratings" on older layouts) |
| `details` | a line per `#feature-bullets li`, then a `Label: value` line per row of the `#productOverview_feature_div` and `#prodDetails` tables; pages without those tables list details in `#detailBullets_feature_div li` |
| `url` | `https://www.amazon.com/dp/<ASIN>`, without tracking parameters |

Read `details` row by row, not as the whole section's text: `#prodDetails` also holds a feedback
form's `<style>`, which fills the 4,000 characters before the later rows, and some cells hold an
inline `<script>`. Skip rows that say nothing about the product, such as ASIN, UPC, Best Sellers
Rank, and Customer Reviews.

**Calling the server.** Call `http://127.0.0.1:8000/api/...` from the side panel or the service
worker, not from the content script, because content scripts run as amazon.com and hit CORS.
The permission for this (`host_permissions`) is already set in `extension/wxt.config.ts`.

**Recording voice.** Chrome may not show the microphone permission prompt inside a side
panel, so check this early. The usual workaround is to open a small extension page in a tab
once, ask for the microphone there, and after that the side panel can record.

**The website** calls `fetch('/api/...')`. The Vite dev server forwards those calls to the
server (see the README).
