"""The compliance engine.

Takes an extraction run, works out which rules apply, evaluates each one, and
records the result with its evidence.

    Product + ExtractionRun
        -> applicable rules      (category, effective date, active)
        -> evaluate each         (via apps.rules.checks validators)
        -> findings              (every outcome: passed, failed, inconclusive)
        -> violations + evidence (failures against verified rules only)
        -> overall result
        -> ComplianceCheck row

Findings and violations are both written, and the difference is the point. A
finding records what a rule concluded; a violation records that a package was
found wanting. Every violation has a finding; most findings have no violation.
See `ComplianceFinding` for why both exist.

The verdict logic is deliberately conservative, and the three rules below are
the ones to preserve if this file is ever rewritten:

1. **Zero applicable verified rules never yields COMPLIANT.** It yields
   REVIEW_REQUIRED. Having no rules loaded means we have not checked anything,
   which is not the same as finding nothing wrong. This is the current state of
   the repository, and a test enforces it.

2. **Unverified rules cannot fail a product.** A rule whose legal text nobody
   has checked against the source can flag a product for human review. It can
   never, on its own, tell a user their package breaks the law.

3. **Inconclusive is not a pass.** A rule that could not be decided - usually
   because the photograph was unreadable - degrades the result to
   REVIEW_REQUIRED or PARTIALLY_COMPLIANT. It is never counted as compliance.
"""

from __future__ import annotations

import json
import logging
import time

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.compliance.models import (
    ComplianceCheck,
    ComplianceEvidence,
    ComplianceFinding,
    ComplianceViolation,
)
from apps.extraction.models import ExtractionRun
from apps.rules import checks
from apps.rules.checks.base import CheckContext, CheckOutcome, CheckStatus
from apps.rules.models import ComplianceRule

logger = logging.getLogger(__name__)

#: Bumped when the verdict logic changes, so a stored result stays
#: interpretable after this file is edited.
ENGINE_VERSION = "0.1.0"


def applicable_rules(product: Product | None) -> list[ComplianceRule]:
    """Return the active, in-force rules that apply to `product`.

    Returns an empty list when `product` is None or has no category. That is
    correct and load-bearing: without knowing what the commodity is, we cannot
    know which declarations apply to it, and guessing would be worse than
    admitting it. The caller turns an empty list into REVIEW_REQUIRED.
    """
    if product is None or product.category_id is None:
        return []

    codes = product.applicable_category_codes
    candidates = (
        ComplianceRule.objects.filter(is_active=True)
        .prefetch_related("applies_to_categories")
        .order_by("code")
    )
    today = timezone.localdate()
    return [
        rule
        for rule in candidates
        if rule.is_in_force_on(today) and rule.applies_to_category_codes(codes)
    ]


@transaction.atomic
def evaluate(
    extraction_run: ExtractionRun,
    *,
    product: Product | None = None,
    requested_by=None,
) -> ComplianceCheck:
    """Evaluate `extraction_run` against the applicable rules and persist it.

    Always returns a saved `ComplianceCheck`. A run that could not be evaluated
    produces a REVIEW_REQUIRED result with an explanation, not an exception -
    the user needs to be told why there is no verdict.
    """
    started = time.perf_counter()
    product = product or extraction_run.image.product

    check = ComplianceCheck.objects.create(
        product=product,
        extraction_run=extraction_run,
        requested_by=requested_by,
        status=ComplianceCheck.Status.RUNNING,
        engine_version=ENGINE_VERSION,
        started_at=timezone.now(),
    )

    rules = applicable_rules(product)
    context = CheckContext.from_run(extraction_run)

    passed: list[ComplianceRule] = []
    failed: list[tuple[ComplianceRule, CheckOutcome]] = []
    inconclusive: list[tuple[ComplianceRule, CheckOutcome]] = []
    #: Every outcome, in evaluation order, with whether it was downgraded.
    #: Collected alongside the three buckets rather than derived from them
    #: afterwards, because the downgrade below rewrites an outcome and the
    #: original status would not be recoverable from the buckets.
    outcomes: list[tuple[ComplianceRule, CheckOutcome, bool]] = []

    for rule in rules:
        outcome = _evaluate_rule(rule, context)
        if outcome is None:
            continue

        # Guarantee 2: an unverified rule can never produce a violation, no
        # matter what its validator concluded. It is downgraded to a review
        # signal here, at the one place it can be enforced for every rule.
        if outcome.status is CheckStatus.FAILED and not rule.is_verified:
            downgraded = CheckOutcome(
                status=CheckStatus.INCONCLUSIVE,
                message=(
                    f"{outcome.message} This rule has not been verified "
                    f"against the authoritative legal text, so it is "
                    f"flagged for human review rather than reported as "
                    f"a violation."
                ),
                field_key=outcome.field_key,
                evidence_excerpt=outcome.evidence_excerpt,
                bounding_box=outcome.bounding_box,
                details=outcome.details,
            )
            inconclusive.append((rule, downgraded))
            outcomes.append((rule, downgraded, True))
            continue

        if outcome.status is CheckStatus.PASSED:
            passed.append(rule)
        elif outcome.status is CheckStatus.FAILED:
            failed.append((rule, outcome))
        else:
            inconclusive.append((rule, outcome))
        outcomes.append((rule, outcome, False))

    violations = _record_violations(check, failed, extraction_run, context)
    _record_findings(check, outcomes, context, violations)

    result, summary = _decide(
        product=product,
        run=extraction_run,
        applicable_count=len(rules),
        passed=passed,
        failed=failed,
        inconclusive=inconclusive,
    )

    check.status = ComplianceCheck.Status.COMPLETED
    check.result = result
    check.summary = summary
    check.rules_evaluated = len(passed) + len(failed) + len(inconclusive)
    check.rules_passed = len(passed)
    check.rules_failed = len(failed)
    check.rules_inconclusive = len(inconclusive)
    check.completed_at = timezone.now()
    check.processing_ms = int((time.perf_counter() - started) * 1000)
    check.save()

    return check


