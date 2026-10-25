// Which checklist part a product is, guessed from its title
import type { PlannedPart } from '@/utils/api';

// Words in titles and search terms that say nothing about the kind of product
const FILLER = new Set(['and', 'for', 'with', 'the', 'new', 'pack', 'set', 'black', 'white']);

// So a plural matches its singular: "Desk Lamps" shares "lamp" with "Desk lamp"
function singular(word: string): string {
  if (word.endsWith('ies')) return `${word.slice(0, -3)}y`;
  if (/(x|ch|sh)es$/.test(word)) return word.slice(0, -2);
  // Not "glass" or "bus"
  if (/[^su]s$/.test(word)) return word.slice(0, -1);
  return word;
}

function words(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9]{3,}/g) ?? [])
    .filter((word) => !FILLER.has(word))
    .map(singular);
}

// The part whose name and search terms share the most words with the title, or null if no part
// shares at least minShared. A tie goes to the part whose whole name is in the title, the longer
// name if both are: "Office Desk Chair" ties Desk and Office chair, but Office chair says more
export function matchCategory(title: string, parts: PlannedPart[], minShared = 1): string | null {
  const titleWords = new Set(words(title));
  // A Set, because the part's name usually repeats in its search terms ("Case", "PC case")
  const shared = (text: string) => [...new Set(words(text))].filter((word) => titleWords.has(word)).length;
  let best: string | null = null;
  let [bestShared, bestName] = [0, 0];
  for (const part of parts) {
    const allShared = shared(`${part.category} ${part.search_query}`);
    if (allShared < minShared) continue;
    // Not partly: "Low-Power SSD" shares "power" with Power supply, but it's storage
    const nameLength = new Set(words(part.category)).size;
    const name = shared(part.category) === nameLength ? nameLength : 0;
    if (allShared > bestShared || (allShared === bestShared && name > bestName)) {
      [best, bestShared, bestName] = [part.category, allShared, name];
    }
  }
  return best;
}

// For a product the user chose: always a part, so the first one when nothing matches
export function guessCategory(title: string, parts: PlannedPart[]): string {
  return matchCategory(title, parts) ?? parts[0]?.category ?? '';
}
