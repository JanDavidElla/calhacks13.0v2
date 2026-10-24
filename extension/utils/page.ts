// What the side panel and the content script on Amazon pages send each other

export const GET_PRODUCT = 'getProduct';

// Answered once the sync has finished
export const SYNC_CART = 'syncCart';

// Sent by the content script as soon as a product page can be read
export const PRODUCT_FOUND = 'productFound';
export type ProductFoundMessage = { type: typeof PRODUCT_FOUND; product: Product };

// The contract's Product (docs/api-contract.md)
export type Product = {
  asin: string;
  title: string;
  price: number;
  url: string;
  image: string | null;
  stars: number | null;
  details: string | null;
};