def _evaluate_rule(
    rule: ComplianceRule, context: CheckContext
) -> CheckOutcome | None:
    """Run one rule's validator. Returns None when the rule is misconfigured.

    A broken rule is logged and skipped rather than crashing the whole check:
    one bad rule file must not make every product unevaluable. It is not
    counted as passing.
    """
    try:
        validator = checks.get_check(rule.check_type)
        return validator(rule.parameters or {}, context)
    except Exception:
        logger.exception(
            "Rule %s could not be evaluated (check_type=%s)",
            rule.code,
            rule.check_type,
        )
        return None


def _record_violations(
    check: ComplianceCheck,
    failed: list[tuple[ComplianceRule, CheckOutcome]],
    run: ExtractionRun,
    context: CheckContext,
) -> dict[str, ComplianceViolation]:
    """Persist each failure with the evidence that supports it.

    Takes `context` so the linking extracted field comes from the map already
    loaded once in `CheckContext.from_run`, rather than a fresh query per
    violation.

    Returns the violations by rule code, so `_record_findings` can point each
    failed finding at the violation it became without re-querying. A rule code
    is unique per check because `applicable_rules` returns each rule once.
    """
    violations: dict[str, ComplianceViolation] = {}
    for rule, outcome in failed:
        violation = ComplianceViolation.objects.create(
            compliance_check=check,
            rule=rule,
            severity=rule.severity,
            rule_code=rule.code,
            legal_reference=rule.legal_reference,
            field_key=outcome.field_key or "",
            message=outcome.message,
        )
        # Evidence is attached even for an absence: what we DID read is the
        # justification for concluding the declaration was not there.
        ComplianceEvidence.objects.create(
            violation=violation,
            extracted_field=(
                context.field(outcome.field_key) if outcome.field_key else None
            ),
            image=run.image,
            excerpt=outcome.evidence_excerpt,
            bounding_box=outcome.bounding_box,
        )
        violations[rule.code] = violation
    return violations


#: `CheckStatus` is the checks package's runtime vocabulary; `Status` is the
#: database's. Mapped here rather than shared so a stored finding stays
#: readable if the runtime enum is ever extended - the same split
#: `extraction_service._STATUS_MAP` makes for extraction.
_FINDING_STATUS = {
    CheckStatus.PASSED: ComplianceFinding.Status.PASSED,
    CheckStatus.FAILED: ComplianceFinding.Status.FAILED,
    CheckStatus.INCONCLUSIVE: ComplianceFinding.Status.INCONCLUSIVE,
}


