# Mobile client (`mobile/`)

A React Native app, built with Expo, that photographs a package label and
sends it to the same Django REST API the web frontend uses. It is a second
client of the compliance engine, not a second engine: nothing legal, nothing
OCR and nothing learned runs on the phone.

```
Phone                                   Backend (one container, docs/deployment.md)
─────                                   ────────────────────────────────────────────
camera / gallery
  → validate (format, size)             POST /api/v1/extraction/
  → upload photograph  ────────────────►  validate ─ store ─ OCR ─ field extraction
                                           ─ normalise ─ product classification
  ◄──────────────────────────────────── 201 ExtractionRun (+ product_classification)
  → evaluate the run id  ──────────────► POST /api/v1/compliance/
                                           applicability ─ deterministic rule engine
  ◄──────────────────────────────────── 201 ComplianceCheck (verdict, findings, reading)
result screen: verdict, summary, findings, what was read, classification (suggestion)
```

This document covers what the app is, how to run it, and what it does not do.
The API it consumes is documented in [api.md](api.md); the reasons the engine
is server-side are in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Status

**Foundation.** The flow above works end to end against a running backend,
with tests for every layer. It has been verified as follows, and no further
than this:

| Check | Evidence |
|---|---|
| Unit, hook, screen and navigation tests | `npm test` in `mobile/`: 14 suites, 181 tests |
| Type check and lint | `npm run typecheck`, `npm run lint` |
| Expo project configuration | `npx expo-doctor`: 21/21 checks |
| API contract | The mappers were run over real responses from a local backend (`tesseract` 0.4.0) - extraction, compliance with and without a category, and the 400/404 error envelopes |
| Android native project | `npx expo prebuild --platform android` generates it; the merged manifest carries `INTERNET` and `CAMERA` (from expo-image-picker), storage permissions only up to API 32, and no `RECORD_AUDIO`; cleartext HTTP is enabled in the **debug** manifest only. `gradlew assembleDebug` produced `app-debug.apk` on Windows (JDK 21, SDK 36, NDK 27; 35 minutes cold). Not installed anywhere - no device or emulator was attached |
| iOS | Configured (`bundleIdentifier`, usage strings) and type-checked. **Not built and not run**: this needs a Mac with Xcode, which was not available |
| On a device | **Not exercised in this branch.** No emulator or physical phone was attached |

It is not production-ready and does not claim to be: it has no sign-in, it
depends on the backend's demonstration switch (below), and it has not been run
on hardware.

## Technology decision

**Expo SDK 57 (React Native 0.86, React 19), TypeScript, React Navigation
(native stack), `expo-image-picker`, Jest via `jest-expo`.**

Considered against the alternatives:

- **Expo vs bare React Native.** Every native capability this app needs -
  camera capture, photo-library selection, runtime permissions, HTTPS
  multipart upload, safe-area insets - is covered by maintained Expo modules
  with no custom native code. Expo's *continuous native generation* means the
  `android/` and `ios/` directories are generated on demand (`npx expo
  prebuild`) and are git-ignored, which keeps a repository that already holds a
  backend, a web client and an ML package from gaining a few hundred generated
  native files. If a future step needs a native module Expo does not provide,
  `prebuild` produces an ordinary React Native project to add it to; nothing is
  locked in. Bare React Native would have brought the native directories,
  their toolchain upkeep and manual permission plumbing for no capability this
  branch uses.
- **System camera vs a custom viewfinder.** `expo-image-picker` opens the
  platform camera and the platform photo picker. They handle focus, exposure,
  rotation and HDR; they need the fewest permissions (the photo picker needs
  none on iOS 14+ and Android 13+); and they are the UI the user already knows.
  A live preview with framing guides (`expo-camera`) is a later decision if
  the OCR workstream asks for it.
- **TypeScript.** The Expo default, and the API contract is the thing most
  worth typing: `src/types/api.ts` is the wire format field for field. The web
  client is JavaScript with JSDoc; the two are separate clients and do not
  share code, so the difference costs nothing.
- **React Navigation native stack** rather than Expo Router. Four screens in a
  line do not need file-based routing, and the native stack gives platform back
  gestures, the Android back button and headers for free.
- **Jest (`jest-expo`) + Testing Library** rather than Vitest, which the web
  client uses. `jest-expo` is the preset the SDK is tested against and wires up
  React Native's transformer and native-module mocks; Vitest has no equivalent.
  The test *style* follows the web client: fixtures in the wire shape, `fetch`
  stubbed at the boundary, the real mappers and screens running in between.
