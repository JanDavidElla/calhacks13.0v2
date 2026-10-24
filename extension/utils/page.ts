// What the side panel and the content script on Amazon pages send each other

export const GET_PRODUCT = 'getProduct';

// Grows into the contract's Product (docs/api-contract.md) as more fields are read
export type PageProduct = {
  asin: string;
  title: string;
};
