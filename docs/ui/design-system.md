# Design system

The visual language shared by the web client (`frontend/`) and the mobile
client (`mobile/`), and the reference both are checked against.

**Scope: appearance only.** Nothing in this redesign touched a compliance rule,
the applicability engine, extraction, OCR, the classifier, the database schema,
an API contract or any backend behaviour. The backend remains the source of
truth for every word, status and number on screen.

---

## 1. The two rules this system is built around

**1. Nothing in the styling layer encodes a compliance decision.**

There is no selector mapping `compliant` to green. A component picks a *tone*
from the raw status the backend sent — `utils/compliance.js` on the web,
`utils/status.ts` on mobile — and the styling layer only says what a tone looks
like. If the API grows a fifth verdict tomorrow, it renders neutrally and the
UI says it is unrecognised, rather than inheriting whichever colour happened to
be the default. Rendering an unknown verdict in green is the specific failure
this shape prevents.

**2. The accent is never a verdict.**

`--colour-primary` (`#0E7C50`) means "this is the primary action". It is a
*different green* from `--tone-success` (`#10693A`) on purpose. If a primary
button and a passing check were the same colour, the button would start reading
as a result.

Colour is never the only carrier of a status either. Every verdict, finding and
callout also carries its status in words and a symbol, so the interface reads
the same in greyscale, under Windows forced colours, and to a screen reader.

---

## 2. Visual direction

iOS 18, read as a set of constraints rather than a skin:

| | |
|---|---|
| **Ground** | near-white (`#F4F5F7`), never pure white, so white surfaces have something to sit on |
| **Surfaces** | white, hairline border, shadow soft enough to read as lift rather than as a drop |
| **Corners** | large but controlled — 18px on a card, 24px on the two elements meant to read as sheets |
| **Accent** | one restrained green, used for actions and wayfinding only |
| **Type** | one optical family (system/SF), hierarchy by size, weight and tracking |
| **Translucency** | exactly two places, both of them surfaces content scrolls *under* |
| **Motion** | one duration (180ms), one curve, and all of it switchable off |

Deliberately avoided: neon, gradients as decoration, glass everywhere, a
compliance score, a dashboard of invented statistics.

### Where translucency is and is not used

The web sticky header gets `backdrop-filter: saturate(180%) blur(20px)`. That
is the one element content passes beneath, and the blur is what keeps the
navigation legible over whatever is scrolling under it. It sits behind an
`@supports` query, so a browser without `backdrop-filter` gets an opaque header
rather than a see-through one, and it is dropped entirely under
`forced-colors: active`.

Everywhere else is opaque, and that is a performance decision rather than a
stylistic one. A full-viewport `backdrop-filter` costs a recomposited layer per
frame on a phone and buys no legibility. The mobile pinned action bar gets a
hairline and a shadow instead of `expo-blur`: a real backdrop blur there would
mean a new native dependency and a continuously recomposited layer on a screen
the user scrolls, to keep one button legible.

---

## 3. Tokens

The two files hold the same values in each platform's own idiom. They are
values rather than a shared package on purpose: a React Native app importing
the web's CSS would be carrying a layout model it cannot run. **What is shared
is the vocabulary; layout stays native** — which is why the mobile theme has
`elevation` and the web has `backdrop-filter`, and neither has the other.

| | web | mobile |
|---|---|---|
| file | `frontend/src/styles/index.css` (`:root`) | `mobile/src/theme.ts` |

### Colour

| Token | Value | Use |
|---|---|---|
| `page` / `background` | `#F4F5F7` | the ground |
| `surface` | `#FFFFFF` | cards, panels, the header |
| `surface-muted` | `#F6F7F9` | card headers, recessed blocks |
| `surface-sunken` | `#F0F1F4` | the evidence photo well |
| `border` | `#E4E5EA` | hairlines |
| `border-strong` | `#D3D5DC` | control outlines, dashed edges |
| `text` | `#1C1C1E` | body |
| `muted` / `textSecondary` | `#5B5F66` | secondary prose |
| `faint` / `textMuted` | `#6E7076` | metadata, captions |
| `primary` | `#0E7C50` | primary action fill |
| `primary-hover` / `primaryPressed` | `#0A6640` | pressed/hover, and the accent as text |
| `primary-soft` | `#E8F4EE` | active nav pill, selected tint |
| `primary-softer` | `#F3FAF6` | dropzone hover ground |
| `accent` | `#0A6640` | the accent used *as text* on light |

There is deliberately no `accent-soft`: it used to be a second name for
`primary-soft` with the same hex, which is how two tokens drift into two
slightly different greens.

### Tones

Named for the tone, never for a verdict.

