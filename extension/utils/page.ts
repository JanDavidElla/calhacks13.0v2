// What the side panel and the content script on Amazon pages send each other

export const GET_PRODUCT = 'getProduct';

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
