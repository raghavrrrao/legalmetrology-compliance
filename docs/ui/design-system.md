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
| **Background** | three radial washes at ≤7% on one fixed pseudo-element — depth, not a landing page |
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

Glass is carried by a `.glass` modifier on exactly five kinds of surface — the
hero label card, the four workflow tiles, the recent-inspections panel, the
verdict, and the scan flow's checkpoint. It is a modifier rather than a base
style so the list is visible in the markup; that is what stops "subtle
glassmorphism" becoming a frosted rectangle behind every paragraph. Its
`@supports` fallback is an *opaque* white card, not a transparent one, because
a see-through panel over text is worse than a solid panel.

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

## 3a. Composition

Tokens were not the problem the first pass left behind. The home page was a
page header, a "Backend connection" card and two warning panels — correct,
honest, and indistinguishable from an admin console. Colour and radius cannot
fix that; the arrangement had to change.


### The product name

The application is **NIRIKSHAN**, presented as

    NIRIKSHAN
    Compliance Assistant

in the web header and as `NIRIKSHAN` alone where there is no room for the
tagline — the mobile home header, the phone-width web header, the browser tab,
and the app's display name on a device.

**"Legal Metrology" is not the product.** It is the name of the Rules the
system checks against, and it stays wherever the law is being referred to: the
hero eyebrow, the footer disclaimer, every finding's clause and legal
reference. Renaming the product does not rename the legislation, and the two
must never be collapsed into one string.

Nothing internal was renamed. The Django project, Python packages, database
tables, API paths, environment variables, the Expo `slug`, the iOS
`bundleIdentifier` and the Android `package` are all unchanged — a bundle
identifier is a registry key, and changing one publishes a different
application rather than renaming this one.

### Home

    HEADER      mark · NIRIKSHAN / Compliance Assistant       Home  Inspections  [+ New scan]

    HERO        § Legal Metrology (Packaged Commodities) Rules, 2011
                Check a package before you trust the label.        ┌──────────────┐
                Scan or upload a packaged-product label…           │ label card   │
                [ Scan a label ]  [ Upload images ]                │ scan frame   │
                ⓘ Automated assistance — never a legal             │ field rows   │
                  determination.                                   └──────────────┘

    NOTICES     placeholder engine / no verified rules / cannot reach backend

    HOW IT      01 Scan   02 Extract   03 Check   04 Review
    WORKS       four glass tiles

    RECENT      real rows from GET /api/v1/compliance/, or a polished empty
                state with one button

    STATUS      ▸ System status                     (closed <details>, last)

    FOOTER      Automated assistance only · Not a legal determination · Read the full notice

Three things about this are deliberate:

**The diagnostics moved, the honesty notices did not.** API version, database
ping and Tesseract build are now a closed `<details>` at the bottom. The two
notices that say the system *cannot currently produce a real finding* stay
directly under the hero, because they are not diagnostics — they are the
difference between "this label was checked" and "nothing here is a real
reading".

**The hero illustration asserts nothing.** It draws the shape of a reading: the
declaration names this extractor actually looks for, blank bars where values
would be, a scan frame, and ticks. No MRP, no net quantity, no brand. Putting a
fabricated `₹350` on the front page of a tool that exists to check real ones
would be absurd, and it is `aria-hidden` because the sentence beside it already
says everything it shows.

**Recent inspections are real or absent.** The rows come from the same endpoint
and the same `InspectionRow` the Inspections screen uses. There is no
inspection count, no pass rate, no score.

### Result

    Inspection report
      breadcrumb · title · "A saved record of one label check…"

    VERDICT (glass, tone-tinted)
      (?)  AUTOMATED COMPLIANCE CHECK
           Requires review
           Packaged food · Checked 23 Sept 2026, 4:11 pm       engine v0.3.0 · 214 ms
      1 requirement failed · 3 require review · 4 passed.
      <the engine's own summary sentence>
      ─────────────────────────────────────────────
      [4 passed] [1 failed] [3 require review] [2 did not apply] [8 examined]
      <notes: human review recommended / N/A is not a pass / review is not a pass>

    CLASSIFICATION      suggestion · model confidence · label phrases · confirmation state
    REQUIREMENTS        finding cards, failures first
    EVIDENCE            photo with the read regions outlined
    EXTRACTION          what was read
    DECLARATIONS        what a person stated

