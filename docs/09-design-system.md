# 09 · Design System

Apple-grade restraint, Gymshark-grade energy. Dark-first, light-complete.

---

## 1. Design principles

1. **The data is the interface.** Numbers are the hero. Chrome recedes.
2. **Dark is the default.** Gyms are dim, sessions are at night, and the product reads as
   premium in dark. Light mode is a first-class alternative, not an afterthought.
3. **One accent.** A single high-energy colour marks progress and primary action. Everything
   else is neutral. Two accents halve the meaning of both.
4. **Motion explains, never decorates.** Every animation answers "where did this come from?"
5. **Thumb-first.** The primary action sits in the lower third of the screen.
6. **Never punish the user.** A missed day is neutral grey, not red. Shame drives churn.

---

## 2. Colour

### 2.1 Brand

| Token | Value | Use |
|---|---|---|
| `--brand-500` | `#C8FF3D` | The accent. Primary CTA, progress fills, PR celebration |
| `--brand-600` | `#B2E82A` | Hover/pressed |
| `--brand-400` | `#D8FF6E` | Subtle fills, focus glow |
| `--brand-ink` | `#0F0F11` | Text **on** brand fills — brand is a light colour; white text on it fails contrast |

A single electric lime against near-black. High energy, unmistakable, and — critically — it
reads as "achievement" rather than "alert", which red and orange cannot do in a fitness context.

### 2.2 Surfaces & ink

| Role | Dark | Light |
|---|---|---|
| Page plane | `#0A0A0B` | `#F4F4F2` |
| Surface 1 (cards) | `#0F0F11` | `#FAFAFA` |
| Surface 2 (raised, sheets) | `#17171A` | `#FFFFFF` |
| Surface 3 (inputs, wells) | `#1F1F23` | `#F0F0EE` |
| Hairline border | `rgba(255,255,255,0.08)` | `rgba(11,11,11,0.10)` |
| Primary ink | `#FFFFFF` | `#0B0B0B` |
| Secondary ink | `#C3C2B7` | `#52514E` |
| Muted ink (axis, meta) | `#898781` | `#898781` |

Elevation in dark mode is expressed by **surface lightness, not shadow** — shadows are close to
invisible on near-black. In light mode, elevation uses a soft shadow plus the same surface
ladder.

### 2.3 Status

Reserved. Never reused as a series colour, and never the only signal — always paired with an
icon and a label.

| Role | Hex | Meaning in GymPulse |
|---|---|---|
| good | `#0CA30C` | Target met, streak alive, verified food |
| warning | `#FAB219` | Approaching a limit, unverified data |
| serious | `#EC835A` | Missed target, sync backlog |
| critical | `#D03B3B` | Destructive action, failed save, safety warning |

On the **light** surface, `warning` and `serious` fall below 3:1 — the icon + label pairing is
the required mitigation there.

### 2.4 Semantic mapping

```css
--color-bg            /* page plane */
--color-surface       /* card */
--color-surface-raised
--color-text          /* primary ink */
--color-text-muted
--color-border
--color-accent        /* brand-500 */
--color-accent-ink    /* brand-ink */
--color-focus         /* brand-400 */
```

Components consume **semantic** tokens only. No component references `--brand-500` or a raw hex
directly, so a theme change is a variable swap.

---

## 3. Charts & data visualisation

Charts are most of this product's surface area. They follow one validated system.

### 3.1 Categorical palette (validated)

Assigned in **fixed slot order, never cycled**. Colour follows the entity, so filtering a series
out never repaints the survivors.

| Slot | Hue | Dark | Light | Typical GymPulse series |
|---|---|---|---|---|
| 1 | blue | `#3987E5` | `#2A78D6` | Volume |
| 2 | orange | `#D95926` | `#EB6834` | Calories |
| 3 | aqua | `#199E70` | `#1BAF7A` | Protein |
| 4 | yellow | `#C98500` | `#EDA100` | Carbs |
| 5 | magenta | `#D55181` | `#E87BA4` | Fat |
| 6 | green | `#008300` | `#008300` | Chest / group A |
| 7 | violet | `#9085E9` | `#4A3AA7` | Back / group B |
| 8 | red | `#E66767` | `#E34948` | Legs / group C |

Validated against GymPulse's own chart surfaces (`#0F0F11` dark, `#FAFAFA` light):

```bash
node scripts/validate_palette.js "#3987e5,#d95926,#199e70,#c98500,#d55181,#008300,#9085e9,#e66767" \
  --mode dark  --surface "#0f0f11"     # all checks PASS
node scripts/validate_palette.js "#2a78d6,#eb6834,#1baf7a,#eda100,#e87ba4,#008300,#4a3aa7,#e34948" \
  --mode light --surface "#fafafa"     # all checks PASS (contrast WARN on 3 slots)
```

