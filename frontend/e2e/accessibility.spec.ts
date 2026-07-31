import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * Accessibility is a gate, not a report (docs/09 §9).
 *
 * Only the public routes are covered here: everything behind the auth guard needs a
 * seeded session, which is a separate harness. These four still carry the design
 * system, the theme and every form primitive the rest of the app is built from, so a
 * contrast or labelling regression shows up here first.
 */
const PUBLIC_ROUTES = [
  { path: "/", name: "landing" },
  { path: "/login", name: "login" },
  { path: "/register", name: "register" },
  { path: "/forgot-password", name: "forgot password" },
];

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

for (const route of PUBLIC_ROUTES) {
  test(`${route.name} has no accessibility violations (dark)`, async ({ page }) => {
    await page.goto(route.path);
    const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();

    // The full node list is attached rather than just a count: "3 violations" tells
    // you nothing at 9am, whereas the selector and the failing contrast ratio do.
    expect(
      results.violations,
      JSON.stringify(
        results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
        null,
        2,
      ),
    ).toEqual([]);
  });

  test(`${route.name} has no accessibility violations (light)`, async ({ page }) => {
    // Light mode is a first-class theme, not an afterthought — and it is the one where
    // several chart slots sit closest to the contrast floor (docs/09 §2.2, §3.1).
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto(route.path);
    const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();

    expect(
      results.violations,
      JSON.stringify(
        results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
        null,
        2,
      ),
    ).toEqual([]);
  });
}

test("the keyboard reaches the login form without a mouse", async ({ page }) => {
  await page.goto("/login");

  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");

  // Something focusable must actually be focused — a page where Tab goes nowhere is
  // unusable by keyboard regardless of what axe reports about the markup.
  const focused = await page.evaluate(() => document.activeElement?.tagName ?? "BODY");
  expect(focused).not.toBe("BODY");
});

test("the focus ring is visible on the primary action", async ({ page }) => {
  await page.goto("/login");

  // Tabbed to, not `.focus()`d: the ring is `:focus-visible`, which deliberately does
  // not fire for programmatic or pointer focus. Driving it from the keyboard is the
  // only way to test what a keyboard user actually sees.
  let reached = false;
  for (let i = 0; i < 12 && !reached; i += 1) {
    await page.keyboard.press("Tab");
    reached = await page.evaluate(
      () => document.activeElement?.textContent?.trim() === "Log in",
    );
  }
  expect(reached, "the submit button was not reachable by keyboard").toBe(true);

  // A visible focus indicator is non-negotiable (docs/09 §9), and `outline: none` with
  // nothing in its place is the most common way it gets removed by accident.
  const outline = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement as Element);
    return { width: style.outlineWidth, style: style.outlineStyle, color: style.outlineColor };
  });

  expect(outline.style).not.toBe("none");
  expect(parseFloat(outline.width)).toBeGreaterThan(0);
});
