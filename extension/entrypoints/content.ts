import { GET_PRODUCT, type PageProduct } from '@/utils/page';

export default defineContentScript({
  // Every Amazon page, so the side panel can tell "not a product page" from "reload the page"
  matches: ['*://*.amazon.com/*'],
  main() {
    browser.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message === GET_PRODUCT) sendResponse(readProduct());
    });
  },
});

function readProduct(): PageProduct | null {
  const asin = location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/)?.[1];
  const title = document.querySelector('#productTitle')?.textContent?.trim();
  return asin && title ? { asin, title } : null;
}