Results to honour:

- **Dark:** every check passes, all eight slots ≥ 3:1 against the surface.
- **Light:** lightness band, chroma, CVD separation (worst adjacent ΔE 9.1) and normal-vision
  separation (worst 19.6) all pass. **Contrast warns** for aqua (2.7), yellow (2.07) and magenta
  (2.58) — so on light backgrounds those series **must** carry visible direct labels or a table
  view. That is a requirement, not a suggestion.
- **Scatter, bubble and small-multiple forms cap at three series** (slots 1–3). Beyond three,
  fold into "Other" or facet — the all-pairs floors cannot be cleared past that.
- A ninth series is never a generated hue.

**Sequential** (magnitude — the workout calendar heatmap, muscle-volume maps): one hue,
light → dark, blue by default. **Diverging** (surplus vs deficit): blue ↔ red with a neutral
grey midpoint — never a hue at the midpoint, never a rainbow.

### 3.2 Chart rules

- **One axis. Never dual-axis.** Weight and calories on one chart with two scales is the single
  most misleading chart in fitness apps. Two charts, or index both to a common base.
- **Thin marks.** 2 px lines, ≥ 8 px markers, 4 px rounded data-ends on bars anchored to the
  baseline, 2 px surface gap between adjacent or stacked fills.
- **Recessive chrome.** Hairline gridlines, muted axis ink, no chart borders, no background fills.
- **Legend present for ≥ 2 series** (a single series needs none — the title names it); up to 4
  series are also direct-labelled, so identity is never colour-alone.
- **Selective labels only.** Label the first, last and extreme points — never every point.
- **Hover by default.** Crosshair + tooltip on line/area, per-mark tooltip on bar/dot/cell.
- **Text wears text tokens**, never the series colour.
- **A table view is available for every chart.** It is the accessibility fallback, and power
  users want it anyway.
- **Empty states are explicit.** "Log your first weigh-in", never an empty grid.

### 3.3 Stat tiles

The dashboard is mostly stat tiles, not charts. A tile is: label (muted, small caps), value
(large, proportional figures), delta (with icon + sign, status-coloured), and an optional
sparkline or ring.

```
┌──────────────────────┐   ┌──────────────────────┐
│ CALORIES             │   │ WEIGHT TREND         │
│ 2,140 / 2,400        │   │ 78.4 kg              │
│ ▓▓▓▓▓▓▓▓▓▓░░░  89%   │   │ ↓ 0.4 kg  this week  │
└──────────────────────┘   └──────────────────────┘
```

- **Values use proportional figures**; `tabular-nums` is reserved for columns that must align
  vertically (set tables, axis ticks).
- Deltas pair an arrow **and** a sign with colour — never colour alone.
- A ring/meter is used only for a value with a real denominator (calories vs target, water vs
  goal). No decorative rings.
- **Not everything needs a chart.** A single number with a delta beats a five-point line chart.

---

## 4. Typography

**Inter Variable** (self-hosted, `display: swap`). One family, weight and size carry hierarchy.

| Token | Size / line | Weight | Use |
|---|---|---|---|
| `display` | 40 / 44 | 700, −0.02em | PR celebration, onboarding headline |
| `h1` | 32 / 38 | 700, −0.02em | Screen title |
| `h2` | 24 / 30 | 600, −0.01em | Section |
| `h3` | 20 / 26 | 600 | Card title |
| `body-lg` | 17 / 26 | 400 | Primary reading |
| `body` | 15 / 22 | 400 | Default |
| `caption` | 13 / 18 | 500 | Meta, labels |
| `overline` | 11 / 14 | 600, 0.08em, uppercase | Tile labels |
| `numeric-hero` | 48 / 52 | 700 | The one big number |
| `numeric-table` | 15 / 20 | 500, `tabular-nums` | Set tables, axis ticks |

Negative tracking on large text is what makes headings feel Apple-like rather than default-web.

---

## 5. Space, radius, elevation

**4 px base scale:** 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.

| Radius | Value | Use |
|---|---|---|
| `sm` | 8 px | Chips, badges, inputs |
| `md` | 12 px | Buttons, small cards |
| `lg` | 16 px | Cards |
| `xl` | 24 px | Sheets, modals |
| `full` | 9999 px | Avatars, pills, FAB |

Generous radii are the strongest single signal of the "premium rounded" aesthetic — but they are
consistent, never mixed arbitrarily within a view.

| Elevation | Dark | Light |
|---|---|---|
| 0 | surface-1 | surface-1 |
| 1 | surface-2 | surface-2 + `0 1px 2px rgba(0,0,0,.06)` |
| 2 | surface-2 + hairline | + `0 4px 12px rgba(0,0,0,.08)` |
| 3 (modal) | surface-3 + hairline | + `0 12px 32px rgba(0,0,0,.12)` |

