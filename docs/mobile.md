# Mobile client (`mobile/`)

A React Native app, built with Expo, that photographs a package label and
sends it to the same Django REST API the web frontend uses. It is a second
client of the compliance engine, not a second engine: nothing legal, nothing
OCR and nothing learned runs on the phone.

```
Phone                                   Backend (one container, docs/deployment.md)
─────                                   ────────────────────────────────────────────
camera / gallery (1–6 photos)
  → validate (format, size) each        POST /api/v1/extraction/
  → upload them in ONE request ────────►  validate ─ store ─ OCR ─ field extraction
    (the `image` part, repeated)           ─ normalise ─ product classification
                                           …once per photo, into ONE run
  ◄──────────────────────────────────── 201 ExtractionRun (+ images[], product_classification)
  → evaluate the run id  ──────────────► POST /api/v1/compliance/
                                           applicability ─ deterministic rule engine
  ◄──────────────────────────────────── 201 ComplianceCheck (one verdict, findings, reading)
result screen: "3 images checked", one verdict, summary, findings, what was read
```

**One inspection, however many photographs.** A packaged commodity declares
different things on different panels, so the app gathers a *set* of photographs
and sends them together. They become one `ExtractionRun` and one
`ComplianceCheck` - never one inspection per photograph, which would report the
front panel as failing to declare a net quantity printed on the back. See
[Several photographs, one inspection](api.md#several-photographs-one-inspection)
for the request shape and the guarantees around it.

This document covers what the app is, how to run it, and what it does not do.
The API it consumes is documented in [api.md](api.md); the reasons the engine
is server-side are in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Status

**Foundation.** The flow above works end to end against a running backend,
with tests for every layer. It has been verified as follows, and no further
than this:

| Check | Evidence |
|---|---|
| Unit, hook, screen and navigation tests | `npm test` in `mobile/`: 19 suites, 280 tests |
| Type check and lint | `npm run typecheck`, `npm run lint` |
| Expo project configuration | `npx expo-doctor`: 21/21 checks |
| API contract | The mappers were run over real responses from a local backend (`tesseract` 0.4.0) - extraction, compliance with and without a category, and the 400/404 error envelopes |
| Android native project | `npx expo prebuild --platform android` generates it; the merged manifest carries `INTERNET` and `CAMERA` (from expo-image-picker), storage permissions only up to API 32, and no `RECORD_AUDIO`; cleartext HTTP is enabled in the **debug** manifest only. `gradlew assembleDebug` produced `app-debug.apk` on Windows (JDK 21, SDK 36, NDK 27; 35 minutes cold). Not installed anywhere - no device or emulator was attached |
| iOS | Configured (`bundleIdentifier`, usage strings) and type-checked. **Not built and not run**: this needs a Mac with Xcode, which was not available |
| On a device | An Android phone in Expo Go reported `[api] target http://192.168.29.172:8000/api/v1/ (https: false; development-default)` and `network_error (HTTP 0)` on upload while the same phone could open the Railway `health/` URL in Chrome. Two causes were found and fixed - see *Two things that looked like "no network"*. The fixes are verified by tests that run Expo's real env loader and multipart encoder; the re-run on the phone after the fix is the developer's to record |

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
    ├── api/                client.ts (the one HTTP client), extraction.ts, compliance.ts,
    │                       rules.ts (the server's rule inventory, every page)
    ├── config/env.ts       the ONLY reader of process.env; API base URL; upload limit
    ├── types/api.ts        the API contract: wire shapes and their camelCase mappings
    ├── services/           imagePicker.ts (camera/library + permissions), imageValidation.ts
    ├── hooks/              useLabelAnalysis.ts (the two-step flow), useInspectionImages.ts
    │                       (the set being composed), useImageSelection.ts, AnalysisContext.tsx,
    │                       useRuleInventory.ts (the Rules screen's request)
    ├── navigation/         RootNavigator.tsx, types.ts
    ├── screens/            HomeScreen, ScanScreen, AnalysisScreen, ResultScreen
    ├── components/         Button, StatusBadge, Card, Callout, ProgressSteps, FindingCard,
    │                       ImageTray, ClassificationCard, ExtractedFieldsList, KeyValue,
    │                       PhotoTips, ScanPreview, Screen
    ├── utils/              errors.ts (user-facing messages), status.ts (tones), format.ts,
    │                       images.ts (naming the photo a piece of evidence came from)
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
  run id, so the photographs are uploaded once and a re-check never re-uploads.
  It also keeps the set that was submitted, so a retry after a failed upload
  resends exactly those photographs.
- `src/hooks/useInspectionImages.ts` owns the set being gathered: add, remove,
  de-duplicate by uri, and stop at the backend's maximum. It lives in
  `AnalysisProvider` rather than in a screen so the photographs survive
  navigating to the progress screen and back after a failure - losing four
  panels to a dropped connection is the worst thing this feature could do to
  someone.
- `src/screens/` render what came back. **No screen computes a verdict, a
  score, a count or an outcome.** The counts shown are the backend's `rules_*`
  fields; the tones in `utils/status.ts` are looked up from a value the backend
  returned, and an unrecognised value renders neutral, never green. The one
  figure made on the phone is the Rules screen's active/inactive split: a tally,
  in `src/api/rules.ts`, of the `is_active` flags on the complete list the
  server returned - not a judgement about which rules apply to anything.

## Screens

```
Home ─────────► Scan ──────────────► Analysis ─────────► Result
Take photo      [1][2][3][+ Add]     Reading 3 photos    "3 images checked"
Choose photos   remove any           Checking the        one verdict + summary
tips            Check package · 3    requirements        findings by status
                Product type         error + retry       what was read (· Image n)
                (optional)                               photos used
                                                         classification (suggestion)
                                                         technical details
```

- **Home.** Two buttons and five lines of advice (flat label, sharp text, no
  glare, whole panel, hold steady). Either button starts a **new** inspection -
  the previous result and any photographs left over from it are cleared - and
  the gallery button accepts several photographs at once. A refused permission
  shows a message; when the system will no longer ask, an *Open Settings*
  button.
- **Scan.** Where the set is composed, and the screen the feature is built
  around.
  - The first photograph is shown large, so the user can see whether the label
    is actually readable; a row of 96 px thumbnails could not settle that.
  - Below it, every photograph as a numbered thumbnail with its own remove
    control, and a *+ Add* tile at the end of the row. The number is the
    position the backend will use, so "Image 2" here and "Evidence · Image 2"
    on the result screen are the same photograph.
  - The primary action states the count - *Check package · 3 photos* - because
    it is the last thing read before the tap, and it is where an unintended
    submission gets caught.
  - With no photographs the action is disabled and the screen says at least one
    is needed, rather than leaving a dead button.
  - An optional product category code. It is a text field rather than a list
    because no endpoint lists categories (the web client's field is a text
    input for the same reason - see *Gaps* below). Blank is supported: the
    result then says the product type was not known.
- **Analysis.** "Analysing label…" with **two** steps, which are the two real
  requests - "Reading 3 photos" and "Checking the requirements". The first
  covers upload, OCR and field extraction for the whole set, which happen
  inside one request on the server and cannot be told apart from the client;
  the second is the rule engine. There is deliberately no step per photograph
  and no five-stage list: the backend performs two operations this client can
  observe and reports nothing from inside either, so a longer list would look
  more informative and be invented. Nothing is a timer or a percentage. On
  failure: a plain message, *Try again* - which resends the same set, without
  asking the user to choose their photographs again - and *Start a new
  inspection*, which discards them.
- **Result.** One verdict for the set, with "3 images checked — one package,
  one result" beside it. The verdict badge uses the backend's `result_display`
  and the summary is always beside it. Findings are grouped Failed → Needs
  review → Passed → Not applicable, each card carrying the rule's title,
  clause, the backend's message, the requirement in the rule's words, and the
  evidence excerpt with the OCR confidence labelled as *reading* confidence.
  The extracted fields are their own card. A *Photos used* card lists each
  photograph and how it fared on its own, so a submitter can see that image 2
  was unreadable while the package was still judged. Technical details (ids,
  engine versions, timings, recognised text) are behind a toggle.
- **Rules.** The rule inventory the analysis server reports,
  `GET /api/v1/rules/` (docs/api.md), and nothing else. **The backend is the
  source of truth**; the screen is informational and evaluates nothing - no
  validator, threshold or applicability exists in this app, and the endpoint
  sends none.
  - Shows the server's `count` as *Total*, the active and inactive tallies of
    its `is_active` flags, and every rule in the server's order: code, `Rule`
    and the linked clause (the label a finding card uses), title, and the legal
    reference verbatim. An inactive rule is listed and marked *Not evaluated*;
    a rule the server reports as unverified is marked *Not yet verified*. No
    clause is shown when the server links none - one is never read out of the
    reference text - and effective dates are not used to decide anything.
  - Reads every page. `src/api/rules.ts` asks for the largest page the backend
    serves (100) and follows `next` to the end, so the list is always the whole
    inventory and nothing assumes how many rules there are. A response that is
    malformed, has a malformed rule, or whose pages do not add up to its
    `count` is refused as a whole, not shown in part.
  - *Loading*: a spinner naming the server; no counts and no list. *Error*:
    "The server's current rule list could not be loaded", the reason, and
    *Try again* when a retry could help - never a list. A 401/403 (the
    demonstration switch is off) and a 404 (a backend from before the
    endpoint) are named as such, and a timeout is not blamed on a photograph
    as the shared analysis message does. *Empty*: "The server reports that it has no
    compliance rules loaded."
  - **No fallback.** `src/data/lmpcRules.ts`, the generated mirror of
    `rules/definitions/` the screen used to show, is no longer imported by the
    app; it is kept, generated and drift-tested, as a repository mirror only.
    It is not shown while loading or on failure, because it says what the
    repository ships rather than what the server has loaded, and on this
    screen it would be taken for the server's list. The Settings row that
    opens this screen no longer quotes its count for the same reason.

### Which photograph a piece of evidence came from

When an inspection carries more than one photograph, a declaration is labelled
with the panel it was read from - *Net quantity · Image 1* - and a finding's
evidence block with the panel behind it - *What was read · Image 2*.

**Only where the backend actually attributed it.** `utils/images.ts` produces a
label from `image_id` and returns `null` in every other case, and the interface
then says nothing about images:

- the backend recorded no source (an older server, or an image row since
  deleted) - `null` there means "not stated", never "no photograph";
- the finding became no violation, so there is no evidence row to carry an
  image - a passing finding is not attributed to a panel;
- a finding of **absence**, where the backend falls back to the primary
  photograph because the declaration was absent from the whole set. The app
  must never turn that into "image 1 is missing the net quantity", which is a
  claim about where a declaration should appear on a package;
- there is only one photograph, where "Image 1" is noise rather than
  information.

A declaration may legitimately appear **twice** in *What was read* when it is
printed on two photographed panels. Both are shown, each against its own
photograph, because both are real readings - deciding which panel of a package
to believe is not the phone's job. Which one the rule engine judged against is
the backend's answer, on the finding.

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

Out of the box this talks to the **deployed Railway backend** - no local
Django needed - because the committed `mobile/.env.development` says so. The
home screen shows the host in use ("Analysis server connected · …railway.app")
and the Metro console logs it once as `[api] target …`. Look there first when
anything fails.

To use a backend on **your own machine** instead, create the git-ignored
`mobile/.env.local` (copy `.env.example`), set the address, and restart with
`npx expo start --clear`. The backend must be reachable *from the phone*:

```bash
# mobile/.env.local
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.20:8000/api/v1/   # your laptop's LAN address

# root .env
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.20        # the same address
DEMO_PUBLIC_ANALYSIS_API=True                                 # see "Authentication"

python backend/manage.py runserver 0.0.0.0:8000                # all interfaces
```

and your firewall must allow inbound connections to port 8000 (Windows
prompts for this the first time Python listens; if it was dismissed, the phone
gets no answer and the app reports the server unreachable at that host).

### Configuration

One variable controls where every request goes, and it is read in exactly one
file, `src/config/env.ts`:

| Variable | Meaning |
|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | Base URL of the API **including `/api/v1/` and a trailing slash** |

Three targets, each selected by a file - never by editing source:

| Target | File | Committed? | Used by |
|---|---|---|---|
| **Local backend** on your machine | `mobile/.env.local` | no (git-ignored; copy `.env.example`) | `npx expo start` |
| **Railway, development / demo** | `mobile/.env.development` | yes | `npx expo start` - the default |
| **Railway, production** | `mobile/.env.production` | yes | `npx expo export`, EAS builds |

**Why `.env.production` is not the development configuration.** Expo picks
env files by `NODE_ENV`, which `expo start` sets to `development` and `expo
export`/EAS set to `production` (`@expo/cli` `start/index.js`). In development
the files read are, highest priority first:

```
.env.development.local  >  .env.local  >  .env.development  >  .env
```

and in production `.env.production.local > .env.local > .env.production >
.env`. A higher-priority file overwrites a lower one (even with an empty
value), and a variable already set in the shell wins over every file
(`@expo/env`). So `.env.production` is never seen by `expo start`; before
`.env.development` existed, a development build had no address at all and
fell back to guessing - which is what the phone logged as
`development-default`.

What the app does with the value it receives (`resolveApiBaseUrl`):

1. Set and non-blank → used as given (one trailing slash enforced).
2. Blank in a **development** build → derived from the machine serving Metro,
   on port 8000: `http://<metro-host>:8000/api/v1/`. A deliberate guess for
   "Django is on the laptop I ran `expo start` on"; the home screen labels it
   *(development default)*. Reached only by setting the variable empty in
   `.env.local`.
3. Blank with no Metro host → `http://localhost:8000/api/v1/`.
4. Blank in a **production** build → the app refuses to start, as the web
   client's build refuses. `.env.production` supplies the value, so this only
   happens if it is deliberately blanked.

Switching:

```bash
# Railway (the default) - nothing to create:
npx expo start --lan --clear

# Local backend - once:
cp .env.example .env.local            # then edit the address inside
npx expo start --lan --clear

# Back to Railway - remove or rename the override:
rm .env.local && npx expo start --lan --clear

# One-off, any target, without touching files (shell wins over every file):
EXPO_PUBLIC_API_BASE_URL="https://other-host/api/v1/" npx expo start --lan --clear
```

Always `--clear` after changing an env file: values are inlined into the
bundle when Metro starts and cached. Expo prints what it loaded on startup
(`env: load .env.development`, `env: export EXPO_PUBLIC_API_BASE_URL`), and
the app logs the resolved target once in development.

Every `EXPO_PUBLIC_` value is inlined into the bundle and readable by anyone
who unpacks the app. The Railway URL is **public configuration, not a
secret** - the same address is committed in `frontend/.env.production`. **No
secret goes in any file under `mobile/`.** The upload size pre-check
(`MAX_UPLOAD_SIZE_MB`, 10) is a constant in `env.ts`, mirroring the backend's
default; the backend's own limit is the one that counts.

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
| Photo library | none on 13+ (system Photo Picker); `READ_EXTERNAL_STORAGE` ≤ API 32 | none (PHPicker) | On *Choose photos*, Android ≤ 12 only |
| Microphone | **blocked** | not declared | never - no video is recorded |
| Network | `INTERNET` | ATS default (HTTPS) | always |

Outcomes the app handles, each with its own message (`src/services/imagePicker.ts`,
`src/hooks/useImageSelection.ts`, `src/screens/ScanScreen.tsx`):

- granted → the camera or picker opens;
- denied, may ask again → "Camera access needed";
- denied, will not ask again (`canAskAgain` false) → "…turned off" with an
  *Open Settings* button;
- cancelled → nothing happens, no message;
- no camera (no activity can take a photo; a simulator) → "Camera not
  available", pointing at the gallery;
- picked file rejected before upload → the reason: unsupported format (only
  JPEG, PNG, WebP), too large (over 10 MB), empty, too small (under 32 px).
  When several were chosen and only some were rejected, **the acceptable ones
  are kept** and the message says how many of each: throwing the whole
  selection away would make the user repeat a choice that was mostly fine,
  over a file format they cannot change.

The camera is opened with `exif: false` and JPEG quality 0.85; the photograph
is not written to the user's library by the app. EXIF stripping is not
guaranteed for a photograph chosen from the gallery, which is uploaded as it
is.

### Selecting several at once

The gallery is opened with `allowsMultipleSelection` and a `selectionLimit`
set to the room the inspection has left, so the **system picker** stops the
user at the right number - a refusal while they are choosing is far better
than an error after a multi-megabyte upload. Both platforms support this
natively (iOS PHPicker, Android Photo Picker), so it needs no custom grid and
no additional permission.

**The camera stays one photograph per launch.** That is the platform's shape,
not a limitation of this app: neither system camera returns a batch. Taking
several means taking one, returning to the scan screen, and tapping *+ Add*
again - which is also the only arrangement in which the user sees each
photograph before deciding to keep it.

## Authentication - read before demoing

The app sends **no credentials**. It works because the deployed backend has
`DEMO_PUBLIC_ANALYSIS_API=True`, which opens the six analysis operations - and
the read-only rule list the Rules screen reads, `GET /api/v1/rules/` - to
anonymous callers ([api.md → Permissions on the six analysis
endpoints](api.md#permissions-on-the-six-analysis-endpoints),
[deployment.md → Demonstration mode](deployment.md#demonstration-mode)).
Verified at the time of writing: `GET /api/v1/compliance/applicability-conditions/`
on the production host returns 200 without a session, and on 2026-09-25
`GET /api/v1/rules/` did too. With the switch off, the Rules screen says the
server shows its rule list only to signed-in users.

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
| No network, DNS failure, connection refused, or a request `fetch` could not build | "Unable to connect to the analysis server. The app is configured to use *host*. Check your internet connection and that the server address is right, then try again." + *Try again*. The underlying error is logged as the `cause` in development builds |
| Timeout (90 s for the upload, **plus 60 s per photograph after the first**, 15 s otherwise) | "The server took too long" + *Try again*. The upload allowance grows with the set because the backend reads the photographs one after another inside the request; keeping the single-photo timeout would abort work proceeding normally. It is not an estimate and is never shown. Classified by the app's own abort, because `expo/fetch` reports it as `fetch failed: Fetch request has been canceled` rather than an `AbortError` |
| 400 validation | "The photo was not accepted" + the backend's reason (e.g. "The file could not be read as an image."). A set is one inspection, so one rejected photograph rejects the request; **the user's photographs are kept** and *Try again* resends the same set |
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
- **The image tray is walked in order.** The row is a list; each thumbnail is
  one element labelled with its position ("Photo 2 of 3") and the remove
  control beside it is a separate button labelled the same way ("Remove photo
  2"), so a screen-reader user never has to discover which photograph
  "remove" means by pressing it. The thumbnail's label is the position, never
  a description of the picture - the app has not looked at it and must not
  claim to know what it shows. The remove control is 28 px with a 10 px
  `hitSlop`, and the tile it sits on is 96 px, so the two cannot be confused by
  a thumb.
- The primary action carries the count in its accessible label too ("Check
  package using 3 photos"), because that is the confirmation a screen-reader
  user gets before submitting.
- The "3 photos" badge on the scanning frame is marked decorative: the
  heading above it already says how many photographs are being checked, and
  hearing the number twice is worse than once.
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
| HTTP client: URL joining, JSON/multipart bodies, no credentials, error envelope for 400/401/403/404/413/429/500, non-JSON bodies, network vs timeout (including `expo/fetch`'s cancellation shape), abort, the `cause` carried for logs | `src/api/client.test.ts` |
| Upload construction (`image` part with name/type/`bytes()`, `view_type`), extraction mapping, the image set and each reading's source photograph, classification present / null / absent / malformed / "unknown" | `src/api/extraction.test.ts` |
| The upload part run through **Expo's real multipart encoder** (`expo/fetch`): encoded with the validated filename, type and the file's bytes; the legacy `{uri}` part rejected | `src/api/uploadPart.expoFetch.test.ts` |
| Server check: `health/` through the same client, unreachable state, re-check, dev-only target log | `src/hooks/useApiHealth.test.tsx` |
| Compliance request body (category sent only when given), result mapping, findings absent vs empty, malformed bodies rejected | `src/api/compliance.test.ts` |
| Rule inventory: the GET and nothing else, snake_case → camelCase verbatim, only the contract's fields, server order kept, `next` followed to the end (and refused off-server, looping or past the ceiling), pages that do not add up to `count` refused, every malformed page or rule refusing the whole inventory, network / 403 / 500 | `src/api/rules.test.ts` |
| Format detection, size/empty/too-small rejection, filename normalisation | `src/services/imageValidation.test.ts` |
| Camera and library permission grant / denial / permanent denial, cancellation, unavailable camera, picker errors, platform differences, multiple selection and its limit | `src/services/imagePicker.test.ts` |
| The two-step flow over a stubbed `fetch`: phases, network failure, HTTP failure, retry without re-upload, human-confirmed re-check, duplicate evaluate dropped | `src/hooks/useLabelAnalysis.test.tsx` |
| The set being composed: order kept, duplicates refused, the maximum enforced, partial acceptance, removal and its effect on the room left | `src/hooks/useInspectionImages.test.tsx` |
| User-facing messages per failure | `src/utils/errors.test.ts` |
| Tones for known and unknown statuses, grouping order | `src/utils/status.test.ts` |
| Naming a photograph, and the four cases where nothing is named | `src/utils/images.test.ts` |
| Home: server status with the host it used, both pickers, seeding the set (one photo and several), every outcome, Settings deep link | `src/screens/HomeScreen.test.tsx` |
| Scan: thumbnails and their labels, the count on the action, empty state and disabled submission, adding from camera and gallery, the picker limit, removal, duplicate and full refusals, permission denials | `src/screens/ScanScreen.test.tsx` |
| Analysis: loading steps, the set-aware first step, each error, retry, completion | `src/screens/AnalysisScreen.test.tsx` |
| Result: each verdict, findings by status, extracted fields, "N images checked", per-declaration and per-finding image attribution (and where none is claimed), per-photo outcomes, classification present / absent / unknown, re-check confirmation, no percentage, technical details | `src/screens/ResultScreen.test.tsx` |
| Rules: loading with no list, the server's rules and counts, inactive and unverified marked, server order, server data never the bundled mirror's (which the test file refuses to load), no clause invented, active flag shown as sent whatever the dates, empty, error with retry, malformed, 403 and 404 | `src/screens/RulesScreen.test.tsx` |
| The scanning frame: reduced motion honoured, the photo count, no progress claimed | `src/components/ScanPreview.test.tsx` |
| The whole flow through the real navigator: Home → Scan → Analysis → Result, three photos as **one** request with three `image` parts, adding and removing before submission, offline stop, retry that resends the same set, start over, a Rules visit mid-inspection that makes only its own request | `src/navigation/RootNavigator.test.tsx` |

Only three things are replaced in tests: `expo-image-picker` and
`expo-file-system` (native modules) and `fetch`. Fixtures are in the wire shape the backend sends
(`tests/fixtures.ts`), so the mapping layer is always under test.

## Gaps and limitations

Things the app needs and the API does not yet offer, recorded rather than
faked:

- **No endpoint lists product categories.** The scan screen therefore takes
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
- **iOS not built**, and the post-fix run on the Android phone is not recorded here.
- No offline analysis, by design: the engine and OCR are server-side, and the
  app says so instead of pretending.
- No image preprocessing on the phone (deskew, contrast, crop). That belongs
  to the OCR workstream on the server.

Limitations specific to the image set:

- **The app does not ask which panel is which.** Every photograph is uploaded
  with `view_type: unspecified`. The API accepts a per-photograph view type and
  the client sends one when given, but no screen collects it, and the order a
  person happens to photograph a package in is not evidence that the second
  shot is the back. Recording a guess would put a claim in the database that
  nobody made.
- **`ProductImage.view_type` changes nothing downstream even when stated.**
  Neither the compliance engine nor `labelextract` reads it today, so a
  declaration absent from a front-panel photograph is still reported FAILED
  rather than undeterminable. That gap is the backend's (it is recorded on the
  model and in PROJECT_STATUS.md), and it is the reason the app tells the
  submitter to photograph every panel carrying a declaration rather than
  relying on labelling one.
- **Six photographs per inspection**, mirroring the backend's
  `MAX_IMAGES_PER_INSPECTION`. Each one costs a full OCR pass inside the same
  synchronous request, so the set is bounded until extraction moves behind a
  queue.
- **The camera returns one photograph per launch** on both platforms; only the
  gallery offers a multiple selection. See *Permissions*.
- **A retry resends the photographs**, because the upload is one request and a
  partial one cannot be resumed. On a slow connection a large set is uploaded
  again in full.
- **No image is served back**, so the per-photograph outcomes on the result
  screen are named ("Image 2") rather than shown as thumbnails once the local
  files are gone.

## Two things that looked like "no network"

Recorded because both produced the same line on an Android phone in Expo Go -
`[extraction] network_error (HTTP 0): Unable to connect...` - while the same
phone could open the Railway `health/` URL in Chrome.

1. **The development build was talking to the laptop, not to Railway.** The
   device logged `[api] target http://192.168.29.172:8000/api/v1/ (https:
   false; development-default)`. `expo start` never reads `.env.production`,
   and no development env file existed, so the app derived the address from
   the Metro host. Nothing was listening there (and Windows Firewall had no
   inbound rule for Python), so every request hung until the client's timeout
   - which `expo/fetch` reports as `fetch failed: Fetch request has been
   canceled`. Fixed by committing `mobile/.env.development` (Railway) with
   `.env.local` as the local override, by showing the host on the home screen
   and in the offline message, and by classifying the app's own abort as a
   timeout whatever `fetch` calls it. See *Configuration*.
2. **The multipart body was one Expo's `fetch` cannot encode.** Expo SDK 57
   replaces the global `fetch` with `expo/fetch` on native
   (`expo/src/winter/runtime.native.ts`). Its multipart encoder does not read
   React Native's legacy `{ uri, name, type }` file part - it throws
   `Unsupported FormDataPart implementation` *before any request is made*,
   and the client could only report that as a network failure. This would
   have failed the upload even with the right address. The part is now a
   File-like object (`name`, `type`, and `bytes()` from `expo-file-system`'s
   `File`), which `expo/fetch` encodes with a boundary it generates itself;
   `uri` is kept so React Native's own fetch (`EXPO_PUBLIC_USE_RN_FETCH=1`)
   still works. `src/api/uploadPart.expoFetch.test.ts` runs the part through
   Expo's actual encoder. The `cause` of a status-0 failure is now carried on
   `ApiError` and logged in development, so this class of problem names itself.

Neither involved the backend, CORS, TLS or Railway, and nothing there changed.

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
