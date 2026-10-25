import { PRODUCT_PATH, readCartAsins, readProduct } from '@/utils/amazon';
import { matchCategory } from '@/utils/category';
import {
  GET_PRODUCT,
  PRODUCT_FOUND,
  SYNC_CART,
  type Product,
  type ProductFoundMessage,
} from '@/utils/page';
import {
  addToShortlist,
  cartCountItem,
  cartReportItem,
  planItem,
  setupItem,
  syncShortlistWithCart,
  type CartReport,
} from '@/utils/storage';

const ADD_TO_CART = '#add-to-cart-button, [name="submit.add-to-cart"]';

// The cart badge in the header of every Amazon page
const CART_COUNT = '#nav-cart-count';

// Time for Amazon to confirm the add, on this page or the confirmation page it opens
const CONFIRM_WINDOW_MS = 30_000;

const CART_URL = '/gp/cart/view.html';

// The cart itself, not the "Added to cart" confirmation page at /cart/smart-wagon
const CART_PAGE = /^\/(gp\/cart\/view\.html|cart\/?)$/;

// How long a product page is watched for late details, like a price that loads after the title
const PRODUCT_WATCH_MS = 10_000;

// Other pages fetch the cart at most this often
const CART_SYNC_INTERVAL_MS = 60_000;

// Kept in storage, not a variable, because the confirmation can arrive on the next page
const pendingCartItem = storage.defineItem<{ product: Product; clickedAt: number } | null>(
  'local:pendingCart',
  { fallback: null },
);

// Cart items' product pages, read once each. Matching runs again on every sync, so a new
// project or better matching applies to them without reading the pages again.
const cartProductsItem = storage.defineItem<Record<string, Product>>('local:cartProducts', {
  fallback: {},
});

export default defineContentScript({
  // Every Amazon page, so the side panel can tell "not a product page" from "reload the page"
  matches: ['*://*.amazon.com/*'],
  // As soon as the HTML is parsed, without waiting for images and ads
  runAt: 'document_end',
  main(ctx) {
    browser.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message === GET_PRODUCT) sendResponse(readProduct(document, location.pathname));
      if (message === SYNC_CART) {
        void syncCart().then(() => sendResponse(true));
        // Keeps the channel open until the sync answers
        return true;
      }
    });
    watchForProduct();
    watchCartCount();
    // Picking another size or color swaps the product without reloading the page
    ctx.addEventListener(window, 'wxt:locationchange', () => watchForProduct());
    // Capture phase, so the click is seen before Amazon's handler can navigate away
    document.addEventListener('click', (event) => void onClick(event), true);
    void watchForCartConfirmation();

    if (CART_PAGE.test(location.pathname)) {
      // Deleting an item updates the cart page in place, so re-read it after every change
      onPageSettled(() => void syncCart(document));
      void syncCart(document);
    } else {
      void syncCartIfStale();
    }
    // A new project pulls in what's already in the cart; one tab is enough to do it
    planItem.watch(() => {
      if (document.visibilityState === 'visible') void syncCart();
    });
  },
});

// Tells the side panel as soon as the product can be read, instead of after the page finishes
// loading. Keeps reading for a while, since details like the price can arrive later.
let productWatch: MutationObserver | undefined;
let lastAnnounced = '';
function watchForProduct() {
  productWatch?.disconnect();
  if (!PRODUCT_PATH.test(location.pathname)) return;
  announceProduct();
  const watch = onPageSettled(announceProduct, 200);
  productWatch = watch;
  setTimeout(() => watch.disconnect(), PRODUCT_WATCH_MS);
}

function announceProduct() {
  const product = readProduct(document, location.pathname);
  if (!product) return;
  const key = `${product.asin} ${product.title} ${product.price}`;
  if (key === lastAnnounced) return;
  lastAnnounced = key;
  const message: ProductFoundMessage = { type: PRODUCT_FOUND, product };
  browser.runtime.sendMessage(message).catch(() => {
    // The side panel is closed; it asks for the product when it opens
  });
}

// Amazon updates the badge in place after Add to Cart, so watch it instead of reading it once
function watchCartCount() {
  const badge = document.querySelector(CART_COUNT);
  if (!badge) return;
  const save = () => {
    // "99+" reads as 99
    const count = Number.parseInt(badge.textContent ?? '', 10);
    if (!Number.isNaN(count)) void cartCountItem.setValue(count);
  };
  new MutationObserver(save).observe(badge, { childList: true, characterData: true, subtree: true });
  save();
}

