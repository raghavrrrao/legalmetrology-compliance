# Frontend

React 19 + Vite 7, plain CSS, Vitest + Testing Library. No state library and no
UI kit — see [ARCHITECTURE.md](../ARCHITECTURE.md) for why neither is needed
yet.

```bash
npm install
cp .env.example .env      # PowerShell: Copy-Item .env.example .env
npm run dev               # http://localhost:5173
npm test                  # vitest run
npm run lint
npm run build
```

The backend must be running and reachable at `VITE_API_BASE_URL`. The analysis
endpoints require an authenticated user unless `DEMO_PUBLIC_ANALYSIS_API` is set
in the backend environment; without either, the scan screen renders a 403 that
says so.

## The API URL

`VITE_API_BASE_URL` is the only place the backend address is configured.
`src/config/env.js` reads it once and `services/apiClient.js` resolves every
path against it; nothing else touches `import.meta.env`. The value **includes**
`/api/v1/` and a trailing slash, because services ask for `health/` and
`compliance/` relative to it.

| Command | File Vite loads | Value |
|---|---|---|
| `npm run dev` | `.env` (your copy of `.env.example`) | `http://localhost:8000/api/v1/` |
| `npm run build` | `.env.production` (committed) | `https://legalmetrology-compliance-production.up.railway.app/api/v1/` |

It is a **build-time** variable: it is compiled into the bundle, so changing it
means rebuilding and redeploying, not editing a setting on whatever hosts
`dist/`. A shell variable overrides both files
(`VITE_API_BASE_URL="https://…/api/v1/" npm run build`).

A build with no value **fails** — in `vite.config.js`, and again in
`src/config/env.js` — rather than quietly defaulting to localhost, which in a
deployed page means asking each visitor's own computer for the API.

Pointing a local `npm run dev` at the deployed API works, but the backend must
list `http://localhost:5173` in `CORS_ALLOWED_ORIGINS` or the browser blocks
every response. See [docs/deployment.md](../docs/deployment.md).

## Screens

| Route | What it is |
|---|---|
| `/` | Backend health, and the honesty notices about the engine and the rule set. |
| `/inspections` | The stored assessments, newest first. Each row opens its result. |
| `/scan` | Upload the photos of a package, watch them be read, read the verdict. |
| `/result/:checkId` | A stored result, fetched by id. What a shared link opens. |

`Inspections` and `New scan` are separate navigation items because they are
separate screens: one lists what has been assessed, the other adds to it. The
breadcrumbs on the scan and result screens have always named an *Inspections*
parent; `/inspections` is the route that makes that name lead somewhere.

## The flow

```
files  ->  POST /api/v1/extraction/  ->  ExtractionRun id
   (repeated `image` parts)          ->  POST /api/v1/compliance/  ->  verdict
```

Two steps rather than the one-shot `POST /api/v1/images/`, because the screen
shows the reading next to the verdict and a reviewer has to be able to check a
finding against the text it came from. `useLabelAnalysis` owns the run id and
guarantees three things: the photographs are uploaded once, one compliance
request is made per evaluation, and a failed verdict leaves the reading on
screen with a retry that does not re-upload.

`analyseImage` (the one-shot path) is still exported and tested — a caller that
wants only a verdict should not have to make two requests. It is deliberately
single-photograph: nothing calls it, and an untested second way to build the
same multipart body is worth less than none.

## One inspection, several photos

A packaged commodity declares different things on different panels — the net
quantity on the back, the price on a side, a batch number in small print — so
`/scan` gathers a **set** of up to six photographs and sends them in **one**
request, by repeating the `image` part:

```
FormData
  image      front.jpg
  image      back.jpg
  image      side.jpg
  view_type  unspecified      ← positional, one per image part
  view_type  back
  view_type  unspecified
```

