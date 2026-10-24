# extension

The Chrome extension, built with [WXT](https://wxt.dev) + React + TypeScript. It opens in
Chrome's side panel next to Amazon. The API it calls is described in
[docs/api-contract.md](../docs/api-contract.md).

## Run it

```sh
cd extension
npm install
npm run dev
```

`npm run dev` opens a separate Chrome window with the extension already loaded, and reloads
it when you save a file. That window uses a fresh profile, so you're signed out of Amazon
there, which is fine for browsing products.

To use your normal Chrome instead, run `npm run build`, open `chrome://extensions`, turn on
Developer mode, click **Load unpacked**, and pick `extension/.output/chrome-mv3`. After each
rebuild, click the reload icon on the extension's card.

Click the extension's toolbar icon to open the side panel. On an Amazon product page, it
shows the product's title.

## Where things are

- `entrypoints/sidepanel/`: the side panel UI (React)
- `entrypoints/content.ts`: runs on Amazon pages and reads the product when the panel asks
- `entrypoints/background.ts`: opens the side panel when the toolbar icon is clicked
- `utils/page.ts`: what the side panel and the content script send each other
- `wxt.config.ts`: the extension's name, permissions, and other `manifest.json` settings

Type check with `npm run compile`.