- **Configuration through `EXPO_PUBLIC_` variables**, the direct counterpart of
  the web client's `VITE_` variables, with the same rule: read in one file
  (`src/config/env.ts`), public by construction, never a secret.

## Layout

```
mobile/
├── App.tsx                 providers: safe area, analysis state, navigation
├── app.json                Expo config: names, ids, permission strings, plugins
├── index.ts                registers App (Expo template)
├── jest.config.js          jest-expo preset
├── eslint.config.js        eslint-config-expo
├── .env.example            copy to .env for development (git-ignored)
├── .env.production         committed; the deployed API URL (public config)
├── assets/                 icons (Expo template)
├── tests/                  Jest setup, wire-shape fixtures, screen-test helpers
└── src/
    ├── api/                client.ts (the one HTTP client), extraction.ts, compliance.ts
    ├── config/env.ts       the ONLY reader of process.env; API base URL; upload limit
    ├── types/api.ts        the API contract: wire shapes and their camelCase mappings
    ├── services/           imagePicker.ts (camera/library + permissions), imageValidation.ts
    ├── hooks/              useLabelAnalysis.ts (the two-step flow), useImageSelection.ts, AnalysisContext.tsx
    ├── navigation/         RootNavigator.tsx, types.ts
    ├── screens/            HomeScreen, PreviewScreen, AnalysisScreen, ResultScreen
    ├── components/         Button, StatusBadge, Card, Callout, ProgressSteps, FindingCard,
    │                       ClassificationCard, ExtractedFieldsList, KeyValue, PhotoTips, Screen
    ├── utils/              errors.ts (user-facing messages), status.ts (tones), format.ts
    └── theme.ts            colours, spacing, type, minimum touch target
```

Tests sit next to the code they test (`*.test.ts`, `*.test.tsx`), as in the
web client.

### What each layer may do

- `src/api/` talks to the network. Nothing else calls `fetch`. It renames
  keys and throws `ApiError`; it decides nothing.
- `src/services/` talks to the platform (picker, permissions) and pre-checks a
  picked file. The backend is still the authority on every upload.
- `src/hooks/useLabelAnalysis.ts` sequences the two requests and holds the
  run id, so the photograph is uploaded once and a re-check never re-uploads.
- `src/screens/` render what came back. **No screen computes a verdict, a
  score, a count or an outcome.** The counts shown are the backend's `rules_*`
  fields; the tones in `utils/status.ts` are looked up from a value the backend
  returned, and an unrecognised value renders neutral, never green.

## Screens

```
Home ─────────► Preview ─────────► Analysis ─────────► Result
Take photo      Use this photo     Reading the label   verdict + summary
Choose from     Retake             Checking the        findings by status
gallery         Product type       requirements        what was read
tips            (optional)         error + retry       classification (suggestion)
                                                       technical details
                                                       Scan another label
```

- **Home.** Two buttons and five lines of advice (flat label, sharp text, no
  glare, whole panel, hold steady). A refused permission shows a message; when
  the system will no longer ask, an *Open Settings* button.
- **Preview.** The photograph, its size, and an optional product category
  code. It is a text field rather than a list because no endpoint lists
  categories (the web client's field is a text input for the same reason - see
  *Gaps* below). Blank is supported: the result then says the product type was
  not known.
- **Analysis.** "Analysing label…" with two steps that are the two real
  requests. The first covers upload, OCR and field extraction, which happen
  inside one request on the server and cannot be told apart from the client;
  the second is the rule engine. Nothing is a timer or a percentage. On
  failure: a plain message, *Try again* where a retry could work, and *Choose
  another photo*.
- **Result.** The verdict badge uses the backend's `result_display` and the
  summary is always beside it. Findings are grouped Failed → Needs review →
  Passed → Not applicable, each card carrying the rule's title, clause, the
  backend's message, the requirement in the rule's words, and the evidence
  excerpt with the OCR confidence labelled as *reading* confidence. The
  extracted fields are their own card. Technical details (ids, engine versions,
  timings, recognised text) are behind a toggle.

### Classification on the result screen

When `extraction.product_classification` is present the result shows:

```
Product classification
  Product classification   Packaged non-food
  Confidence               67%
  This confidence is the classifier's confidence in the product type.
  It says nothing about whether the label complies with the Rules.
  [ Re-check as Packaged non-food ]
```

The button appears only when the result was produced **without** a product
type. Pressing it is the person confirming the suggestion: the app sends
`category_code` to `POST /api/v1/compliance/` for the same run, which is the
call docs/api.md prescribes. Nothing copies the classifier's output into a
request on its own, and nothing thresholds its confidence. `category:
"unknown"` is shown as *Could not tell* with no button. When the field is
`null` or absent - which is what the deployed backend returns today, since it
runs `tesseract` 0.3.0 and the classifier arrived in 0.4.0 - no card is shown
and the technical details say *None was made for this reading*.

