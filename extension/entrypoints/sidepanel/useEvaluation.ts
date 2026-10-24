import { useEffect, useState } from 'react';
import { evaluate, type Evaluation, type PlannedPart, type SetupEntry } from '@/utils/api';
import type { Product } from '@/utils/page';

export type EvaluationState =
  | { status: 'loading' }
  | { status: 'done'; evaluation: Evaluation }
  | { status: 'error'; message: string };

// What the product is checked against: everything else, not itself and not what it would replace
export function otherParts(setup: SetupEntry[], category: string | undefined, asin: string): SetupEntry[] {
  return setup.filter((entry) => entry.category !== category && entry.product.asin !== asin);
}

// Scores the product as soon as the page opens, and again when the part or the shortlist changes
export function useEvaluation(
  product: Product,
  request: string,
  part: PlannedPart | undefined,
  setup: SetupEntry[],
): EvaluationState {
  const [state, setState] = useState<EvaluationState>({ status: 'loading' });
  const others = otherParts(setup, part?.category, product.asin);
  const othersKey = others.map((entry) => entry.product.asin).join();

  useEffect(() => {
    if (!part) return;
    // Ignore an answer that arrives after the user moved on
    let current = true;
    setState({ status: 'loading' });
    evaluate({ request, category: part.category, max_price: part.max_price, product, setup: others })
      .then((evaluation) => current && setState({ status: 'done', evaluation }))
      .catch((error: Error) => current && setState({ status: 'error', message: error.message }));
    return () => {
      current = false;
    };
    // Keys instead of objects: re-reading the page or the shortlist makes new objects for the
    // same product, which shouldn't cost another call
  }, [product.asin, product.title, product.price, request, part?.category, part?.max_price, othersKey]);

  return state;
}