async function onClick(event: MouseEvent) {
  if (!(event.target instanceof Element) || !event.target.closest(ADD_TO_CART)) return;
  const product = readProduct(document, location.pathname);
  if (!product) return;
  await pendingCartItem.setValue({ product, clickedAt: Date.now() });
  void watchForCartConfirmation();
}

// A click alone doesn't mean it was added (e.g. a size wasn't picked), so wait for Amazon to say so
async function watchForCartConfirmation() {
  const pending = await pendingCartItem.getValue();
  const timeLeft = pending ? pending.clickedAt + CONFIRM_WINDOW_MS - Date.now() : 0;
  if (!pending || timeLeft <= 0) return;

  const confirmIfAdded = async () => {
    // innerText skips hidden elements, so a hidden "Added to cart" template doesn't count
    if (!/added to cart/i.test(document.body.innerText)) return;
    observer.disconnect();
    await pendingCartItem.setValue(null);
    const plan = await planItem.getValue();
    // Without a project there's no checklist part to file it under
    if (!plan) return;
    // Only a product that matches a part: a mouse pad would replace the CPU the user chose
    const category = matchCategory(pending.product.title, plan.parts);
    if (!category) return;
    // The user just chose this product, so it replaces whatever filled its part
    await addToShortlist(category, pending.product, { fromCart: true });
  };
  const observer = onPageSettled(() => void confirmIfAdded());
  setTimeout(() => observer.disconnect(), timeLeft);
  await confirmIfAdded();
}

async function syncCartIfStale() {
  const report = await cartReportItem.getValue();
  if (!report || Date.now() - report.checkedAt > CART_SYNC_INTERVAL_MS) await syncCart();
}

// One sync at a time, so two triggers can't add the same item twice
let syncQueue = Promise.resolve();
function syncCart(cartPage?: Document): Promise<void> {
  syncQueue = syncQueue
    .then(() => runCartSync(cartPage))
    .catch((error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      return saveReport({ error: `Couldn't sync your cart: ${message}`, items: [] });
    });
  return syncQueue;
}

// Removes deleted cart items from the shortlist, and fills empty parts with cart items that fit
async function runCartSync(cartPage?: Document) {
  const plan = await planItem.getValue();
  if (!plan) return;
  const asins = readCartAsins(cartPage ?? (await fetchPage(CART_URL)));
  if (!asins) {
    await saveReport({ error: "Couldn't find the items on your Amazon cart page.", items: [] });
    return;
  }
  await syncShortlistWithCart(asins);

  const cached = await cartProductsItem.getValue();
  const products: Record<string, Product> = {};
  const items: CartReport['items'] = [];
  for (const asin of asins) {
    const product = cached[asin] ?? (await readProductPage(asin));
    if (product) products[asin] = product;
    // Two shared words, not one: a phone case shares only "case" with a PC case
    const category = product && matchCategory(product.title, plan.parts, 2);
    items.push({ asin, title: product?.title ?? null, category });
    if (!product || !category) continue;

    const setup = await setupItem.getValue();
    // Never replace a part the user already filled, and don't add the same product twice
    const filled = setup.some((entry) => entry.category === category || entry.product.asin === asin);
    if (!filled) await addToShortlist(category, product, { fromCart: true });
  }
  // Only what's still in the cart, so the cache doesn't grow forever
  await cartProductsItem.setValue(products);
  await saveReport({ error: null, items });
}

function saveReport(report: Omit<CartReport, 'checkedAt'>): Promise<void> {
  return cartReportItem.setValue({ ...report, checkedAt: Date.now() });
}

// The cart page has no specs or ratings, so read the product page for them. null (and not
// cached) when the page has no price, so the next sync tries again.
async function readProductPage(asin: string): Promise<Product | null> {
  const path = `/dp/${asin}`;
  return readProduct(await fetchPage(path), path);
}

// Same origin as the page, so Amazon sends the user's own cart
async function fetchPage(path: string): Promise<Document> {
  const response = await fetch(path, { credentials: 'include' });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return new DOMParser().parseFromString(await response.text(), 'text/html');
}

// Calls back once the page stops changing, instead of reading it on every small change
function onPageSettled(callback: () => void, delayMs = 500): MutationObserver {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const observer = new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(callback, delayMs);
  });
  observer.observe(document.body, { childList: true, subtree: true });
  return observer;
}
