# Design: from Figma to the extension

The side panel of the Chrome extension started in Figma. We designed it there, generated a
working React prototype with Figma Make, then turned that prototype into the real extension
in [`extension/entrypoints/sidepanel/`](../extension/entrypoints/sidepanel/).

- **Figma Make prototype:** [Build and Update Frontend](https://www.figma.com/make/VhuHPyMfgSua6JD8af8xyC/Build-and-Update-Frontend?t=Ah3rObAIdUIzqdzF-1)
- **Figma Design file:** [Side panel designs](https://www.figma.com/design/0gkGMWul9LlHS94bRzZEGq/Untitled?t=Ah3rObAIdUIzqdzF-1)
- **Working repository:** [github.com/JanDavidElla/calhacks13.0v2](https://github.com/JanDavidElla/calhacks13.0v2)

## What's in this folder

[`figma-make/`](figma-make/) is the code Figma Make produced, exported unchanged
(`src/App.tsx`, its SVG assets, and the `.figma/make/` project files). It's kept here as a
record of the starting point. Nothing in `client/`, `extension/` or `server/` imports it, and
it isn't part of any build. To run it on its own:

```sh
cd design/figma-make
pnpm install
pnpm dev
```

## From prototype to product

The prototype was one static screen with sample data. We kept its layout, colors and fonts,
and made each part work with live Amazon pages and Claude's scores.

| Figma Make prototype | In the extension |
| --- | --- |
| Header with "Khai's CTO" in Press Start 2P | Same header and font, renamed to gomdori with a bear logo |
| Yellow project bar: title, "Not saved", edit and save buttons | Same bar; the title is the shopper's request, and edit reopens the request form |
| Tabs: "This product" and "Shortlist · 6" | "This product" and "List (N in Cart)", hidden while the shopper types a request |
| "CTO" avatar above a speech bubble | The bear avatar, whose face changes with the score, above a scrolling speech bubble |
| Score card with a fixed "68%" in Happy Monkey | Same card and font, showing Claude's score for the product on the open Amazon page |
| Pros, Cons and Missing spec boxes in green, red and amber | Same boxes and colors, filled with Claude's compatibility and requirement checks |
| A placeholder shortlist message | The shortlist itself: each saved product with its score, price and a link to Amazon |
| Footer with fixed totals: setup total, budget remaining, change from current | Same footer, computed from the shortlist and the plan's budget |
| — | New: a request form, better-option suggestions, and the cart status |

The colors carry over directly: the page background `#f6f1e8`, the header `#e8d8be`, the
project bar `#efcb7f`, the footer `#d8b35a`, and the pros, cons and missing-spec boxes
`#cbe7cb`, `#f4ded6` and `#fff4e5` are the same in
[`style.css`](../extension/entrypoints/sidepanel/style.css). The prototype's Tailwind classes
became plain CSS classes, since the extension doesn't use Tailwind.