The report header is what makes this read as a record rather than a row: a
filled status disc, the outcome as a word at ~2rem, and under it what was
inspected and when. **No product name is shown, because the API does not carry
one** — this system reads labels, it does not identify products.

The summary tiles are the engine's own `rules_*` counts and nothing else. There
is no percentage, no score, and no derived rate anywhere on the screen.

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

| Width | What changes |
|---|---|
| **≥ 1440px** | gutter 32px; the hero gets its full 48px column gap |
| **1024–1440px** | two-column hero, four workflow tiles across, 78rem (1248px) content column |
| **≤ 1200px** | workflow drops to two across |
| **≤ 1024px** | gutter 16px; the hero stacks, copy first, illustration below at ≤30rem |
| **≤ 768px** | illustration hidden; hero buttons go full width; header becomes two rows with each nav item an equal share (keeps all three over 44px); workflow tiles become one column with the number beside the title; `read-field`, `status-list`, `review-summary`, `suggestion` collapse to one column; pagination stacks |
| **≤ 424px** | gutter 12px; answer pills one per row; count tiles full width |

### How this was verified, and what could not be

Rendered in headless Edge against a stub API and inspected as images at
**1920, 1440, 1280, 1024, 768 and 492 CSS px** — no horizontal scrolling at any
of them, the hero stays balanced, buttons stay over 44px, and no text
truncates.

**430, 390 and 375 could not be rendered on this machine.** Windows clamps a
browser window to a minimum width, so the smallest layout viewport obtainable
is **492 CSS px** — measured, not assumed:

    --window-size=375  ->  document.documentElement.clientWidth = 492

This matters more than it sounds, because it produced a false alarm worth
recording: screenshots taken at `--window-size=375` *looked* like a page
overflowing horizontally, with the nav CTA and body text clipped on the right.
They were not. They were 375px-wide captures of a 492px layout, and "fixing"
the overflow they appeared to show would have been fixing nothing.

So the three phone widths are verified by rule inspection only: every grid
track is `minmax(0, 1fr)`, long values break with `overflow-wrap: anywhere`,
and the one element that cannot reflow — the declarations table, `min-width:
32rem` — is wrapped in `.table-scroll` so it scrolls inside its own container
rather than taking the page with it. **They should be confirmed on a real
phone, or in a browser with device emulation, before a demonstration.**

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

- **Phone widths below 492 CSS px are unverified visually.** See §6. Everything
  from 492px up was rendered and inspected; 430/390/375 were not, because this
  machine cannot produce a layout viewport that narrow.
- **Screenshots were taken with the Edge that ships with Windows**, driven by a
  throwaway static server that stubs the two endpoints the app calls. No
  browser-automation dependency was added. The stub bodies are shaped like the
  real serializers and exist only to make the screens render; none of that data
  is in the repository or presented anywhere as a real reading.
- **The mobile client has no "recent inspections".** The brief asked for one,
  and it is deliberately not built: `mobile/src/api/` has no history call, so
  it would need a new endpoint integration, a new screen and navigation to
  reach it. That is a feature, not a restyle, and it is out of scope for a
  UI pass.
- **No visual regression testing.** The 243 web and 203 mobile tests assert
  behaviour, text and semantics; none asserts on appearance. A styling
  regression would not fail a test — which is why this pass was checked by
  looking at rendered pages, and why doing so found two bugs the suite could
  not: a nav CTA rendering muted grey on a green pill (a specificity defect),
  and every value in a history row indented 40px by the user agent's `dd`
  margin.
- **Dark mode is not implemented.** The tokens are structured for it — every
  colour is a variable — but no `prefers-color-scheme: dark` block exists, and
  shipping a half-checked dark palette on a compliance tool is worse than
  shipping none.
- **Glass degrades to opaque white** on browsers without `backdrop-filter`, and
  is dropped entirely under forced colours. Deliberate graceful degradation,
  not a gap.
- **Mobile has no backdrop blur at all.** See §2.
- **Icons are inline SVG and platform glyphs.** No icon set was added.
