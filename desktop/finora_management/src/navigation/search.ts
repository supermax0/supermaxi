/**
 * Local navigation search shared by «المزيد» and the Ctrl+K palette (one engine, one data source).
 * Arabic + English, partial words, synonyms; every query word must match somewhere; ranked, stable order.
 */

export interface Searchable {
  id: string;
  label: string;
  description?: string;
  keywords?: readonly string[];
}

const TASHKEEL = /[ً-ٰٟـ]/g; // harakat, superscript alef, tatweel
const ARABIC_DIGITS = /[٠-٩۰-۹]/g;

/** Comparison form: lowercase, no diacritics, unified alef / ya / ta marbuta / hamza seats, ASCII digits. */
export function normalizeSearchText(text: string): string {
  return text
    .toLowerCase()
    .replace(TASHKEEL, "")
    .replace(ARABIC_DIGITS, (d) =>
      String((d.charCodeAt(0) - (d.charCodeAt(0) >= 0x06f0 ? 0x06f0 : 0x0660)) % 10),
    )
    .replace(/[أإآٱ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/ؤ/g, "و")
    .replace(/ئ/g, "ي")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function words(text: string): string[] {
  return text ? text.split(" ") : [];
}

/** Arabic "ال" prefix is optional for matching (المنتجات ≈ منتجات). */
function variants(word: string): string[] {
  return word.length > 3 && word.startsWith("ال") ? [word, word.slice(2)] : [word];
}

function tokenScore(
  token: string,
  fieldWords: string[],
  exact: number,
  prefix: number,
  partial: number,
): number {
  let best = 0;
  for (const raw of fieldWords) {
    for (const word of variants(raw)) {
      if (word === token) best = Math.max(best, exact);
      else if (word.startsWith(token)) best = Math.max(best, prefix);
      else if (token.length >= 2 && word.includes(token)) best = Math.max(best, partial);
    }
  }
  return best;
}

interface Indexed<T> {
  item: T;
  order: number;
  label: string;
  labelWords: string[];
  keywordWords: string[];
  descriptionWords: string[];
}

function index<T extends Searchable>(items: readonly T[]): Indexed<T>[] {
  return items.map((item, order) => {
    const label = normalizeSearchText(item.label);
    return {
      item,
      order,
      label,
      labelWords: words(label),
      keywordWords: (item.keywords ?? []).flatMap((k) => words(normalizeSearchText(k))),
      descriptionWords: words(normalizeSearchText(item.description ?? "")),
    };
  });
}

/** Ranked matches for `query`. An empty query returns no results (callers show their own default view). */
export function searchItems<T extends Searchable>(items: readonly T[], query: string, limit = 50): T[] {
  const needle = normalizeSearchText(query);
  if (!needle) return [];
  const tokens = words(needle);
  const scored: { entry: Indexed<T>; score: number }[] = [];
  for (const entry of index(items)) {
    let total = 0;
    let matchedAll = true;
    for (const token of tokens) {
      const score = Math.max(
        tokenScore(token, entry.labelWords, 100, 70, 40),
        tokenScore(token, entry.keywordWords, 60, 45, 25),
        tokenScore(token, entry.descriptionWords, 15, 10, 5),
      );
      if (score === 0) {
        matchedAll = false;
        break;
      }
      total += score;
    }
    if (!matchedAll) continue;
    if (entry.label === needle) total += 80;
    else if (entry.label.startsWith(needle)) total += 40;
    scored.push({ entry, score: total });
  }
  scored.sort((a, b) => b.score - a.score || a.entry.order - b.entry.order);
  return scored.slice(0, limit).map((s) => s.entry.item);
}
