import { describe, expect, it } from "vitest";

import { el } from "./el";
import { en } from "./en";

/**
 * The two catalogues, checked against each other.
 *
 * TypeScript already forces `el` to hold every English key — that is why it is typed as
 * `Messages` rather than `Partial<Messages>`. What the compiler cannot check is the
 * *content*: a placeholder dropped in translation produces a sentence with a hole in it,
 * and an untranslated value produces a Greek screen with an English sentence in the
 * middle. Both look like bugs to the person reading them and neither is a type error.
 */

const PLACEHOLDER = /\{(\w+)\}/g;

function placeholders(value: string): string[] {
  return [...value.matchAll(PLACEHOLDER)].map((match) => match[1] ?? "").sort();
}

/** Keys whose English and Greek text is legitimately identical. */
const SHARED_BY_DESIGN = new Set([
  // Latin-script words Greek uses unchanged. "Ημέιλ" would be a transliteration nobody
  // writes, and the units are how they appear on Greek packaging and gym equipment.
  "auth.email",
  "notifications.email",
  "settings.imperial",
]);

describe("the Greek catalogue", () => {
  it("covers every English key", () => {
    // Enforced by the type system too; asserted here so the failure names the key
    // instead of pointing at an assignment.
    const missing = Object.keys(en).filter((key) => !(key in el));
    expect(missing).toEqual([]);
  });

  it("has no keys English does not have", () => {
    // A stray key is dead weight that survives every rename of the real one.
    const extra = Object.keys(el).filter((key) => !(key in en));
    expect(extra).toEqual([]);
  });

  it("keeps every placeholder, with the same names", () => {
    // The failure this catches: "{count} ημέρες" translated as "ημέρες" renders a
    // sentence missing its number, and nothing anywhere throws.
    const broken: string[] = [];
    for (const [key, english] of Object.entries(en)) {
      const greek = el[key as keyof typeof el];
      const expected = placeholders(english);
      const actual = placeholders(greek);
      if (expected.join(",") !== actual.join(",")) {
        broken.push(`${key}: expected [${expected.join(", ")}], got [${actual.join(", ")}]`);
      }
    }
    expect(broken).toEqual([]);
  });

  it("is actually translated", () => {
    // An entry copied verbatim from English is an untranslated string, which on a Greek
    // screen reads as a bug rather than as a fallback.
    const untranslated = Object.entries(en)
      .filter(([key, english]) => !SHARED_BY_DESIGN.has(key) && el[key as keyof typeof el] === english)
      .map(([key]) => key);

    expect(untranslated).toEqual([]);
  });

  it("uses Greek characters in its prose", () => {
    // A weaker check than the one above, and it catches a different mistake: a value
    // that was reworded but never actually translated.
    const greekLetters = /[Ͱ-Ͽἀ-῿]/;
    const withoutGreek = Object.entries(el)
      .filter(([key, value]) => {
        if (SHARED_BY_DESIGN.has(key)) return false;
        // Values that are only a placeholder, a number or a unit have no letters to check.
        const prose = value.replace(PLACEHOLDER, "").replace(/[^A-Za-zͰ-Ͽ]/g, "");
        return prose.length > 2 && !greekLetters.test(value);
      })
      .map(([key]) => key);

    expect(withoutGreek).toEqual([]);
  });

  it("does not leave a trailing space where English had none", () => {
    const sloppy = Object.entries(el)
      .filter(([, value]) => value !== value.trim())
      .map(([key]) => key);

    expect(sloppy).toEqual([]);
  });
});

describe("the English catalogue", () => {
  it("has no duplicate values that should share a key", () => {
    // Not an error in itself, but two identical strings under different keys usually
    // means one was pasted rather than reused, and they drift apart later.
    const seen = new Map<string, string[]>();
    for (const [key, value] of Object.entries(en)) {
      seen.set(value, [...(seen.get(value) ?? []), key]);
    }
    const duplicated = [...seen.entries()]
      .filter(([value, keys]) => keys.length > 1 && value.length > 12)
      .map(([value, keys]) => `${keys.join(" / ")}: "${value}"`);

    expect(duplicated).toEqual([]);
  });

  it("uses no exclamation marks", () => {
    // The product's tone, stated in the catalogue's own docstring: a gym app that cheers
    // at you between sets gets deleted.
    const shouty = Object.entries(en)
      .filter(([, value]) => value.includes("!"))
      .map(([key]) => key);

    expect(shouty).toEqual([]);
  });
});
