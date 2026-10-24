import { useEffect, useState } from 'react';
import { findAlternatives, type Alternative, type PlannedPart, type SetupEntry } from '@/utils/api';
import type { Product } from '@/utils/page';
import { otherParts } from './useEvaluation';

export type AlternativesState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'done'; alternatives: Alternative[] }
  | { status: 'error'; message: string };

// Searches for better options once the score is in. Nothing beats 100, so a perfect score
// skips the search (an Apify run plus a Claude call, about 30 seconds)
export function useAlternatives(
  product: Product,
  request: string,
  part: PlannedPart | undefined,
  setup: SetupEntry[],
  score: number | null,
): AlternativesState {
  const [state, setState] = useState<AlternativesState>({ status: 'idle' });
  const others = otherParts(setup, part?.category, product.asin);
  const othersKey = others.map((entry) => entry.product.asin).join();

  useEffect(() => {
    if (!part || score === null || score >= 100) {
      setState({ status: 'idle' });
      return;
    }
    // Ignore an answer that arrives after the user moved on
    let current = true;
    setState({ status: 'loading' });
    findAlternatives({
      request,
      category: part.category,
      search_query: part.search_query,
      max_price: part.max_price,
      setup: others,
      product,
    })
      // The server re-judges this product, so its bar can differ from the score on screen
      .then((found) => found.filter((alternative) => alternative.score > score))
      .then((alternatives) => current && setState({ status: 'done', alternatives }))
      .catch((error: Error) => current && setState({ status: 'error', message: error.message }));
    return () => {
      current = false;
    };
    // Keys instead of objects, as in useEvaluation
  }, [
    product.asin,
    product.title,
    product.price,
    request,
    part?.category,
    part?.search_query,
    part?.max_price,
    othersKey,
    score,
  ]);

  return state;
}