| Tone | Text | Background | Border | Means |
|---|---|---|---|---|
| `success` | `#10693A` | `#E7F4EC` | `#B6DDC5` | the check passed |
| `error` | `#B3261E` | `#FDECEA` | `#F2C4C0` | the check failed |
| `error` (strong) | `#B3261E` | `#FADBD8` | `#E9B3AE` | the error **verdict** only |
| `review` | `#3A4C63` | `#E9EFF6` | `#C6D4E4` | a person must look at this |
| `warning` | `#8A5300` | `#FDF4E3` | `#EED6A6` | a notice about the reading |
| `muted` | `#56585E` | `#F0F1F4` | `#DCDDE2` | not applicable — **not a pass** |
| `neutral` | `#4A4C52` | `#EEEFF2` | `#DCDDE2` | unrecognised |

The error *verdict* takes the stronger tint while an error *panel* takes the
lighter one. This is the one place the design spends saturation: the verdict is
the loudest element on the loudest screen, and a package that failed has to be
unmistakable at a glance.

`muted` exists so an exemption never looks like a pass. It is also the only
tone drawn with a **dashed** edge, so the difference survives greyscale.

### Spacing, radius, elevation, motion

| | web | mobile |
|---|---|---|
| spacing | `--space-1…7` = 4, 8, 12, 16, 24, 32, 48px | `spacing.xs…xxl` = 4, 8, 12, 16, 24, 32 |
| radius | `xs` 6, `sm` 10, base 14, `lg` 18, `xl` 24, `pill` 999 | same names, same numbers |
| elevation | `--shadow-card`, `--shadow-raised`, `--shadow-overlay` | `elevation.card`, `elevation.raised` (per-platform) |
| motion | `--duration` 180ms, `--ease` `cubic-bezier(.32,.72,0,1)` | RN defaults; no custom animation added |
| tap target | `--tap` 2.75rem (44px) | `MIN_TOUCH_TARGET` 48 |

### Type

Web is a single system stack (`-apple-system` first). The previous design
paired a serif for titles with a sans for everything else; iOS 18 is one
optical family throughout, and the hierarchy is carried by size, weight and
tracking instead. Negative tracking is applied from ~1rem upward and never
below, where tightening costs legibility.

---

## 4. Components

| Web class | Mobile component | Notes |
|---|---|---|
| `.card` | `Card` | hairline + soft shadow, 18px radius, tinted header band |
| `.button`, `--primary`, `--quiet`, `--link`, `--large`, `--block` | `Button` (`primary`/`secondary`/`text`) | ≥44/48px tall, visible pressed state |
| `.status-badge` | `StatusBadge` | tone + symbol + word |
| `.count-chip` | — (mobile keeps the counts as one sentence) | the backend's own counts only |
| `.panel`, `.callout` | `Callout` | tinted, with a coloured rule down the leading edge |
| `.verdict` | `VerdictPanel` **(new)** | the tinted sheet the verdict sits on |
| `.finding` | `FindingCard` | tone as a 4px leading rule, dashed for not-applicable |
| `.empty-state` | — | dashed outline, centred |
| `.spinner`, `.workflow` | `ProgressSteps` | real steps, never a fake percentage |
| `.field`, `.question__option` | — | radios styled through their label, so keyboard behaviour stays the browser's |
| `.skip-link` **(new)** | — | first in the tab order, visible on focus |

---

## 5. Accessibility

### Contrast, measured

Every pair below was computed, not eyeballed. **Lowest ratio anywhere in the
system: 4.54 : 1.** Nothing falls back to "AA for large text only".

| Pair | Ratio | |
|---|---|---|
| `text` on surface `#FFFFFF` | **17.01 : 1** | AAA |
| `text` on page `#F4F5F7` | **15.60 : 1** | AAA |
| `muted` on surface | **6.42 : 1** | AA |
| `muted` on page | **5.88 : 1** | AA |
| `faint` on surface | **4.95 : 1** | AA |
| `faint` on page | **4.54 : 1** | AA |
| white on `primary` `#0E7C50` | **5.23 : 1** | AA |
| white on `primary-hover` `#0A6640` | **7.03 : 1** | AAA |
| `accent` on surface | **7.03 : 1** | AAA |
| `accent` on `primary-soft` | **6.23 : 1** | AA |
| `success` on `success-bg` | **5.98 : 1** | AA |
| `error` on `error-bg` | **5.72 : 1** | AA |
| `error` on `error-strong-bg` | **5.04 : 1** | AA |
| white on `error` | **6.54 : 1** | AA |
| `review` on `review-bg` | **7.58 : 1** | AAA |
| `warning` on `warning-bg` | **5.79 : 1** | AA |
| `neutral` on `neutral-bg` | **7.46 : 1** | AAA |
| `muted` tone on `muted-bg` | **6.30 : 1** | AA |
| `text` on any tone background | **13.1 – 15.0 : 1** | AAA |

