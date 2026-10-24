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
  const text = page.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  return text || null;
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

function readDetails(page: Document): string | null {
  const parts = [
    textOf(page, '#feature-bullets'),
    textOf(page, '#productDetails_techSpec_section_1') ?? textOf(page, '#prodDetails'),
  ].filter((part) => part !== null);
  return parts.length > 0 ? parts.join('\n').slice(0, MAX_DETAILS) : null;
}
