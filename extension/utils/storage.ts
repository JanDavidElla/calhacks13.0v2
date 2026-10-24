// The user's state lives here: the server stores nothing between requests
import type { Plan, SetupEntry } from '@/utils/api';
import type { Product } from '@/utils/page';

// fromCart marks entries added by Amazon's Add to Cart, so deleting them from the cart removes
// them here too. The server ignores the extra field.
export type ShortlistEntry = SetupEntry & { fromCart?: boolean };

export const planItem = storage.defineItem<Plan | null>('local:plan', { fallback: null });

export const setupItem = storage.defineItem<ShortlistEntry[]>('local:setup', { fallback: [] });

// The number on Amazon's cart badge, quantities included; null until an Amazon page is opened
export const cartCountItem = storage.defineItem<number | null>('local:cartCount', {
  fallback: null,
});

// What the last cart sync found, so the side panel can show why an item was or wasn't added
export type CartReport = {
  checkedAt: number;
  error: string | null;
  // title is null when the product page couldn't be read; category is null when no part matched
  items: { asin: string; title: string | null; category: string | null }[];
};

export const cartReportItem = storage.defineItem<CartReport | null>('local:cartReport', {
  fallback: null,
});

// One product per part: adding replaces what filled the part before
export async function addToShortlist(
  category: string,
  product: Product,
  { fromCart = false } = {},
): Promise<void> {
  const setup = await setupItem.getValue();
  const others = setup.filter(
    (entry) => entry.category !== category && entry.product.asin !== product.asin,
  );
  await setupItem.setValue([...others, { category, product, fromCart }]);
}

// Drops entries that came from the cart but aren't in it anymore
export async function syncShortlistWithCart(cartAsins: Set<string>): Promise<void> {
  const setup = await setupItem.getValue();
  const kept = setup.filter((entry) => !entry.fromCart || cartAsins.has(entry.product.asin));
  if (kept.length < setup.length) await setupItem.setValue(kept);
}
