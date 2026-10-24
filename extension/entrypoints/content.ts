import { GET_PRODUCT, type Product } from '@/utils/page';

// The server accepts at most this much of the page's bullets and spec table
const MAX_DETAILS = 4000;

export default defineContentScript({
  // Every Amazon page, so the side panel can tell "not a product page" from "reload the page"
  matches: ['*://*.amazon.com/*'],
  main() {
    browser.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message === GET_PRODUCT) sendResponse(readProduct());
    });
  },
});

function readProduct(): Product | null {
  const asin = location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/)?.[1];
  const title = textOf('#productTitle');
  const price = readPrice();
  // Without a price the product can't be scored, e.g. "Currently unavailable"
  if (!asin || !title || price === null) return null;

  return {
    asin,
    title,
    price,
    url: `https://www.amazon.com/dp/${asin}`,
    image: document.querySelector<HTMLImageElement>('#landingImage')?.src ?? null,
    stars: readStars(),
    details: readDetails(),
  };
}

function textOf(selector: string): string | null {
  const text = document.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  return text || null;
}

function readPrice(): number | null {
  // Amazon uses either price block depending on the page layout
  const text = textOf(
    '#corePrice_feature_div .a-price .a-offscreen, #corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
  );
  const price = Number.parseFloat(text?.replace(/[^0-9.]/g, '') ?? '');
  return Number.isNaN(price) ? null : price;
}

function readStars(): number | null {
  // The title reads "4.7 out of 5 stars"
  const title = document.querySelector('#acrPopover')?.getAttribute('title');
  const stars = Number.parseFloat(title ?? '');
  return Number.isNaN(stars) ? null : stars;
}

function readDetails(): string | null {
  const parts = [
    textOf('#feature-bullets'),
    textOf('#productDetails_techSpec_section_1') ?? textOf('#prodDetails'),
  ].filter((part) => part !== null);
  return parts.length > 0 ? parts.join('\n').slice(0, MAX_DETAILS) : null;
}
