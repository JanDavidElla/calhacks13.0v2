// Reads Amazon pages: the open tab, or a page fetched in the background (docs/api-contract.md
// lists the selectors). Amazon changes its pages, so these may need updating.
import type { Product } from '@/utils/page';

// The server accepts at most this much of the page's bullets and spec table
const MAX_DETAILS = 4000;

export const PRODUCT_PATH = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})/;

// Only the cart, not "Saved for later" below it
const ACTIVE_CART = '#sc-active-cart, [data-name="Active Items"]';

export function readProduct(page: Document, path: string): Product | null {
  const asin = path.match(PRODUCT_PATH)?.[1];
  const title = textOf(page, '#productTitle');
  const price = readPrice(page);
  // Without a price the product can't be scored, e.g. "Currently unavailable"
  if (!asin || !title || price === null) return null;

  return {
    asin,
    title,
    price,
    url: `https://www.amazon.com/dp/${asin}`,
    image: page.querySelector<HTMLImageElement>('#landingImage')?.src ?? null,
    stars: readStars(page),
    details: readDetails(page),
  };
}

// null when the cart can't be read, so a changed page layout never empties the shortlist
export function readCartAsins(page: Document): Set<string> | null {
  const cart = page.querySelector(ACTIVE_CART);
  if (!cart) {
    return /your amazon cart is empty/i.test(page.body.textContent ?? '') ? new Set() : null;
  }
  const asins = [...cart.querySelectorAll('[data-asin]')].map((item) => item.getAttribute('data-asin'));
  return new Set(asins.filter((asin): asin is string => Boolean(asin)));
}

function textOf(page: Document, selector: string): string | null {
  const text = page.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  return text || null;
}

function readPrice(page: Document): number | null {
  // Amazon uses either price block depending on the page layout
  const text = textOf(
    page,
    '#corePrice_feature_div .a-price .a-offscreen, #corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
  );
  const price = Number.parseFloat(text?.replace(/[^0-9.]/g, '') ?? '');
  return Number.isNaN(price) ? null : price;
}

function readStars(page: Document): number | null {
  // The title reads "4.7 out of 5 stars"
  const title = page.querySelector('#acrPopover')?.getAttribute('title');
  const stars = Number.parseFloat(title ?? '');
  return Number.isNaN(stars) ? null : stars;
}

function readDetails(page: Document): string | null {
  const parts = [
    textOf(page, '#feature-bullets'),
    textOf(page, '#productDetails_techSpec_section_1') ?? textOf(page, '#prodDetails'),
  ].filter((part) => part !== null);
  return parts.length > 0 ? parts.join('\n').slice(0, MAX_DETAILS) : null;
}
