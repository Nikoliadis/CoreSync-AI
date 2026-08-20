import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils/cn";

/**
 * Regression tests for a bug that shipped: tailwind-merge did not know the project's
 * type scale, so it treated `text-accent-ink` (a colour) and `text-body` (a size) as
 * one `text-*` group and dropped the colour. Every primary button rendered
 * white-on-lime at 1.17:1 until the accessibility gate caught it.
 */
describe("cn", () => {
  it("keeps a semantic colour alongside a font size", () => {
    const result = cn("bg-accent text-accent-ink", "text-body");
    expect(result).toContain("text-accent-ink");
    expect(result).toContain("text-body");
  });

  it("keeps the light-mode-safe accent colour alongside a size", () => {
    const result = cn("text-accent-text", "text-caption");
    expect(result).toContain("text-accent-text");
    expect(result).toContain("text-caption");
  });

  it("still collapses two genuine font sizes", () => {
    expect(cn("text-body", "text-h1")).toBe("text-h1");
  });

  it("still collapses two genuine text colours", () => {
    expect(cn("text-text-muted", "text-critical")).toBe("text-critical");
  });

  it("lets the caller win on spacing", () => {
    // The reason cn exists at all: a component's own padding must be overridable.
    expect(cn("px-4", "px-6")).toBe("px-6");
  });

  it("collapses conflicting background colours", () => {
    expect(cn("bg-surface", "bg-surface-raised")).toBe("bg-surface-raised");
  });

  it("drops falsy values", () => {
    expect(cn("px-4", false, undefined, null, "py-2")).toBe("px-4 py-2");
  });
});
