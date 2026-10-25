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
    ratings_count: readRatingsCount(page),
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

function textOf(within: ParentNode, selector: string): string | null {
  return clean(within.querySelector(selector)?.textContent);
}

function clean(text: string | null | undefined): string | null {
  return text?.replace(/\s+/g, ' ').trim() || null;
}

// The price to pay, in either block depending on the page layout. .a-text-price is the
// crossed-out list price next to it
const PRICE_TO_PAY =
  '#corePrice_feature_div .a-price:not(.a-text-price), #corePriceDisplay_desktop_feature_div .a-price:not(.a-text-price)';

function readPrice(page: Document): number | null {
  for (const element of page.querySelectorAll(PRICE_TO_PAY)) {
    // Many pages leave the screen reader copy empty and only show the price on screen
    const text = textOf(element, '.a-offscreen') ?? textOf(element, '[aria-hidden="true"]');
    const price = Number.parseFloat(text?.replace(/[^0-9.]/g, '') ?? '');
    if (!Number.isNaN(price)) return price;
  }
  return null;
}

function readStars(page: Document): number | null {
  // The title reads "4.7 out of 5 stars"
  const title = page.querySelector('#acrPopover')?.getAttribute('title');
  const stars = Number.parseFloat(title ?? '');
  return Number.isNaN(stars) ? null : stars;
}

function readRatingsCount(page: Document): number | null {
  // "(11,781)" next to the stars, or "11,781 ratings" on older layouts
  const digits = textOf(page, '#acrCustomerReviewText')?.replace(/\D/g, '');
  return digits ? Number.parseInt(digits, 10) : null;
}

// Rows that say nothing about the product itself
const SKIPPED_ROWS = new Set([
  'ASIN',
  'Best Sellers Rank',
  'Customer Reviews',
  'Global Trade Identification Number',
  'UPC',
]);

function readDetails(page: Document): string | null {
  const lines = [
    ...listItems(page, '#feature-bullets li'),
    ...tableRows(page, '#productOverview_feature_div tr, #prodDetails tr'),
    // Pages without a spec table list their details as bullets instead
    ...listItems(page, '#detailBullets_feature_div li'),
  ];
  // The overview repeats rows from the spec table
  const unique = [...new Set(lines)];
  return unique.length > 0 ? unique.join('\n').slice(0, MAX_DETAILS) : null;
}

function listItems(page: Document, selector: string): string[] {
  return [...page.querySelectorAll(selector)]
    .map(readableText)
    .filter((text) => text !== null);
}

// "Label: value" per row. Read row by row because the section's text also holds a
// feedback form's <style>, which would fill MAX_DETAILS before the later rows
function tableRows(page: Document, selector: string): string[] {
  const rows: string[] = [];
  for (const row of page.querySelectorAll(selector)) {
    const cells = [...row.querySelectorAll('th, td')].map(readableText);
    const [label, value] = cells;
    if (cells.length === 2 && label && value && !SKIPPED_ROWS.has(label)) {
      rows.push(`${label}: ${value}`);
    }
  }
  return rows;
}

// The element's text without the inline <script> and <style> some cells hold
function readableText(element: Element): string | null {
  const copy = element.cloneNode(true) as Element;
  for (const code of copy.querySelectorAll('script, style')) code.remove();
  return clean(copy.textContent);
}