def _record_findings(
    check: ComplianceCheck,
    outcomes: list[tuple[ComplianceRule, CheckOutcome, bool]],
    context: CheckContext,
    violations: dict[str, ComplianceViolation],
) -> None:
    """Persist every rule outcome, not only the failures.

    This is what makes `rules_passed` and `rules_inconclusive` more than
    counters: each one now has a row naming the rule, the declaration it
    concerns, what was read, how confident the reader was, and why the
    validator concluded what it did.

    Nothing here decides anything. Every value is copied from a `CheckOutcome`
    the validator already produced or from the rule row as it stood when it was
    evaluated. Written with `bulk_create` so evaluating fifty rules costs one
    insert rather than fifty - the query-count regression tests in
    `test_engine_queries.py` bound this.
    """
    rows = []
    for rule, outcome, downgraded in outcomes:
        # The reading behind this outcome, when there is one. `context.field`
        # reads the map loaded once per check, so this is not a query.
        extracted = context.field(outcome.field_key) if outcome.field_key else None
        rows.append(
            ComplianceFinding(
                compliance_check=check,
                rule=rule,
                violation=violations.get(rule.code),
                status=_FINDING_STATUS[outcome.status],
                downgraded_from_failed=downgraded,
                rule_code=rule.code,
                title=rule.title,
                requirement=rule.requirement,
                legal_reference=rule.legal_reference,
                severity=rule.severity,
                check_type=rule.check_type,
                field_key=outcome.field_key or "",
                extracted_field=extracted,
                # Snapshotted from the reading rather than followed through the
                # foreign key: None stays None. A missing confidence means the
                # engine did not report one, never zero.
                extracted_confidence=(
                    extracted.confidence if extracted is not None else None
                ),
                message=outcome.message,
                evidence_excerpt=outcome.evidence_excerpt,
                bounding_box=outcome.bounding_box,
                details=_json_safe_details(outcome.details, rule_code=rule.code),
            )
        )
    if rows:
        ComplianceFinding.objects.bulk_create(rows)


def _json_safe_details(details, *, rule_code: str) -> dict:
    """Return `details` if the JSON column can store it, else an empty dict.

    Validator diagnostics are validator-shaped by design, and `details` is
    typed as a plain `Mapping` with nothing enforcing its contents. A `Path` or
    a `datetime` in there would otherwise surface as an adaptation error from
    inside `bulk_create`, after the check and its violations had been written -
    turning a cosmetic diagnostic into a failed compliance evaluation.

    Dropped rather than raised, because `details` is debugging output: losing it
    must not cost the user their result. The loss is logged with the rule code
    so it is fixable.
    """
    if not details:
        return {}
    try:
        return json.loads(json.dumps(dict(details)))
    except (TypeError, ValueError):
        logger.warning(
            "Rule %s produced diagnostics that are not JSON-serialisable; "
            "the finding is recorded without them",
            rule_code,
        )
        return {}


def _decide(
    *,
    product: Product | None,
    run: ExtractionRun,
    applicable_count: int,
    passed: list,
    failed: list,
    inconclusive: list,
) -> tuple[str, str]:
    """Derive the overall result and a plain-language explanation."""
    Result = ComplianceCheck.Result

    # Guarantee 1: nothing checked means nothing established.
    if applicable_count == 0:
        if product is None or product.category_id is None:
            return (
                Result.REVIEW_REQUIRED,
                "The commodity category for this product is not known, so the "
                "system cannot determine which declarations apply. No "
                "compliance conclusion has been drawn.",
            )
        return (
            Result.REVIEW_REQUIRED,
            "No compliance rules are loaded for this product's category, so "
            "nothing was checked. This is not a finding that the product "
            "complies - see rules/README.md.",
        )

    if not run.produced_usable_output:
        return (
            Result.REVIEW_REQUIRED,
            f"No readable text was extracted from this image "
            f"(extraction status: {run.status}), so none of the "
            f"{applicable_count} applicable rule(s) could be decided. Try a "
            f"clearer, closer photograph of the label.",
        )

    if failed and not inconclusive:
        return (
            Result.NON_COMPLIANT,
            f"{len(failed)} of {applicable_count} applicable rule(s) were not "
            f"met. See the violations below for the evidence behind each one.",
        )

    if failed and inconclusive:
        return (
            Result.PARTIALLY_COMPLIANT,
            f"{len(failed)} rule(s) were not met and {len(inconclusive)} could "
            f"not be determined from this image. The undetermined rules are "
            f"neither a pass nor a failure and need human review.",
        )

    if inconclusive:
        return (
            Result.REVIEW_REQUIRED,
            f"{len(inconclusive)} of {applicable_count} applicable rule(s) "
            f"could not be determined, so no compliance conclusion has been "
            f"drawn. {len(passed)} rule(s) passed.",
        )

    # Guarantee 3: reaching COMPLIANT requires rules to have actually passed.
    if passed:
        return (
            Result.COMPLIANT,
            f"All {len(passed)} applicable rule(s) were met. This covers only "
            f"the rules currently loaded in this system and only what was "
            f"legible in the submitted image - it is not a certification of "
            f"legal compliance.",
        )

    return (
        Result.REVIEW_REQUIRED,
        "No rule produced a usable outcome for this product, so no compliance "
        "conclusion has been drawn.",
    )
