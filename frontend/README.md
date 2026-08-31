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

## Screens

| Route | What it is |
|---|---|
| `/` | Backend health, and the honesty notices about the engine and the rule set. |
| `/inspections` | The stored assessments, newest first. Each row opens its result. |
| `/scan` | Upload a label, watch it be read, read the verdict. |
| `/result/:checkId` | A stored result, fetched by id. What a shared link opens. |

`Inspections` and `New scan` are separate navigation items because they are
separate screens: one lists what has been assessed, the other adds to it. The
breadcrumbs on the scan and result screens have always named an *Inspections*
parent; `/inspections` is the route that makes that name lead somewhere.

## The flow

```
file  ->  POST /api/v1/extraction/  ->  ExtractionRun id
                                    ->  POST /api/v1/compliance/  ->  verdict
```

Two steps rather than the one-shot `POST /api/v1/images/`, because the screen
shows the reading next to the verdict and a reviewer has to be able to check a
finding against the text it came from. `useLabelAnalysis` owns the run id and
guarantees three things: the photograph is uploaded once, one compliance request
is made per evaluation, and a failed verdict leaves the reading on screen with a
retry that does not re-upload.

`analyseImage` (the one-shot path) is still exported and tested — a caller that
wants only a verdict should not have to make two requests.

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
back, so the picture under the bounding boxes is the `File` the user selected,
held as an object URL. Boxes are positioned as percentages of
`image.width` × `image.height`, which is the coordinate space `bounding_box` is
expressed in, so they stay aligned at any display size with no measurement in
JavaScript.

A finding with no box gets no marker. A box that is not four finite positive
numbers gets no marker. Coordinates are never inferred — a drawn rectangle is a
claim about where on the package something was read, and a guessed one would be
a false claim. On `/result/:checkId` there is no local file, and the panel says
the photograph is unavailable rather than showing an empty frame.

## Backward compatibility

`findings[]` was added to the compliance response after the first version of
this UI. Against a server that does not send the key at all, `findingsReported`
is false: the findings section says the per-rule trace is unavailable, and
`violations[]` renders exactly as it always did. That is deliberately different
from `findings: []`, which means no rule was examined — the two get different
sentences, because "this server does not report per-rule outcomes" is not "we
checked and found nothing".