No percentage is ever shown next to the verdict. There is no compliance score
in the API and the app derives none.

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Node.js | 20.19+ (verified on 24.14) | Same as the web client |
| npm | 10+ (verified on 11.9) | npm only; no pnpm or yarn lockfiles |
| A running backend | this repository | Local, or the deployed one |
| **Android:** Android Studio, SDK Platform 35+, an emulator or a phone | | Only for a native build; Expo Go needs none of it |
| **iOS:** macOS with Xcode 16+ | | Only for a native build or the simulator |
| Expo Go on a phone | from the app stores | The quickest way to run in development |

## Setup and running

From the repository root:

```bash
cd mobile
npm install
cp .env.example .env          # optional - see "Configuration" below
npx expo start
```

Then either scan the QR code with **Expo Go** on a phone on the same Wi-Fi,
press `a` for an Android emulator, or `i` for the iOS simulator (Mac only).

The backend must be reachable *from the phone*. For a local backend that means
starting Django on all interfaces and allowing your machine's LAN address:

```bash
# root .env
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.20      # your LAN address
DEMO_PUBLIC_ANALYSIS_API=True                               # see "Authentication"

python backend/manage.py runserver 0.0.0.0:8000
```

### Configuration

One variable, read in exactly one file (`src/config/env.ts`):

| Variable | Where | Meaning |
|---|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | `mobile/.env` (dev, git-ignored) or `mobile/.env.production` (committed) | Base URL of the API **including `/api/v1/` and a trailing slash** |

Resolution order:

1. `EXPO_PUBLIC_API_BASE_URL`, if set (in a `.env` file or the shell).
2. In development with nothing set: the machine serving Metro, on port 8000 -
   `http://<metro-host>:8000/api/v1/`. On a phone running Expo Go this is the
   laptop that ran `npx expo start`, which is usually where Django is too. This
   is why the variable can be left unset for the common case.
3. In development with no Metro host either: `http://localhost:8000/api/v1/`.
4. In a **production build** with nothing set: the app refuses to start,
   exactly as the web client's build refuses. `mobile/.env.production` supplies
   the deployed URL so this only happens if it is deliberately blanked.

Set it explicitly when the default is wrong:

```bash
# Android emulator, backend on the same machine (10.0.2.2 is the host):
EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000/api/v1/
# Physical phone, backend on a laptop at 192.168.1.20:
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.20:8000/api/v1/
# Against the deployed backend, from a development build:
EXPO_PUBLIC_API_BASE_URL=https://legalmetrology-compliance-production.up.railway.app/api/v1/
```

Every `EXPO_PUBLIC_` value is inlined into the bundle and readable by anyone
who unpacks the app. It is public configuration. **No secret goes in any file
under `mobile/`.** The upload size pre-check (`MAX_UPLOAD_SIZE_MB`, 10) is a
constant in the same file, mirroring the backend's default; the backend's own
limit is the one that counts.

### Android

Expo Go covers development. For a native build:

```bash
cd mobile
npx expo run:android          # generates android/ (prebuild), builds, installs on the connected device/emulator
```

`android/` is generated and git-ignored; regenerate it with `npx expo prebuild
--platform android --clean` after changing `app.json`. The generated manifest
declares `INTERNET`, `CAMERA` (from `expo-image-picker`), and the legacy
storage permissions capped at API 32. `RECORD_AUDIO`, which the picker plugin
adds by default for video, is blocked in `app.json`. Cleartext `http://` is
allowed only in the debug manifest, so a release build talks HTTPS only.

On Windows, Gradle needs `JAVA_HOME` pointing at a JDK 17+ and
`ANDROID_HOME` at the SDK; `expo run:android` writes `android/local.properties`
for you. The first build downloads Gradle and the React Native dependencies
and takes a while.

### iOS

```bash
cd mobile
npx expo run:ios              # macOS with Xcode only; generates ios/, builds, launches the simulator
```

`app.json` sets the bundle identifier and the camera and photo usage strings
(the `NSCameraUsageDescription` / `NSPhotoLibraryUsageDescription` text the
system shows in the permission prompt). `ITSAppUsesNonExemptEncryption` is
false because the app uses only standard HTTPS. Nothing iOS-specific has been
run in this branch - see *Status*.

## Permissions