### The rest

- **Never colour alone.** Every status carries a word and a symbol.
- **Focus.** One `:focus-visible` ring — 2px accent, 2px offset — on every
  element that takes focus. Inputs also get a soft halo. `:focus-visible`
  rather than `:focus`, so a mouse click leaves no ring but a keyboard user
  always sees where they are.
- **Skip link.** First in the tab order, hidden until focused. `<main>` carries
  `tabIndex={-1}` so the jump moves focus and not only the viewport.
- **Targets.** 44px on web, 48px on mobile, including the navigation items,
  the answer pills and the disclosure summaries.
- **Reduced motion.** `prefers-reduced-motion: reduce` stops every transition,
  the spinner animation and all three transform effects.
- **Forced colours.** `forced-colors: active` restores borders on every surface
  that relied on a tint, and drops the header blur.
- **Semantics unchanged.** Real `<fieldset>`/`<legend>`, real radios, real
  `<details>`, `aria-current` on the active nav item, `role="alert"` on error
  panels, `accessibilityRole="header"` on mobile headings.

---

## 6. Responsive behaviour (web)

Three breakpoints. The layout is fluid between them, so none is a
pixel-perfect target for one device — each is the width at which a particular
arrangement stops working.

| Width | What changes |
|---|---|
| **> 1024px** | full layout, 70rem content column, gutter 24px |
| **≤ 1024px** | gutter drops to 16px, vertical padding tightens |
| **≤ 768px** | header becomes two rows (identity, then nav across the full width, each item an equal share so all three stay over 44px); tagline hidden; answer pills go two-per-row; `read-field`, `status-list`, `review-summary` and `suggestion` collapse to one column; the workflow connector is dropped; pagination stacks |
| **≤ 424px** | gutter 12px; answer pills go one-per-row (two 0.86rem pills start truncating "Not answered", and a truncated answer is worse than a taller form); count chips go full width |

**No horizontal scrolling at 1440, 1280, 1024, 768, 430, 390 or 375px.** Every
grid track is `minmax(0, 1fr)`, long values break with `overflow-wrap: anywhere`,
and the one element that genuinely cannot reflow — the declarations table, which
has a `min-width: 32rem` — is wrapped in `.table-scroll` so it scrolls inside
its own container rather than taking the page with it.

---

## 7. Mobile behaviour

Same language, native layout. The flow is unchanged:

    camera / gallery → preview → upload → extraction → compliance → result

- `Screen` gives every screen a 16px gutter plus safe-area insets, with an
  optional pinned footer for the primary action.
- Navigation is the native stack; the header takes the accent for its back
  chevron and actions, and leaves the title text-coloured, so the accent means
  "you can press this".
- Nothing in the compliance path is duplicated on the device. The phone
  uploads, the server decides, the screen renders what came back.

---

## 8. What was fixed along the way

The web stylesheet was three stylesheets stacked on top of each other — a base
system, a "product surface" pass and a "visual pass" — each appended by a later
branch and each silently overriding the one before it.

| | before | after |
|---|---|---|
| lines | 3,403 | 2724 |
| selectors declared more than once | **118 of 211** (`.technical-details` ten times) | 0 |
| tokens referenced but never defined | 2 (`--radius-2`, `--colour-surface-sunken`) | 0 |
| tokens defined but never used | 3 | 0 |
| dead selectors (styled, never in any markup) | 9 | 0 |
| built CSS | 47.09 kB (8.05 kB gzip) | 39.63 kB (7.02 kB gzip) |

The class names are unchanged, so the markup and the tests are unchanged. What
changed is that there is now a single answer to "what does a card look like".

The other inconsistency was across platforms: **the mobile app used a blue
primary (`#1F4E9C`) while the web used a dark green.** Both are now the same
green.

---

## 9. Known limitations

- **No screenshots.** No browser automation is installed in this environment and
  adding Playwright plus its browsers for image capture was not a dependency
  worth taking. The responsive claims above are from the stylesheet's own rules
  and a static check for fixed widths, not from rendered captures — they should
  be confirmed by eye before a demonstration.
- **No visual regression testing.** The 243 web and 203 mobile tests assert
  behaviour, text and semantics; none asserts on appearance. A styling
  regression would not fail a test.
- **Dark mode is not implemented.** The tokens are structured for it — every
  colour is a variable — but no `prefers-color-scheme: dark` block exists, and
  shipping a half-checked dark palette on a compliance tool is worse than
  shipping none.
- **The header blur is the one translucent surface on the web** and is absent
  on browsers without `backdrop-filter`. That is a deliberate graceful
  degradation, not a gap.
- **Mobile has no backdrop blur at all.** See §2.
- **Icons are inline SVG and platform glyphs.** No icon set was added.