---

## 6. Components

| Component | Variants | Notes |
|---|---|---|
| **Button** | primary (brand fill, brand-ink text), secondary (surface-3), ghost, destructive | Heights 36/44/52. Min touch target 44 px. Loading state replaces the label with a spinner and **keeps the width** — no layout jump |
| **Card** | default, interactive, stat | `lg` radius, hairline border, `p-16`/`p-20` |
| **Input** | text, number, stepper, search | Stepper is the default for weight/reps — ±2.5 kg and ±1 rep. Labels above, never placeholder-as-label |
| **SetRow** | normal, warmup, drop, failure, completed | The product's most-used component. Fixed column grid, `tabular-nums`, 48 px tall, tap-to-complete |
| **Sheet** | half, full, scrollable | Bottom sheet on mobile, dialog on desktop. Drag-to-dismiss |
| **Tabs / Segmented** | — | iOS-style pill with a spring-animated indicator |
| **Chip** | filter, muscle, equipment | Horizontally scrollable rows |
| **ProgressRing** | calories, macros, water | Only with a real denominator |
| **RestTimer** | inline, sticky, notification | Absolute `endsAt`, never a decrementing counter ([07](07-frontend-web.md) §4) |
| **EmptyState** | icon + line + action | Every list has one, written specifically |
| **Skeleton** | text, card, chart | Matches final layout dimensions exactly — no CLS |
| **Toast** | info, success, error, undo | Bottom on mobile, top-right on desktop. Destructive actions always offer Undo |

Built on **Radix UI** (web) and equivalents on mobile: correct roles, focus management and
keyboard behaviour come from the primitive, not from us remembering.

---

## 7. Motion

| Token | Duration | Easing | Use |
|---|---|---|---|
| `instant` | 100 ms | ease-out | Toggles, checkbox, tap feedback |
| `fast` | 180 ms | `cubic-bezier(.2,0,0,1)` | Hover, tooltip, chips |
| `base` | 260 ms | `cubic-bezier(.2,0,0,1)` | Sheets, cards, tab indicator |
| `slow` | 420 ms | spring (stiffness 220, damping 26) | Screen transitions, PR celebration |

Rules: **motion originates from the element that triggered it** (a sheet rises from the button
that opened it); lists stagger by 30 ms per item, capped at 8 items; numbers count up only on the
dashboard hero and only once per session; the PR celebration is the one deliberately
"expensive" animation in the product — it earns its place because it is the emotional payoff of
the whole app.

**`prefers-reduced-motion` disables every non-essential animation** and replaces transitions with
instant state changes. The PR celebration becomes a static badge.

---

## 8. Iconography & imagery

- **Lucide** icons, 1.5 px stroke, 20/24 px. One set, no mixing.
- Exercise media on a neutral background, consistent framing, AVIF/WebP with a blurred
  placeholder.
- **Progress photos are never used as decoration** anywhere in the product — no thumbnails in
  feeds, no previews in lists, no marketing use, ever. They appear only inside the user's own
  progress section.

---

## 9. Accessibility (non-negotiable)

| Requirement | Standard |
|---|---|
| Text contrast | ≥ 4.5:1 (≥ 3:1 for ≥ 24 px), both themes |
| UI boundary contrast | ≥ 3:1 |
| Touch targets | ≥ 44 × 44 px |
| Focus indicator | 2 px `--color-focus` ring, 2 px offset, always visible |
| Colour independence | Every colour-coded meaning also has an icon, label or shape |
| Motion | `prefers-reduced-motion` fully honoured |
| Screen readers | Semantic roles, live regions for PRs, timer completion and save failures |
| Dynamic type | Layouts survive 200 % text scaling without clipping |
| Charts | Legend + direct labels + table view fallback |

`axe-core` in CI on every web route; manual VoiceOver and TalkBack passes each release.

---

## 10. Tone of voice

- **Direct and warm, never a drill sergeant.** "Nice session — that's a 5 kg PR on bench."
- **Never shaming.** A missed day is "Ready when you are", not "You skipped your workout".
- **Specific over generic.** "You've averaged 118 g protein against a 160 g target this week"
  beats "Try to eat more protein".
- **Never a medical claim.** "Your weight trend is down 0.4 kg/week" — never "you're losing fat
  at a healthy rate". The distinction is a product rule and a safety rule
  ([10](10-ai-architecture.md) §7).
- **Errors say what to do next.** "Couldn't save — we'll retry when you're back online" beats
  "Error 500".

---

**Next:** [10 · AI Architecture](10-ai-architecture.md)
