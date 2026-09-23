# Project status

What works today, what does not, and what the system is careful **not** to
claim. Written to be read before a demonstration, so that nothing on screen has
to be explained away afterwards.

Companion documents: [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it is built,
[`docs/api.md`](docs/api.md) for the contract, [`docs/security.md`](docs/security.md)
for the security and privacy posture, [`rules/README.md`](rules/README.md) for
what the rule set actually checks, and [`rules/SOURCES.md`](rules/SOURCES.md)
for where the law came from.

---

## The one-line version

An end-to-end pipeline — upload a label photograph, read it, check it against
**eleven** executable rules drawn from the Legal Metrology (Packaged
Commodities) Rules, 2011, and show every finding with the clause behind it and
the evidence it rests on.

**It does not automate the Rules.** Sixty-nine clause-level requirements are on
record; eleven executable rules reach eight of them, and every one of those
eleven checks *less* than its clause requires. The rest are inventoried
precisely so what the software cannot check is visible rather than absent.

---

## Component status

**Architecture:** Working as designed. Image → validation → OCR/extraction →
normalisation → applicability → deterministic rule engine → findings → verdict →
React UI. The rule engine is the only layer that reaches a legal conclusion; the
frontend renders what the API returned and decides nothing.

**Backend:** Django 5.2 + DRF, PostgreSQL, seven apps by bounded responsibility.
Six routed endpoints under `/api/v1/` (health, images, extraction, the
compliance collection, one compliance result, applicability conditions). Deny-by-default
permissions. Synchronous analysis, ~2 s median.

**Frontend:** React 19 + Vite. Scan, result, permalink and history screens
against the real API, with the applicability declaration form and the full
finding trace. No login screen (see *Known security limitations*).
**Redesigned 2026-09-23** onto an iOS 18-inspired system — near-white ground,
one restrained green accent, large radii, hairline separators, translucency on
the sticky header only — shared with the mobile client, which previously used a
blue primary. The stylesheet was three stacked layers in which 118 of 211
selectors were declared more than once; it is now one pass with every selector
declared once, and 680 lines and 7.5 kB smaller. Appearance only: no API
contract, backend behaviour or compliance logic was touched, and the four
outcomes keep their own tone, word and symbol. See
[`docs/ui/design-system.md`](docs/ui/design-system.md).

**OCR/ML:** Working with Tesseract 5 (`eng` + `osd`) through the separate
`labelextract` package, which installs and passes its whole suite with **zero**
dependencies. A placeholder engine is configurable and is flagged to the UI so
its output can never be shown as a real reading. Extraction covers 14
declarations; common/generic name and address are **not attempted**, and their
absence carries no information. The extraction and normalisation layer was
**audited and hardened on 2026-09-23** against the ten photographed packages,
and the audit's own finding is worth quoting: of 94 missed declarations the
expected value is verbatim in the recognised text in **6**, so recall on this
corpus is bounded by *recognition*, not by interpretation. What the pass fixed
was the failure that is not visible in a recall number — five committed,
unflagged, wrong readings, now three. A batch code read off a legend line, a
shelf life reported as a manufacture date and a five-bar soap pack reported as
"4 units" are all gone. A first product classifier (TF-IDF + logistic
regression, a 120 KB JSON artifact evaluated in plain Python) runs as the last
pipeline stage in `tesseract` 0.4.0 and is honestly a baseline: ten training
products, model-drafted labels, and cross-validated numbers that say it cannot
yet recognise an unfamiliar non-food product. It decides nothing. Its dataset
now carries enforced integrity checks and a human-verification ledger; the
ledger is empty, because the repository holds no further genuine product data
and none was invented to fill it. **More photographed products, and a person
verifying the labels, are the whole of what is missing** — neither is a code
change.

**Compliance engine:** Working. Eleven active deterministic rules over seven
registered check types; no LLM and no model output anywhere in the decision
path. Applicability (rules 3 and 26 scope gates, then each clause's own
conditions) is resolved *before* any rule is evaluated.

**Database:** PostgreSQL. 14 migrations, all applied, `makemigrations --check`
clean. `manage.py migrate` → `seed_categories` → `load_rules` →
`load_legal_framework` initialises a fresh database; all three loaders are
idempotent and verified so on a clean database.

**Security:** Reviewed in Step 5 — see [`docs/security.md`](docs/security.md).
No secrets in the repository. Upload validation decodes the bytes rather than
trusting the claim. Compliance results are now scoped to the caller. Throttling
30/min anonymous, 120/min authenticated. `manage.py check --deploy` reports zero
issues with `DJANGO_DEBUG=False`.

**Testing:** 934 backend, 998 ML (plus 2 recorded expected failures and 2 unexpected passes of the same parametrised classifier-robustness test), 243 frontend, 203 mobile — all passing as of 2026-09-23. The ML count includes 92 new extraction-hardening regressions, every one of whose inputs is recognised text this project actually produced rather than a drafted label. The web and mobile counts are unchanged by the 2026-09-23 interface redesign, which was verified against them rather than against new ones: the suites assert behaviour, text and semantics, so they are exactly what a restyle must not change. Nothing asserts on appearance, so a purely visual regression would not fail a test. Lint clean, production build succeeds, mobile typecheck clean, `makemigrations --check` reports no changes. Counts are stated so drift is noticeable, not as a
quality claim: a passing suite bounds what is checked, not what is correct.

**Documentation:** Checked against the code in Step 5. Where a document and the
code disagreed, the document was corrected rather than the claim softened.

**Deployment:** **Ready to deploy, not deployed.** `Dockerfile` (with the
Tesseract binary), `railway.json`, `gunicorn.conf.py` and the `deploy_setup`
initialisation command all exist and were re-verified on 2026-09-09. No Railway
project has been created from this repository and there is no URL. See
*Deployment status* below for what was checked and what was not.

---

## The pipeline, stage by stage

| Stage | State | Where |
|---|---|---|
| Upload & validation | Working. Content-type, size, decodability, decoded format and dimensions are measured from the bytes, never trusted from the request. | `apps/images/` |
| OCR | Working with Tesseract 5. Orientation is **not** detected — see *Known limitations*. | `ml/labelextract/ocr/` |
| Field extraction | Working for 14 declarations. Two — common/generic name and address — are **not attempted**. **Hardened 2026-09-23** (`rule-based-fields` 0.2.0): every quantity on a line is reported rather than the leftmost silently kept, a batch code must carry a digit, a shelf life is no longer read as a manufacture date, and the two date declarations gained unread-observation anchors. Measured on the frozen set: two fewer confident wrong readings in five (silent error rate 0.385 → 0.273), precision still 1.000, recall one cell lower because both detections removed were wrong values. See [`docs/ml/extraction-hardening.md`](docs/ml/extraction-hardening.md). | `ml/labelextract/fields/` |
| Normalisation | Working. Refuses to resolve an ambiguity: `03/04/2025` is emitted with both candidates and marked uncertain rather than guessed; `1142025` becomes no date at all and the declaration is reported unread; `Net Quantity: 5009` is not repaired into `500 g`. | `ml/labelextract/fields/normalisation.py` |
| Product classification | **Baseline.** TF-IDF + logistic regression over the recognised text (`tesseract` 0.4.0), answering `packaged-food` / `packaged-non-food` / `unknown` with a subcategory, a confidence and evidence. Trained on **ten products**; leave-one-product-out strict accuracy 0.36 and non-food never predicted for an unseen product. The 2026-09-22 evaluation review established that it scores **below a constant "always food" classifier** (macro F1 0.279 vs 0.389), that raising the confidence bar makes it monotonically *worse* (0.000 accuracy above 0.75), and that fourteen model configurations all fail the same way — so the artifact stays at 0.1.0 and the acceptance policy stays empty. The binding constraint is two non-food products, one per non-food subcategory. **Dataset work of 2026-09-23** added twelve enforced integrity checks (duplicate products, duplicate images, conflicting labels, product leakage, provenance gaps, empty classes), a human-verification ledger with `label_verified_on` / `label_verification_ref`, and a dataset registry pinning each version's digest — and added **no data**: a repository-wide inventory (image overlap checked by SHA-256) confirmed there is no unused genuine product data, so the set is still 33 examples from 10 products with **0 of 33 labels verified**. The classifier may never verify its own labels; the loader and the ledger both refuse a machine as verifier. Reaches the API as `product_classification`. **Feeds applicability through one adapter** (`auto_applicability.py`): a suggestion for a person to confirm by default; can establish `Product.category` automatically only under a configured, evaluation-cited policy entry — none exists for this artifact. Never a declaration, never a scope gate. A suggestion is shown with the evidence behind it — the label phrases this reading contains, with snippets — and with what confirming will do. See `docs/automatic-applicability.md`. | `ml/labelextract/classification/`, `docs/ml/product-classification.md` |
| Applicability | Working. Rules 3 and 26 scope gates, then each clause's own conditions, resolved from stated facts **before** any rule is evaluated. The classifier's category may now supply the product category — under an accepted policy automatically, otherwise after a person confirms one question — with `product_category_source` and `applicability_assessment` on every result saying which. | `apps/compliance/services/applicability.py`, `auto_applicability.py` |
| Rule engine | Working. Seven registered deterministic checks; no LLM anywhere in the decision path. | `apps/rules/checks/` |
| Findings & result | Working. One finding per rule examined, with clause, source, evidence, confidence and applicability. | `apps/compliance/services/engine.py` |
| Frontend | Working. Scan, result, permalink and history screens against the real API. | `frontend/src/` |
| Mobile client | **Foundation.** React Native (Expo) app: camera or gallery → preview → upload to `POST /api/v1/extraction/` → `POST /api/v1/compliance/` → result with verdict, findings, reading and the classifier's suggestion when present. Shares the web's design language as of 2026-09-23 (same palette, rhythm and tones; native layout, no web CSS). 203 Jest tests; Android project generated and a debug APK built with Gradle; iOS configured but not built; not yet run on hardware. No sign-in - relies on the demonstration switch. | `mobile/`, `docs/mobile.md` |
| Authentication UI | **Not built.** Session auth and deny-by-default permissions exist; there is no login screen, so a demonstration switch (`DEMO_PUBLIC_ANALYSIS_API`, default off) opens the analysis endpoints. | — |
| Deployment | Configured and verified, **not deployed**. Container image, Railway config, gunicorn, one-command initialisation. No Railway project exists. | `Dockerfile`, `railway.json`, `backend/gunicorn.conf.py` |

---

## Automated rules

Eleven active rules over eight clauses. **Each tests less than its clause
requires**, and each rule file's own `requirement` text is narrowed to match so
a finding cannot read as a broader claim.

| Clause | Rule(s) | Automated? | What is checked | What is **not** |
|---|---|---|---|---|
| 6(1)(a) | LM-PC-0001 | Partial | Manufacturer, packer **or** importer name is present | The address — that is rule 10(1), and addresses are not extracted |
| 6(1)(aa) | LM-PC-0007 | Partial | Country of origin, on a package **declared** imported | Whether the country named is correct |
| 6(1)(c) | LM-PC-0003 | Partial | A net quantity is declared | Whether it is true — that needs a weighing |
| 6(1)(d) | LM-PC-0004, LM-PC-0011 | Partial | A date is declared; that it resolves to a month and a year | Its printed format — the clause prescribes none |
| 6(1)(e) | LM-PC-0005, LM-PC-0012 | Partial | A price is declared; that it is not declared *exclusive* of taxes | Whether "MRP" alone indicates tax inclusion (legal construction); "in Indian currency" |
| 6(2) | LM-PC-0006, LM-PC-0010 | Partial | A consumer-care contact is declared; that it states a telephone **and** an e-mail | The **name and address** of the person or office |
| 13(4) | LM-PC-0009 | Partial | No dozen, score, gross or great gross in the quantity | Units "or the like"; anything outside the quantity declaration |
| 13(5) | LM-PC-0008 | Partial | The quantity's unit is SI, or a unit of number | — |

`LM-PC-0002` (clause 6(1)(b), common or generic name) is loaded but **inactive**,
because the extractor does not read the declaration it names. Reactivating it
needs measured extraction recall, not a legal decision.

**No clause in this table is fully automated.** "Partial" is the honest column
value for all eight, and there is no ninth.

Rules 6(1)(a) and 6(1)(d) are scoped to `packaged-non-food` by category, because
Explanation III places food articles under the Food Safety and Standards Act,
2006. A submission declared `packaged-food` therefore never evaluates them —
correctly, and visibly, since the count of rules examined changes with the
category.

---

## Review-required areas

Requirements a photograph and this software cannot settle. These reach
`REQUIRES REVIEW`, or are not evaluated at all, by design:

- **Physical measurement** — rules 7, 8(1), 9(1)(b), 9(2): height of numerals,
  size of the principal display panel, area of the declaration. A photograph
  carries no millimetre scale.
- **Physical inspection** — rules 19–23: the package itself, in the hand.
- **Devanagari** — rule 9(4). Without Hindi OCR a Hindi label reads as
  *unreadable*, never as compliant.
- **Addresses** — rule 10(1), and the address half of 6(1)(a) and 6(2). Not
  extracted at all.
- **Untranscribed clause text** — rules 11(2)–(4), 12(6), 13(2)–(3) have empty
  or summarised text in the framework and must be transcribed by a named
  reviewer before anything is built on them.
- **Administrative** — rules 27–30: registration and record-keeping, not
  labelling.
- **Undeclared applicability** — any clause gated on a fact nobody stated. The
  engine reports the gate as undetermined; it never guesses.
- **Legal construction** — rules 9(1)(a) and 33 are marked
  `legal_review_required` in the framework.

Of 69 recorded requirements: **8 implemented**, 10 implementable with a new
check, 18 blocked on applicability data, 3 blocked on a missing extraction
field, 2 needing legal review, 28 outside this project's scope.

---

## The four outcomes, and why the third one matters

| Result | Meaning |
|---|---|
| `COMPLIANT` | Every applicable rule was evaluated and passed. **Not a certification** — it covers only the loaded rules and only what was legible. |
| `NON_COMPLIANT` | Verified rules were not met, with evidence. |
| `PARTIALLY_COMPLIANT` | Some rules failed, others could not be determined. |
| `REVIEW_REQUIRED` | Nothing could responsibly be concluded. **The default, and a first-class outcome.** |

Per finding there is a fourth status, `NOT_APPLICABLE`: the rule does not govern
this package, so nothing about its declarations was examined. It is **not** a
pass, and it is counted outside `rules_evaluated` for that reason.

Five engine guarantees, each covered by a test:

1. No rules checked → never `COMPLIANT`.
2. An unverified rule can never produce a violation.
3. An unreadable photograph is never a missing declaration.
4. An unestablished fact never produces a verdict.
5. A reading the extractor would not commit to, or one with a low reported
   confidence, never produces a violation.

**There is no compliance score.** No percentage, no grade, no aggregate
confidence — in the API or in the UI. A number would imply that partial
compliance with a labelling requirement is partial credit.

---

## Known legal limitations

1. **The amendment chain has a gap.** The Department's consolidated publication
   annotates amendments up to G.S.R. 226(E) (28 March 2022), while G.S.R. 128(E)
   records the principal rules as last amended by **G.S.R. 881(E) (2 December
   2025)**. The notifications in that window **could not be retrieved and remain
   unresolved.** Read "verified" in this repository as *verified against the
   Department's consolidated publication*, not against every notification in
   force. Nothing in Step 5 changed this, and no claim was upgraded on account
   of the project being finished.
2. **No named human reviewer.** Every rule's `source_note` ends by saying human
   counter-review is outstanding. A qualified reviewer who has read the source
   should replace that with their name. Until then no finding here has been
   confirmed by a person qualified to confirm it.
3. **Rules 3 and 26 do not bite unless declared.** A gate nobody answered leaves
   the package evaluated, with the caveat carried on every finding's
   `applicability_note`. Declaring the facts is what removes it.
4. **Relaxations under rule 33 are invisible** to the system, whatever anybody
   declares.
5. **A finding is about one reading of one photograph**, not about the package.

---

## Known security limitations

Fixed in Step 5:

- **Compliance results are now scoped to the caller.** An authenticated user
  reads only the checks they requested; somebody else's is a 404 identical to a
  result that does not exist. Previously any caller the permission class let
  through could read — and list — every stored check. See
  `docs/security.md` and `apps/compliance/tests/test_result_ownership_api.py`.

Still open:

1. **Anonymous results are a shared pool.** An anonymous caller has no identity
   to scope to, so every anonymous caller of the same deployment sees the same
   demonstration checks. Only reachable with `DEMO_PUBLIC_ANALYSIS_API` on,
   which defaults to off, and which must stay off on any deployment holding real
   submissions. `docs/deployment.md` spells out exactly what turning it on makes
   public, so that turning it on is a decision rather than an accident.
2. **No login screen.** Session authentication works; there is no UI for it.
3. **Throttling is per-process.** DRF's counters live in `LocMemCache`, which is
   per-process, so N workers means N counters and roughly N x the configured
   rate. **Mitigated in Step 6 rather than fixed:** the deployment runs a single
   gunicorn worker by default (`backend/gunicorn.conf.py`), which makes the
   configured rate the real rate; concurrency comes from threads, which share
   the process and therefore the counter. Raising `WEB_CONCURRENCY` reopens the
   gap and needs a shared cache first. No Redis has been added.
4. **`ProductImage.uploaded_by` is not filtered on.** Nothing exposes an image
   or its file through the API today, so nothing leaks by it — but it must be
   enforced before anything does.
5. **No audit log, no antivirus scanning, no CSP, no dependency scanning in CI.**
6. **Uploaded images are unencrypted at rest**, filesystem permissions only.
7. **The HTTPS redirect has one exemption.** `/api/v1/health/` is served over
   plain HTTP rather than redirected, because a platform health probe arrives
   that way and does not follow redirects — without it the deployment never
   passes its health check. It is one exact path, on an endpoint that returns no
   configuration, credentials or user data; HSTS is unaffected and everything
   else still redirects. Asserted in both directions in
   `apps/core/tests/test_https_redirect.py`.

---

## Other known limitations

- **Orientation is not detected.** `osd` is installed but the configured page
  segmentation mode does not use it, so a pack photographed on its side returns
  mirrored text and reads as unreadable. Measured and recorded in
  `docs/evaluation-results.md`.
- **`ProductImage.view_type` is recorded but not acted on.** A declaration
  missing from a *front-panel* photograph is still reported FAILED, exactly as
  on a photograph of the declaration panel. The scan screen warns the submitter
  of this; the engine does not model it, because whether a panel makes a clause
  undeterminable is a legal judgement per clause rather than a switch.
- **Uploaded photographs do not persist in a deployment** unless a volume is
  mounted over `MEDIA_ROOT`. The container filesystem is replaced on every
  deploy, so the database keeps the result rows and loses the evidence they were
  drawn from. Object storage is not a drop-in fix: extraction opens a local file
  path, so S3 needs a code change to `build_image_ref` first. Recorded as a
  requirement rather than solved by picking a provider.
- **Every evaluation creates a `ComplianceCheck`.** Re-evaluating the same
  reading is supported and deliberately produces a second record, so a result
  from before a rule was loaded stays comparable with one from after. The
  history endpoint therefore grows by one per evaluation. Re-evaluation does
  **not** re-read the photograph — the stored reading is used, so the
  declarations the user was shown and the ones the findings cite are the same.

**Extraction quality, stated from measurement, not from hope.** On the project's
own 28-image evaluation set the configured pipeline reads declarations from
roughly a third of the photographs; recall is **0.205** with precision 0.944
(`docs/evaluation-results.md`, v0.2.0). A clear photograph of the declaration
panel yields the full set; an angled, rotated or front-panel shot commonly
yields nothing. **No accuracy figure beyond those measured ones may be quoted,
and there is no measured end-to-end verdict accuracy at all.**

---

## What this system is not

- **Not a legal authority.** It assists a human reviewer. Every finding is the
  output of one deterministic check against one reading of one photograph.
- **Not an enforcement instrument.** It computes no penalty and makes no
  determination under the Act.
- **Not an LLM deciding compliance.** OCR assists with *extraction only*. The
  legal requirements live in versioned data and a deterministic engine; no model
  output reaches a verdict. Machine learning beyond OCR is future scope and is
  not present.
- **Not complete**, and not claimed to be.

---

## Deployment status

**READY FOR DEPLOYMENT — NOT DEPLOYED.** The configuration exists, and every
check below has been run. No Railway project has been created from this
repository, no `railway up` has been run, and there is no URL. Anyone saying
"it's deployed" is wrong; the accurate sentence is "it is ready to deploy".

Target: the backend as a container on **Railway**, with **Railway PostgreSQL**;
the React bundle hosted separately. Full runbook:
[`docs/deployment.md`](docs/deployment.md).

### What now exists

| Requirement | How it is met |
|---|---|
| Production server | `gunicorn` in `backend/requirements.txt`, configured in `backend/gunicorn.conf.py` — one worker, four threads, 120 s timeout |
| Start command | `railway.json` → `deploy.startCommand`, and the `Dockerfile` `CMD` |
| Static files | WhiteNoise middleware + manifest storage; `collectstatic` runs at image build time |
| Release step | `manage.py deploy_setup` as Railway's `preDeployCommand` |
| Tesseract | Installed by the `Dockerfile` (`tesseract-ocr`), which is why the image is a Dockerfile and not an automatic Python build |
| Database | `DATABASE_URL` takes precedence over the discrete `DATABASE_*` variables; nothing is hard-coded |
| Health check | `railway.json` → `healthcheckPath: /api/v1/health/`, exempted from the HTTPS redirect so a plain-HTTP probe is answered |
| Environment | Every variable read by `settings.py` or `gunicorn.conf.py` is documented in `.env.example` — audited in both directions, no drift |
| Frontend | `VITE_API_BASE_URL` at build time; verified to be compiled into the bundle |

### The initialisation problem, and how it is now closed

Step 5 found that omitting `load_legal_framework` changes verdicts silently. A
deployment that ran four hand-written commands could lose the last one and
nothing downstream would complain.

`manage.py deploy_setup` runs all four in the required order, then **verifies
the resulting state** and exits non-zero if categories, active rules,
instruments, requirements or applicability conditions are empty. Railway does
not promote a container when the pre-deploy command exits non-zero, so a
half-initialised database fails the deploy instead of serving wrong answers. It
is idempotent, and CI runs it on every pull request.

### The other silent failure, now visible

`/api/v1/health/` previously could not distinguish a working OCR deployment from
one whose image lacks the Tesseract binary: both report `is_placeholder: false`,
because both have a real pipeline *configured*. The endpoint now also reports
`available`, which resolves the pipeline **and calls the binary**. A deployment
is genuinely doing OCR only when it reports `is_placeholder: false` **and**
`available: true`; `available: false` makes the endpoint answer 503.

### Verified locally

- Clean PostgreSQL database created, `deploy_setup` run twice: succeeds, and the
  second run changes no row count in any of the five tables.
- `DATABASE_URL` proven to be the connection actually used — the discrete
  `DATABASE_*` variables were pointed at a non-existent database and everything
  still connected.
- `check --deploy`: no issues. `makemigrations --check`, `migrate --check`: clean.
- `collectstatic` under the production storage backend: 163 files, manifest written.
- Production-like smoke test — `DEBUG=False`, the real WSGI application over
  real HTTP, real PostgreSQL, real Tesseract 5.4, a real label photograph:
  **41/41 checks passed.** Health, HTTPS enforcement and its one exemption, the
  host allowlist, static serving, media *not* being served, upload → OCR →
  compliance, an invalid image, a REVIEW REQUIRED verdict, result retrieval,
  history, and result ownership.

### Not verified here, and why

- **The container image has never been built.** Docker is not installed on the
  development machine. The `container` job in CI builds it and checks that
  Tesseract, the static manifest and the rule files are inside — but that job
  has not run yet, because nothing has been pushed.
- **Gunicorn has never been started.** It is POSIX-only and this is Windows. The
  smoke test drives the same `config.wsgi:application` callable through
  `wsgiref`, so everything above the server is exercised; the server itself is
  not.

### Deployment blockers

None for a demonstration deployment. Two things must be **decided** rather than
fixed:

1. **Media persistence.** Uploaded photographs do not survive a deploy on an
   ephemeral filesystem. Mount a Railway volume at `/app/backend/media` and set
   `DJANGO_MEDIA_ROOT`, or accept the loss. Object storage is *not* a drop-in
   alternative — `build_image_ref` opens a local path, so S3 needs a code change
   first. This is recorded rather than invented.
2. **Demonstration mode.** `DEMO_PUBLIC_ANALYSIS_API` defaults to `False`. A
   public demo needs it `True`, which makes anonymous results a shared pool.
   Authenticated users' results stay private either way.

---

## Demonstration preparation

The development database accumulates a `ComplianceCheck`, a `ProductImage`, an
`ExtractionRun` and a `Product` per upload. Before a demonstration, inspect what
is there and remove it deliberately — never blindly, and never against a
database you have not just looked at:

```bash
cd backend
python manage.py shell -c "from apps.compliance.models import ComplianceCheck; \
  print(ComplianceCheck.objects.count()); \
  [print(c.pk, c.created_at, c.result, c.requested_by_id) for c in ComplianceCheck.objects.all()]"
```

Deleting the `Product` rows cascades to their images, runs and checks. Rules,
categories and the legal framework are **not** touched by that and do not need
reloading. Confirm the row count is what you expect before and after.

---

## Verification

```bash
cd backend  && pytest -q      # 819 passing
cd ../ml    && pytest -q      # 575 passing
cd ../frontend && npm test    # 202 passing
cd ../frontend && npm run lint && npm run build
```

Deployment configuration:

```bash
DJANGO_DEBUG=False python backend/manage.py check --deploy   # no issues
DJANGO_DEBUG=False python backend/manage.py collectstatic --noinput
python backend/manage.py deploy_setup                        # idempotent
python backend/manage.py makemigrations --check --dry-run    # no changes
```

Counts are as of the Step 6 deployment-preparation pass. The backend gained 19
tests over Step 5: the `deploy_setup` command, the engine-availability probe on
the health endpoint, and the HTTPS-redirect exemption in both directions.
