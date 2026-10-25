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

type Candidate = {
  category: string;
  // Words its name and search terms share with the title
  shared: number;
  // Words in its name when the whole name is in the title, otherwise 0
  name: number;
};

// The parts sharing at least minShared words with the title, best first. A tie goes to the part
// whose whole name is in the title, the longer name if both are: "Office Desk Chair" ties Desk
// and Office chair, but Office chair says more. Any tie left goes to the part listed first.
function rankParts(title: string, parts: PlannedPart[], minShared: number): Candidate[] {
  const titleWords = new Set(words(title));
  // A Set, because the part's name usually repeats in its search terms ("Case", "PC case")
  const shared = (text: string) => [...new Set(words(text))].filter((word) => titleWords.has(word)).length;
  const candidates = parts.map((part) => {
    // Not partly: "Low-Power SSD" shares "power" with Power supply, but it's storage
    const nameLength = new Set(words(part.category)).size;
    const name = shared(part.category) === nameLength ? nameLength : 0;
    return { category: part.category, shared: shared(`${part.category} ${part.search_query}`), name };
  });
  return candidates
    .filter((candidate) => candidate.shared >= minShared)
    .sort((a, b) => b.shared - a.shared || b.name - a.name);
}

// The part whose name and search terms share the most words with the title, or null if no part
// shares at least minShared
export function matchCategory(title: string, parts: PlannedPart[], minShared = 1): string | null {
  return rankParts(title, parts, minShared)[0]?.category ?? null;
}

// How many more words the best part must share with the title than the next part. Sales words
// make one too few: "Ergonomic Wrist Rest for Office Desk" shares two with Office chair's search
// terms ("ergonomic office chair") and one with each desk part, and it's none of them
const SURE_MARGIN = 2;

// The best part only when it clearly wins, or null when it's close enough that the title alone
// can't settle it, or nothing matches
export function sureCategory(title: string, parts: PlannedPart[]): string | null {
  const [best, next] = rankParts(title, parts, 1);
  if (!best || best.shared - (next?.shared ?? 0) < SURE_MARGIN) return null;
  return best.category;
}
