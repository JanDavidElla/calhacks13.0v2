import { useEffect, useRef, useState } from 'react';
import { evaluate, type Plan } from '@/utils/api';
import { saveScore, scoresItem, type ShortlistEntry } from '@/utils/storage';
import { otherParts } from './useEvaluation';
import { useStoredItem } from './useStoredItem';

export type ShortlistScores = {
  scores: Record<string, number>;
  // ASINs being scored right now
  scoring: Set<string>;
};

// Scores shortlist items that were never scored, like cart items whose page wasn't opened with
// the panel. Scores are saved, so each product is scored once.
export function useShortlistScores(plan: Plan | null | undefined, setup: ShortlistEntry[]): ShortlistScores {
  const stored = useStoredItem(scoresItem);
  const scores = stored ?? {};
  // Waits for the stored scores, so items that already have one aren't scored again
  const loaded = stored !== undefined;
  const [scoring, setScoring] = useState<Set<string>>(new Set());
  // Tried this session, so a failing product isn't sent again on every render
  const tried = useRef(new Set<string>());
  const missing = setup.filter(
    (entry) => !(entry.product.asin in scores) && !tried.current.has(entry.product.asin),
  );
  const missingKey = missing.map((entry) => entry.product.asin).join();

  useEffect(() => {
    if (!plan || !loaded) return;
    for (const entry of missing) {
      const { asin } = entry.product;
      const part = plan.parts.find((candidate) => candidate.category === entry.category);
      if (!part) continue;
      tried.current.add(asin);
      setScoring((current) => new Set(current).add(asin));
      evaluate({
        request: plan.transcript,
        category: part.category,
        max_price: part.max_price,
        product: entry.product,
        setup: otherParts(setup, part.category, asin),
      })
        .then((evaluation) => saveScore(asin, evaluation.score))
        .catch(() => {
          // The list shows the price instead
        })
        .finally(() =>
          setScoring((current) => {
            const next = new Set(current);
            next.delete(asin);
            return next;
          }),
        );
    }
    // Keyed by the missing ASINs, so new objects for the same items don't score them again
  }, [plan?.transcript, loaded, missingKey]);

  return { scores, scoring };
}
