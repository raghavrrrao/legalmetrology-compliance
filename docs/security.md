# Security notes

Baseline security for the base structure, and the reasoning behind each choice.
This is a foundation, not a hardened deployment — see "Known gaps" at the end.

## Secrets

Nothing secret is in this repository. Verified: the only credential-shaped
strings in tracked files are the literal `replace-me-...` placeholders in
`.env.example`.

| Rule | Where enforced |
|---|---|
| `.env` never committed | `.gitignore`, plus `!.env.example` so the template stays tracked |
| No default for `DJANGO_SECRET_KEY` | `settings.py` — a missing key raises at startup rather than falling back to a value identical on every machine |
| No default for database credentials | `settings.py` |
| Frontend variables are public | `frontend/.env.example` carries an explicit warning |

**Vite inlines every `VITE_`-prefixed variable into the browser bundle.**
Anything in `frontend/.env` is readable by anyone who views source. It is
public configuration, not client-side storage of a secret.

If a secret is ever committed: rotate it. Deleting it in a later commit does
nothing — it remains in history and in every clone.

## Image upload

Uploads are the largest attack surface here. An uploaded file is
attacker-controlled in every respect: name, declared content type, size, bytes.

`apps/images/validators.py` applies these in order, each covering something the
others do not:

| Check | Defeats |
|---|---|
| Extension allowlist | Casual wrong-type uploads. Cheap, proves nothing on its own. |
| Content-type allowlist | Same. Both are *claims*. |
| Size limit | Resource exhaustion. Enforced at the app layer as well as by `DATA_UPLOAD_MAX_MEMORY_SIZE`, so a caller building an upload in code cannot bypass it. |
| Pixel-count limit | **Decompression bombs.** A 40 KB PNG can declare dimensions expanding to gigabytes. Dimensions are read from the header and rejected *before* a full decode. |
| Minimum dimension | Images too small to carry legible text. |
| `Image.open()` + `verify()` | **The check that matters.** It asks the decoder what the bytes are, rather than asking the uploader. This is what catches an executable or a script renamed to `.png`. |
| Decoded-format allowlist | A file that decodes as something we do not support, whatever it claimed. |

Allowlists throughout, never denylists. A denylist is a list of the attacks
someone already thought of.

**SVG is deliberately excluded.** It is an XML document that can carry script
and external entity references, not an image in any sense useful for OCR.

### Filename handling

The uploaded filename is **never** used to build a path on disk. Every stored
file gets a generated random name under
`product-images/<YYYY>/<MM>/<uuid><ext>`.

That single decision eliminates path traversal (`../../etc/passwd`), collisions
between two users uploading `photo.jpg`, and Windows reserved device names
(`CON`, `NUL`, `LPT1`) — without trying to enumerate and sanitise each one.

The original name is kept as `original_filename` for display only, after being
stripped of directory components and control characters (which can forge log
lines and corrupt terminal output) and length-capped.

### Storage

Uploaded images are third-party content — trade dress, sometimes incidental
personal data. They are stored outside the static tree, are git-ignored, and
are served by Django **only** when `DEBUG=True`. In a deployment, serving is
the web server's or object store's job, behind access control.

`checksum_sha256` on every image ties a compliance result to the exact bytes
analysed. If a stored file is later replaced or corrupted, the mismatch is
detectable rather than silent.

## Django configuration

Set in `backend/config/settings.py`:

| Setting | Value | Purpose |
|---|---|---|
| `SECURE_CONTENT_TYPE_NOSNIFF` | `True` | Stops MIME sniffing. |
| `X_FRAME_OPTIONS` | `DENY` | Clickjacking. |
| `SECURE_REFERRER_POLICY` | `same-origin` | Limits referrer leakage. |
| `SESSION_COOKIE_HTTPONLY` | `True` | Session cookie unreadable from JS. |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `not DEBUG` | HTTPS-only outside development, automatically. |
| `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE` | `Lax` | CSRF defence in depth. |
| `SECURE_SSL_REDIRECT`, HSTS | enabled when `DEBUG=False` | Transport security in deployment. |

Tying the cookie flags to `DEBUG` means a deployment with `DEBUG=False` gets
secure cookies without a second setting anyone could forget.

## API abuse

- Permissions **deny by default**; public endpoints opt in explicitly.
- Throttling: 30/min anonymous, 120/min authenticated, configurable.
- Health is exempt from throttling — a throttled health check reports a false
  outage.

## Logging

Application logs go through the `apps` and `labelextract` loggers.

**Never log** image bytes, full request bodies, credentials, tokens, session
keys, or `SECRET_KEY`. Exceptions are logged with tracebacks server-side; API
responses carry only a stable code and a safe message.

The health endpoint follows this: it reports *whether* the database answered,
never *why* it did not. A connection string in an error response is useful to
an attacker and to nobody else.

## Error handling

- Unhandled exceptions return a plain 500. They are never converted into a
  200-with-error-body, which would hide failures from any client checking the
  status code.
- `DEBUG=False` in deployment means Django never renders a traceback.
- Error responses carry a stable `code` and a user-safe `message`. Internal
  detail stays in the logs.

## Known gaps

Deliberately not addressed in the base structure. Listed so nobody assumes they
are covered.

| Gap | Notes |
|---|---|
| **Throttling is per-process** | DRF's local-memory cache. With multiple workers the effective limit multiplies. Needs a shared cache for a real deployment. |
| **No antivirus scanning** | Format validation is not malware scanning. Consider ClamAV if uploads are ever re-served to other users. |
| **No authentication yet** | No endpoint needs it in the base. `feature/authentication` owns this, and until then no endpoint exposes user data. |
| **No per-object authorisation** | `ProductImage.uploaded_by` exists but nothing enforces "you may only see your own". Must land with the first listing endpoint. |
| **Uploaded images are unencrypted at rest** | Filesystem permissions only (`FILE_UPLOAD_PERMISSIONS = 0o640`). |
| **No audit log** | Who viewed which compliance result is not recorded. |
| **No dependency scanning in CI** | `npm audit` reports 0 vulnerabilities at time of writing; nothing runs it automatically. |
| **No security headers beyond Django's** | No CSP. Relevant once the frontend is deployed. |

`feature/security-hardening` owns closing these.

## Before deploying

- [ ] `DJANGO_DEBUG=False`
- [ ] Fresh `DJANGO_SECRET_KEY`, not reused from any developer machine
- [ ] `DJANGO_ALLOWED_HOSTS` set to real hostnames
- [ ] `CORS_ALLOWED_ORIGINS` set to the real frontend origin only
- [ ] `DJANGO_MEDIA_ROOT` outside the repository, not web-served directly
- [ ] Database user is not a superuser
- [ ] HTTPS terminated in front of Django
- [ ] Throttling backed by a shared cache
- [ ] Per-object authorisation implemented on every endpoint returning user data