| Capability | Android | iOS | When asked |
|---|---|---|---|
| Camera | `CAMERA`, runtime | `NSCameraUsageDescription` | On the first *Take photo*, before the camera opens |
| Photo library | none on 13+ (system Photo Picker); `READ_EXTERNAL_STORAGE` ≤ API 32 | none (PHPicker) | On *Choose from gallery*, Android ≤ 12 only |
| Microphone | **blocked** | not declared | never - no video is recorded |
| Network | `INTERNET` | ATS default (HTTPS) | always |

Outcomes the app handles, each with its own message (`src/services/imagePicker.ts`,
`src/hooks/useImageSelection.ts`, `src/screens/HomeScreen.tsx`):

- granted → the camera or picker opens;
- denied, may ask again → "Camera access needed";
- denied, will not ask again (`canAskAgain` false) → "…turned off" with an
  *Open Settings* button;
- cancelled → nothing happens, no message;
- no camera (no activity can take a photo; a simulator) → "Camera not
  available", pointing at the gallery;
- picked file rejected before upload → the reason: unsupported format (only
  JPEG, PNG, WebP), too large (over 10 MB), empty, too small (under 32 px).

The camera is opened with `exif: false` and JPEG quality 0.85; the photograph
is not written to the user's library by the app. EXIF stripping is not
guaranteed for a photograph chosen from the gallery, which is uploaded as it
is.

## Authentication - read before demoing

