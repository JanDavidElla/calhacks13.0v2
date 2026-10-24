// Which checklist part a product is, guessed from its title
import type { PlannedPart } from '@/utils/api';

// Words in titles and search terms that say nothing about the kind of product
const FILLER = new Set(['and', 'for', 'with', 'the', 'new', 'pack', 'set', 'black', 'white']);

function words(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9]{3,}/g) ?? []).filter((word) => !FILLER.has(word));
}

// The part whose name and search terms share the most words with the title, or null if no part
// shares at least minShared
export function matchCategory(title: string, parts: PlannedPart[], minShared = 1): string | null {
  const titleWords = new Set(words(title));
  let best: string | null = null;
  let bestScore = minShared - 1;
  for (const part of parts) {
    // A Set, because the part's name usually repeats in its search terms ("Case", "PC case")
    const partWords = new Set(words(`${part.category} ${part.search_query}`));
    const score = [...partWords].filter((word) => titleWords.has(word)).length;
    if (score > bestScore) [best, bestScore] = [part.category, score];
  }
  return best;
}

// For a product the user chose: always a part, so the first one when nothing matches
export function guessCategory(title: string, parts: PlannedPart[]): string {
  return matchCategory(title, parts) ?? parts[0]?.category ?? '';
}