They become one `ExtractionRun` and one `ComplianceCheck`. Never one inspection
per photograph, which would report the front panel as failing to declare a net
quantity that is printed on the back — see
[docs/api.md → Several photographs, one inspection](../docs/api.md#several-photographs-one-inspection)
for the backend half.

`useSelectedImages` owns the set: it holds the files, creates and revokes an
object URL per thumbnail, and decides what may join. Its rules, in the order it
applies them:

| Refusal | Why, and what the user is told |
|---|---|
| Unsupported type | Checked first, because an HEIC is not "the seventh photo" and telling somebody to remove one to make room for it ends in the same refusal. The file is named. |
| Empty file | A zero-byte file is something the browser genuinely knows about. |
| Duplicate | Identity is name + size + last-modified — two `File` objects from separate picks are never `===`. A duplicate would have its declarations read and counted twice. |
| Over six | `MAX_INSPECTION_IMAGES`, mirroring `backend/apps/images/constants.py`. Nothing is silently discarded: what did not fit is named, and the user can remove one and add another. |

**Size is deliberately not checked here.** The limit is a backend environment
variable that is not exposed to the client, and refusing a file against a number
invented in the browser would reject uploads the server would have accepted. An
oversized file is rejected by the API, whose message names the real limit, and
the rest of the selection survives so the user can drop that one photograph and
submit the others.

**A failed upload keeps the photographs.** The set lives in the page, not inside
`useLabelAnalysis`, so an error returns the user to the form with their
selection intact and the same button resends it. Losing six photographs to a
dropped connection is the worst thing this screen could do to somebody.

**Which panel each photo shows is stated per photo**, on the thumbnail, because
the API reads `view_type` positionally. That control used to be a single select
in *Package details*, which was unambiguous only while an inspection could hold
one photograph — one value for a set of six would have recorded a claim about
five of them that nobody made. The sentence it carried moved with it: a
declaration that is not in the photograph has not been shown to be missing from
the package.

Accessibility: every remove control is named for its photograph
(`Remove image 2`), every panel select is named for its photograph, and the
add-photos control is a `<label>` for the real file input — so it is reachable
by keyboard and drag-and-drop is never the only way in. The input keeps exactly
one accessible name at any moment, which is why the add tile stays rendered
(dimmed, reading *All 6 added*) when the set is full rather than disappearing
and leaving the input nameless.

## The history

```
GET /api/v1/compliance/  ->  { count, next, previous, results }  ->  /inspections
                                                    row id       ->  /result/<uuid>
```

`fetchComplianceHistory` in `services/complianceService.js` is the only caller,
and `useComplianceHistory` holds one page of it — there is no store, because
nothing outside the Inspections screen reads it.

**Pages are moved through by the API's own `next` / `previous` URLs**, held in
the hook and passed back to the service unchanged. No `?page=n` is built in the
browser: the page size is the server's to choose, and a client that
reconstructed the sequence would walk a different one the moment it changed. The
controls are disabled at the ends rather than hidden, and the total shown is the
endpoint's `count` — omitted entirely, never estimated from the page length,
if a response carries none.

**No filter, no sort control, no search box.** The endpoint offers none of them,
and a control that appeared to narrow a list it cannot narrow would misrepresent
what the user is looking at.

A history row is not a thin compliance result and is not modelled as one: the
list endpoint returns the verdict, the timestamps and two counts, and nothing
else. The findings, the violations, the evidence and the reading are on
`/result/<uuid>`, which the row links to.

> **The history is not scoped to the viewer.** Every caller the backend lets
> through sees every stored check — a documented backend limitation (see
> [docs/api.md](../docs/api.md)). The frontend does **not** filter rows to
> conceal it: filtering in a browser is not authorisation, and hiding the
> records would hide the limitation without fixing it.

## Rules this code is held to

**No compliance logic in the browser.** No rule, no threshold, no legal
requirement, and no combination of statuses into a verdict. The backend decides;
this renders what it decided. `utils/compliance.js` is the only file that maps a
status to an appearance, and its lookups are partial on purpose: a status this
build has never seen renders as *unrecognised*, not as whichever entry happened
to be the default.

**`review_required` and `inconclusive` are outcomes, not soft passes.** Each has
its own tone and its own sentence saying a person needs to look at this.

**Confidence is informational.** `extracted_confidence` is shown so a reader
knows what the reading behind a finding was worth. It changes no outcome, and
`null` renders as *not reported*, never as 0%.

**Nothing is fabricated to fill a layout.** Where the design asked for data the
API does not have, the UI shows an empty state or a different real value. The
list of those decisions is below.

**Backend text is rendered as text.** No `dangerouslySetInnerHTML` anywhere;
error `details` are stringified per field rather than interpolated as markup.

## Where the implementation departs from the Figma, and why

The three approved screens (Inspection Workspace, Compliance Assessment, Mobile
Compliance Workspace) are the visual target. Six elements in them have no
backing data, and were adapted rather than faked.

The **Inspections history has no Figma screen**. Rather than invent a second
design language for it, it is built from the tokens, cards, badges, count chips
and empty states the approved screens already use — one card per assessment at
every width, so the row reflows on a phone instead of scrolling sideways.

| Figma element | What is implemented | Why |
|---|---|---|
| `Scan Confidence: 94%` | The rule counters (passed / failed / undetermined / examined) and the engine version | No aggregate confidence exists in the API. Averaging per-field confidences would put a number on screen that nothing computed. |
| `Product Category` dropdown | A text field, validated server-side | Categories are `ProductCategory` rows and no endpoint lists them (`GET /api/v1/products/` is documented as planned). A hardcoded list would drift silently the moment one is added or deactivated. |
| `Jurisdiction & Ruleset` dropdown | A read-only row, plus the loaded rule counts from `/health/` | A client must not be able to choose which rules apply to it — a verdict you can steer by picking your own rules is worth nothing. |
| `Inspection Scope` dropdown | The panel / `view_type` select | Scope has no counterpart in the request body. `view_type` is a real field that genuinely changes how a result should be read. |
| `Findings Requirements Preview` (Product Name, Net Quantity, MRP, …) | Removed | Those are legal requirements. Listing them in JSX is hardcoding the law into the browser. What was actually required appears after evaluation, in each finding's own `requirement`, in the rule's own words. |
| `Max 25MB/file` | Accepted formats only | The size limit is a backend environment variable that is not exposed to the client. Printing a number the server does not enforce is worse than printing none; an oversized upload is rejected and its message rendered. |
| `Export Report` / `Finalize Audit` | *Copy result link* and *New scan* | Neither has an endpoint. The link is real: it opens `/result/<id>`, backed by `GET /api/v1/compliance/<uuid>/`. |

### The evidence overlay

`ProductImageSerializer` exposes no URL and no endpoint serves the stored bytes
back, so the pictures under the bounding boxes are the `File`s the user
selected, held as object URLs in submission order. Boxes are positioned as
percentages of `image.width` × `image.height`, which is the coordinate space
`bounding_box` is expressed in, so they stay aligned at any display size with no
measurement in JavaScript.

A finding with no box gets no marker. A box that is not four finite positive
numbers gets no marker. Coordinates are never inferred — a drawn rectangle is a
claim about where on the package something was read, and a guessed one would be
a false claim. On `/result/:checkId` there is no local file, and the panel says
the photographs are unavailable rather than showing an empty frame.

**With several photographs, nor is the one a box belongs to inferred.** There is
one figure per photograph, and a box is drawn only on the one the backend
attributed it to — a region measured on the back panel drawn over the front
would point a reviewer at the wrong part of the package, which is worse than
pointing at nothing because it looks authoritative. `utils/images.js`
`findingImageId` resolves that from the two places the backend actually records
it:

1. the violation the finding became — `violations[].evidence[].image_id`;
2. failing that, the reading it drew on — `extraction.fields_read[].image_id`,
   matched on `field_key`, and **only when exactly one reading matches**. A
   declaration printed on two photographed panels produces two readings with the
   same key, and the engine chose between them by a rule this layer does not
   reimplement, so nothing is named.

Where neither resolves, no photograph is named anywhere: not on the figure, not
beside the evidence excerpt, not beside the reading. That includes a finding of
**absence**, where the backend falls back to the primary photograph — the
declaration was absent from the whole set, and rendering that as "image 1 is
missing the net quantity" would be a claim about where a declaration should
appear on a package that this system has not made. With a single photograph
nothing is named either, because "Image 1" is noise rather than information.

## Backward compatibility

`images[]` and `image_id` were added to the extraction and compliance responses
alongside multi-image support. Against a server that sends neither, the client
maps the single `image` the response does carry into a set of one — never an
empty set, which would make the screen say no images were checked — and
`image_id` maps to `null`, which is rendered as no image label at all rather
than as a default to the first photograph. A one-photograph upload is
byte-for-byte the request this client has always sent.

`findings[]` was added to the compliance response after the first version of
this UI. Against a server that does not send the key at all, `findingsReported`
is false: the findings section says the per-rule trace is unavailable, and
`violations[]` renders exactly as it always did. That is deliberately different
from `findings: []`, which means no rule was examined — the two get different
sentences, because "this server does not report per-rule outcomes" is not "we
checked and found nothing".