The app sends **no credentials**. It works because the deployed backend has
`DEMO_PUBLIC_ANALYSIS_API=True`, which opens the six analysis operations to
anonymous callers ([api.md → Permissions on the six analysis
endpoints](api.md#permissions-on-the-six-analysis-endpoints),
[deployment.md → Demonstration mode](deployment.md#demonstration-mode)).
Verified at the time of writing: `GET /api/v1/compliance/applicability-conditions/`
on the production host returns 200 without a session.

That is a controlled arrangement for the SIH demonstration and **not the
final security architecture**. The backend defaults the switch to off, the
throttle (30 requests/minute for anonymous callers) still applies, every upload
still goes through the validators, and anonymous results are a shared pool
visible to anyone using the same deployment. When the switch is off the app
receives 401/403 and says that sign-in is required and not yet supported.

Nothing in this branch changes the backend's permissions, and nothing should
be relaxed there to make the app easier. When a token or session scheme is
adopted, `src/api/client.ts` has one `headers` seam to attach it, and the
web client's CSRF handling shows the shape.

## Error handling

Every failure passes through `describeError` in `src/utils/errors.ts` and
becomes a title, a message and whether a retry is offered. The words come
from that file, except where the API documents the backend's own message as
safe to show (a validation message about the photo). Nothing from a
non-envelope body - an HTML 502 page, a proxy's 413 - reaches the screen.

| Situation | Shown |
|---|---|
| No network, DNS failure, connection refused | "Unable to connect to the analysis server. Check your internet connection and try again." + *Try again* |
| Timeout (90 s for the upload, 15 s otherwise) | "The server took too long" + *Try again* |
| 400 validation | "The photo was not accepted" + the backend's reason (e.g. "The file could not be read as an image.") |
| 401 / 403 | Sign-in required / not allowed on this server |
| 404 | Not found (service address, or a result that is gone) |
| 413 | Photo too large |
| 429 | "Too many requests… wait about N seconds" from `retry_after_seconds` + *Try again* |
| 5xx | "The analysis server had a problem" + *Try again* |
| 2xx that is not JSON, or not a result | "Unexpected response" + *Try again* |
| OCR read nothing usable | The result still arrives (201, `review_required`); the result screen warns that a missing declaration says nothing about the package |
| Extraction failed inside the server | Same: a stored run with `status: failed` and a 201, shown as a result needing review |

Technical detail (`code`, HTTP status, message - never a body, header or
token) goes to `console.warn` in development builds only.

## Accessibility and layout

- Every control is a `Pressable` with `accessibilityRole="button"`, a label, a
  hint where the label is not enough, and `accessibilityState` for disabled
  and busy. Minimum height 48 px, full width.
- Status is never colour alone: each tone carries a symbol (✓ ! ✕ ? –) inside
  the badge text, and finding groups and step states are described in words.
- Error callouts have `accessibilityRole="alert"` and an assertive live region.
- Text uses the platform font at 16 px body / 14 px secondary, with line
  heights set; long values wrap, nothing is truncated with ellipses.
- Layout is a single column with a 16 px gutter at every width, no fixed
  widths, the preview constrained by `aspectRatio` and `maxHeight`, and
  safe-area insets applied to the sides and bottom (`react-native-safe-area-context`).
  Checked conceptually at 320 px (small Android), 412 px (large Android) and
  390 px (iPhone); not yet checked on hardware.

## Tests

```bash
cd mobile
npm test              # jest (jest-expo preset)
npm run typecheck     # tsc --noEmit
npm run lint          # eslint (eslint-config-expo)
```

What is covered, and where:

| Area | File |
|---|---|
| API base URL resolution, trailing slashes, production refusal | `src/config/env.test.ts` |
| HTTP client: URL joining, JSON/multipart bodies, no credentials, error envelope for 400/401/403/404/413/429/500, non-JSON bodies, network vs timeout, abort | `src/api/client.test.ts` |
| Upload construction (`image` part with name/type, `view_type`), extraction mapping, classification present / null / absent / malformed / "unknown" | `src/api/extraction.test.ts` |
| Compliance request body (category sent only when given), result mapping, findings absent vs empty, malformed bodies rejected | `src/api/compliance.test.ts` |
| Format detection, size/empty/too-small rejection, filename normalisation | `src/services/imageValidation.test.ts` |
| Camera and library permission grant / denial / permanent denial, cancellation, unavailable camera, picker errors, platform differences | `src/services/imagePicker.test.ts` |
| The two-step flow over a stubbed `fetch`: phases, network failure, HTTP failure, retry without re-upload, human-confirmed re-check, duplicate evaluate dropped | `src/hooks/useLabelAnalysis.test.tsx` |
| User-facing messages per failure | `src/utils/errors.test.ts` |
| Tones for known and unknown statuses, grouping order | `src/utils/status.test.ts` |
| Home: both pickers, every outcome, Settings deep link | `src/screens/HomeScreen.test.tsx` |
| Preview: image, product type, use / retake | `src/screens/PreviewScreen.test.tsx` |
| Analysis: loading steps, each error, retry, completion | `src/screens/AnalysisScreen.test.tsx` |
| Result: each verdict, findings by status, extracted fields, classification present / absent / unknown, re-check confirmation, no percentage, technical details | `src/screens/ResultScreen.test.tsx` |
| The whole flow through the real navigator: Home → Preview → Analysis → Result, offline stop, retry, start over | `src/navigation/RootNavigator.test.tsx` |

Only two things are replaced in tests: `expo-image-picker` (a native module)
and `fetch`. Fixtures are in the wire shape the backend sends
(`tests/fixtures.ts`), so the mapping layer is always under test.

## Gaps and limitations

Things the app needs and the API does not yet offer, recorded rather than
faked:

- **No endpoint lists product categories.** The preview screen therefore takes
  a free-text code, as the web client does. A picker for the future
  human-confirmation step needs `GET /api/v1/products/categories/` (or
  similar) - documented as planned in api.md.
- **No endpoint serves the stored image back**, so a result reopened later
  cannot show its photograph. The app keeps the local file for the current
  session only.
- **The deployed backend runs `tesseract` 0.3.0**, so `product_classification`
  is `null` there. The card and the re-check button appear only once the
  backend is redeployed at 0.4.0 or later.
- **No applicability declarations UI.** The API accepts `applicability_declarations`
  and the client sends them if given (`evaluateExtractionRun`), but no screen
  collects them yet; the clauses that turn on an undeclared fact reach *Needs
  review*, which is the correct result.
- **No history or permalink screens** (`GET /api/v1/compliance/`). The client
  function for a stored result exists (`fetchComplianceResult`); no screen uses
  it.
- **No sign-in.** See *Authentication*.
- **Not run on a device or simulator in this branch**, and iOS not built.
- No offline analysis, by design: the engine and OCR are server-side, and the
  app says so instead of pretending.
- No image preprocessing on the phone (deskew, contrast, crop). That belongs
  to the OCR workstream on the server.

## What comes next

Before or while the automatic classification → applicability workflow is built:

1. **Deploy the classifier** (`tesseract` 0.4.0) so production returns
   `product_classification`; the app already renders it.
2. **Add a categories endpoint** so the confirmation step can offer a list
   rather than a text field, and so the classifier's suggestion can be shown
   with the backend's own category name.
3. **Decide the confidence policy on the server, not in the app.** When the
   backend gains a "confirm this category" contract (a suggested category plus
   a `needs_confirmation` flag, or a threshold it publishes), the app's
   `ClassificationCard` becomes that confirmation step and
   `evaluate({ categoryCode })` is already the call. The app must not pick a
   threshold of its own.
4. **Authentication.** Replace the demonstration switch with real credentials;
   `src/api/client.ts` has the seam.
5. **Run on hardware**, both platforms, before any claim beyond "foundation".
