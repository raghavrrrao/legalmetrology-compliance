"""Which stored readings a caller may evaluate.

`POST /api/v1/compliance/` takes the id of an `ExtractionRun` and answers with
a result that carries that run's whole reading - the recognised text, every
declaration read off the label, the photographs' metadata - and, when asked,
records applicability facts against the run's product. Until this module
existed the id was resolved with `ExtractionRun.objects.get(pk=...)`, so anyone
who held a run's id could read another person's label text, re-evaluate their
submission into their own history, and overwrite what they had declared about
their goods. A UUID makes a run hard to *find*; it was never permission to use
it.

The rule, and why it is this rule
---------------------------------
It is the rule `CallerScopedCheckQuerysetMixin` (`views.py`) already applies to
stored results, carried back one step to the reading they are made from:

- an **authenticated** caller may use a run only if **every** photograph in it
  was uploaded by them;
- an **anonymous** caller - reachable only with `DEMO_PUBLIC_ANALYSIS_API` on -
  may use a run only if **every** photograph in it was uploaded anonymously.

So a signed-in user cannot use a stranger's run, an anonymous caller cannot use
a signed-in user's run, and a signed-in user does not inherit the anonymous
demonstration pool - the same three answers the result endpoints give.

The ownership recorded on the schema today is `ProductImage.uploaded_by`, so
that is what is read. `ExtractionRun` has no owner of its own, and adding one is
a migration that belongs with the authentication work, not with this fix.

**Every** photograph, not the primary one
-----------------------------------------
A run reads a set of photographs: `ExtractionRun.image` is position 1, and one
`ExtractionRunImage` row per photograph records the whole set (migration 0003
gave every earlier run its position-1 row). The API ingests a set in one request
with one `uploaded_by`, so the photographs of an API-made run always share an
uploader - but `run_extraction_over` accepts any saved images and does not
enforce that. Checking only the primary photograph would therefore authorise a
run on the strength of one image while handing back readings of the others.
The rule checks the primary image *and* every membership row, and a run whose
photographs do not all satisfy it - mixed owners, or owned mixed with anonymous
- is not usable by anyone through the API.

What this does not do
---------------------
It does not make anonymous runs private: every anonymous caller of a
demonstration deployment still shares one pool, exactly as they share one pool
of results. Telling one anonymous caller from another needs an identity this
project does not have yet, and that is the authentication work's decision.
"""

from __future__ import annotations

from django.db.models import Exists, OuterRef, QuerySet

from apps.extraction.models import ExtractionRun, ExtractionRunImage


def runs_usable_by(user) -> QuerySet[ExtractionRun]:
    """The runs `user` may evaluate; an anonymous or missing user is anonymous.

    One query, with the membership check as a correlated `NOT EXISTS`, so the
    cost does not grow with the number of photographs in a set.
    """
    if user is not None and user.is_authenticated:
        primary_is_theirs = {"image__uploaded_by": user}
        # `exclude(uploaded_by=user)` keeps a NULL uploader: Django compiles
        # it as NOT (uploaded_by = user AND uploaded_by IS NOT NULL), so an
        # anonymous photograph counts as not theirs, which is the intent.
        not_theirs = ExtractionRunImage.objects.filter(run=OuterRef("pk")).exclude(
            image__uploaded_by=user
        )
    else:
        primary_is_theirs = {"image__uploaded_by__isnull": True}
        not_theirs = ExtractionRunImage.objects.filter(
            run=OuterRef("pk"), image__uploaded_by__isnull=False
        )
    return ExtractionRun.objects.filter(**primary_is_theirs).filter(~Exists(not_theirs))
