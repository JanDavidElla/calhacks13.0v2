// Reads Amazon pages: the open tab, or a page fetched in the background (docs/api-contract.md
// lists the selectors). Amazon changes its pages, so these may need updating.
import type { Product } from '@/utils/page';

// The server accepts at most this much of the page's bullets and spec table
const MAX_DETAILS = 4000;

// Every product URL form, whatever comes after the ASIN (ref=pd_..., ?th=1):
// /dp/, /gp/product/, mobile /gp/aw/d/, and old /exec/obidos/ASIN/ links
export const PRODUCT_PATH = /\/(?:dp|gp\/product|gp\/aw\/d|exec\/obidos\/ASIN)\/([A-Z0-9]{10})/i;

// Only the cart, not "Saved for later" below it
const ACTIVE_CART = '#sc-active-cart, [data-name="Active Items"]';

export function readProduct(page: Document, path: string): Product | null {
  const asin = path.match(PRODUCT_PATH)?.[1]?.toUpperCase();
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
  return clean(page.querySelector(selector)?.textContent);
}

function clean(text: string | null | undefined): string | null {
  return text?.replace(/\s+/g, ' ').trim() || null;
}

// Where each page layout puts the price, tried in order. priceToPay comes first because it's what
// the buyer pays, not a struck-through list price.
const PRICE_BLOCKS = [
  '#corePriceDisplay_desktop_feature_div .priceToPay',
  '#corePrice_feature_div .a-price',
  '#corePriceDisplay_desktop_feature_div .a-price',
  '#apex_desktop .priceToPay',
  '#apex_desktop .a-price',
  '#tp_price_block_total_price_ww',
  '#priceblock_dealprice',
  '#priceblock_ourprice',
  '#price_inside_buybox',
];

function readPrice(page: Document): number | null {
  for (const selector of PRICE_BLOCKS) {
    const block = page.querySelector(selector);
    if (!block) continue;
    // .a-offscreen holds "$86.94" for screen readers; some layouts fill in only the visible
    // dollars ("86.") and cents ("94")
    const whole = block.querySelector('.a-price-whole')?.textContent ?? '';
    const fraction = block.querySelector('.a-price-fraction')?.textContent ?? '';
    const text =
      block.querySelector('.a-offscreen')?.textContent?.trim() ||
      (whole && `${whole}${fraction}`) ||
      block.textContent;
    const price = parsePrice(text ?? '');
    if (price !== null) return price;
  }
  return null;
}

// The first amount in the text: "$1,219.99" is 1219.99
function parsePrice(text: string): number | null {
  const amount = text.match(/\d[\d,]*(?:\.\d+)?/)?.[0];
  return amount ? Number.parseFloat(amount.replace(/,/g, '')) : null;
}

function readStars(page: Document): number | null {
  // The title reads "4.7 out of 5 stars"
  const title = page.querySelector('#acrPopover')?.getAttribute('title');
  const stars = Number.parseFloat(title ?? '');
  return Number.isNaN(stars) ? null : stars;
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
