import { useEffect, useState } from 'react';
import { findOtherStores, type Offer } from '@/utils/api';
import type { Product } from '@/utils/page';

export type OtherStoresState =
  | { status: 'loading' }
  | { status: 'done'; offers: Offer[] }
  | { status: 'failed' };

// Looks for the product at other stores as soon as its page opens. It doesn't wait for the
// score, so the price usually shows up before Better options
export function useOtherStores(product: Product): OtherStoresState {
  const [state, setState] = useState<OtherStoresState>({ status: 'loading' });

  useEffect(() => {
    // Ignore an answer that arrives after the user moved on
    let current = true;
    setState({ status: 'loading' });
    findOtherStores(product)
      .then((offers) => current && setState({ status: 'done', offers }))
      // The Google search behind it often fails, and the server's message isn't useful to a
      // shopper, so a failure only says the stores didn't answer
      .catch(() => current && setState({ status: 'failed' }));
    return () => {
      current = false;
    };
    // Keys instead of objects, as in useEvaluation
  }, [product.asin, product.title]);

  return state;
}
