"""The chain end to end: real extraction -> database -> compliance engine.

Every other test in the backend stops at one seam. The service tests check that
a result is persisted; the engine tests check that a rule evaluates correctly
against a *fixture* run. Nothing checked that a reading produced by the real
field extractor still means the same thing by the time a rule has been
evaluated against it.

That gap matters because the failures it would catch are silent. The backend
never raises when it flattens a reading - it just stores a smaller truth, and
the compliance engine faithfully draws the wrong conclusion from it.

What is real here and what is not
---------------------------------
The **field extractor is the real one** -
`labelextract.fields.RuleBasedFieldExtractor` - so the readings under test are
the ones production would produce. Only the OCR engine is faked, and only
because the suite must run on a fresh clone with no Tesseract binary
installed. The fake returns lines of text; everything downstream is production
code.

The three distinctions this file defends
----------------------------------------
    DECLARED WITH VALUE      a usable value was read
    DECLARED BUT UNREADABLE  the declaration was named, its value was not read
    NOT DETECTED             nothing on the label named it

Collapsing the second into the third turns "retake the photograph" into "this
package is non-compliant". Collapsing it into the first records a declaration
the package may never have made. Neither is recoverable downstream, because by
then the distinction is gone from the database.

Scope of these assertions
-------------------------
These are **backend** guarantees: that whatever the extractor concluded arrives
intact and is read back unchanged. They deliberately do not assert that the
extractor's conclusion is the right one - that is `ml/tests/`' job, and pinning
ML behaviour from here would make an extraction improvement look like a backend
regression.

Nothing here asserts a legal requirement. The rules are fixtures; whether a
declaration is legally required is decided by verified `ComplianceRule` rows
sourced from the legal text, not by this file.
"""

from __future__ import annotations

import pytest

from labelextract import registry
from labelextract.contracts import ImageRef, OcrResult, TextBlock
from labelextract.exceptions import PipelineNotFoundError
from labelextract.fields import RuleBasedFieldExtractor
from labelextract.interfaces import OcrEngine
from labelextract.pipeline import ExtractionPipeline

from apps.compliance.models import ComplianceCheck
from apps.compliance.services.engine import evaluate
from apps.extraction.models import ExtractedLabelField, ExtractionRun
from apps.extraction.services.extraction_service import run_extraction

_VERSION = "0.0.0-contract-test"


class _ScriptedOcrEngine(OcrEngine):
    """Returns fixed lines of label text. The only faked component."""

    name = "scripted"
    version = _VERSION

    def __init__(self, lines: tuple[str, ...]):
        self._lines = lines

    def recognise(self, image: ImageRef) -> OcrResult:
        return OcrResult(
            blocks=tuple(
                TextBlock(text=line, box=None, confidence=0.9) for line in self._lines
            ),
            raw={"engine": "scripted"},
        )


#: Label text -> pipeline name. Each is a real pack phrasing whose *meaning*
#: has to survive the trip through the database.
_SCRIPTS = {
    # Plain, unambiguous declarations.
    "contract-certain": ("Net Quantity: 500 g", "MRP Rs. 40.00"),
    # Declarations named with their values left blank. No field, but an unread
    # observation - the difference between "absent" and "printed unreadably".
    "contract-unread": ("Net Quantity:", "MRP Rs."),
    # Text was read and no declaration was found. Genuinely absent.
    "contract-absent": ("Store in a cool dry place", "Best consumed when fresh"),
}


def _register_scripts() -> None:
    for name, lines in _SCRIPTS.items():
        try:
            registry.get_pipeline(name, _VERSION)
        except PipelineNotFoundError:
            registry.register_pipeline(
                name,
                _VERSION,
                # The default argument binds the current value; a bare closure
                # would capture the loop variable and give every pipeline the
                # last script.
                lambda lines=lines: ExtractionPipeline(
                    name="scripted",
                    version=_VERSION,
                    ocr_engine=_ScriptedOcrEngine(lines),
                    preprocessor=None,
                    field_extractor=RuleBasedFieldExtractor(),
                ),
            )


_register_scripts()


@pytest.fixture
def extract(product_image):
    def _extract(script: str) -> ExtractionRun:
        return run_extraction(
            product_image, engine_name=script, engine_version=_VERSION
        )

    return _extract


def _field(run: ExtractionRun, key: str) -> ExtractedLabelField | None:
    return run.fields.filter(field_key=key).first()


def _unread(run: ExtractionRun) -> list[dict]:
    return run.raw_output["metadata"]["unread_declarations"]


# --- DECLARED WITH VALUE -----------------------------------------------------


def test_a_read_declaration_survives_into_the_database_unchanged(extract):
    """The straightforward case, pinned so the others mean something."""
    run = extract("contract-certain")

    quantity = _field(run, "net_quantity")
    assert quantity is not None
    assert quantity.normalized_value["base_quantity"] == 500
    assert quantity.normalized_value["base_unit"] == "g"
    assert quantity.raw_value == "Net Quantity: 500 g"

    price = _field(run, "retail_sale_price")
    assert price is not None
    assert price.normalized_value["amount"] == "40.00"


def test_the_uncertainty_flag_is_carried_rather_than_dropped(extract):
    """Whatever the extractor concluded about certainty must reach the row.

    The flag is asserted to be *present and boolean*, not to have a particular
    value: which readings the extractor considers certain is its decision, and
    an improvement there must not read as a backend regression. What the
    backend owes is that the flag arrives at all - a consumer that cannot see
    it has no way to distinguish a measured value from a guess.
    """
    run = extract("contract-certain")

    for field in run.fields.all():
        assert "uncertain" in field.normalized_value
        assert isinstance(field.normalized_value["uncertain"], bool)


def test_a_read_declaration_passes_a_presence_rule(extract, make_rule):
    """...and the compliance engine agrees it is present."""
    run = extract("contract-certain")
    make_rule("CT-0001", field_key="net_quantity")

    check = evaluate(product=run.image.product, extraction_run=run)

    assert check.rules_passed == 1
    assert check.rules_failed == 0
    assert check.result == ComplianceCheck.Result.COMPLIANT


# --- DECLARED BUT UNREADABLE -------------------------------------------------


def test_a_named_declaration_with_no_value_produces_no_field(extract):
    """A keyword is not a value.

    `Net Quantity:` with nothing after it must not become a net quantity.
    `field_presence` passes on any extracted field regardless of its
    uncertainty flag, so a fabricated value here would record a package that
    declared nothing as having declared something - a real violation turned
    into a pass.
    """
    run = extract("contract-unread")

    assert _field(run, "net_quantity") is None
    assert _field(run, "retail_sale_price") is None


def test_a_named_declaration_with_no_value_survives_as_an_observation(extract):
    """Absent" and "printed but unreadable" must stay distinguishable.

    The extraction pipeline puts these in its run metadata, which the backend
    persists verbatim into `raw_output`. That is the whole reason the signal
    reaches the database without a column of its own - and it is why reshaping
    `raw_output` would break a contract written on the ML side of the boundary.
    """
    run = extract("contract-unread")

    keys = {item["key"] for item in _unread(run)}
    assert "net_quantity" in keys
    assert "retail_sale_price" in keys


def test_the_unread_observation_carries_its_evidence_line(extract):
    """An observation about a label has to say which line it came from.

    Without the evidence text there is nothing for a reviewer to check the
    claim against, and "the package names a net quantity we could not read"
    becomes unfalsifiable.
    """
    run = extract("contract-unread")

    quantity = next(
        item for item in _unread(run) if item["key"] == "net_quantity"
    )
    assert quantity["evidence_text"] == "Net Quantity:"
    assert "confidence" in quantity
    assert "box" in quantity


def test_the_unread_signal_survives_a_reload_from_the_database(extract):
    """Read back through the ORM, not just off the in-memory instance."""
    run_pk = extract("contract-unread").pk

    reloaded = ExtractionRun.objects.get(pk=run_pk)

    keys = {
        item["key"]
        for item in reloaded.raw_output["metadata"]["unread_declarations"]
    }
    assert "net_quantity" in keys


def test_an_unread_declaration_is_not_a_stored_field(extract):
    """The two mechanisms must not be conflated.

    An unread declaration is an observation *about* the extraction, explicitly
    not a field. If it ever started arriving as a row in `ExtractedLabelField`,
    `field_presence` would pass on it and "we could not read this" would become
    "this was declared".
    """
    run = extract("contract-unread")

    assert run.fields.count() == 0
    assert len(_unread(run)) >= 2


# --- NOT DETECTED ------------------------------------------------------------


def test_text_that_declares_nothing_produces_no_fields_and_no_unread(extract):
    """A genuine absence, which is the only case a violation may be built on."""
    run = extract("contract-absent")

    assert run.status == ExtractionRun.Status.COMPLETED
    assert run.recognised_text != ""
    assert run.fields.count() == 0
    assert _unread(run) == []


def test_a_genuine_absence_can_fail_a_verified_rule(extract, make_rule):
    """The readable-and-absent case is the one that may be reported.

    This is the counterpart to the unreadable-photograph guarantee: when the
    text *was* read and the declaration genuinely is not there, a verified rule
    is allowed to find against it.
    """
    run = extract("contract-absent")
    make_rule("CT-0003", field_key="net_quantity")

    check = evaluate(product=run.image.product, extraction_run=run)

    assert check.rules_failed == 1
    assert check.violations.count() == 1
    assert check.violations.first().field_key == "net_quantity"


def test_an_unverified_rule_still_cannot_find_against_a_genuine_absence(
    extract, make_rule
):
    """The engine's own guarantee, exercised through a real extraction run.

    Only rules verified against the legal text may produce a violation. An
    unverified one is downgraded to a review signal no matter what its
    validator concluded.
    """
    run = extract("contract-absent")
    make_rule("CT-0004", field_key="net_quantity", verified=False)

    check = evaluate(product=run.image.product, extraction_run=run)

    assert check.rules_failed == 0
    assert check.rules_inconclusive == 1
    assert check.violations.count() == 0


# --- reproducibility ---------------------------------------------------------


def test_the_run_records_the_engine_that_produced_it(extract):
    """A stored result names the pipeline that made it, or it is not evidence."""
    run = extract("contract-certain")

    assert run.engine_name == "contract-certain"
    assert run.engine_version == _VERSION
    assert run.is_placeholder is False


@pytest.mark.parametrize("script", sorted(_SCRIPTS))
def test_every_script_records_which_components_ran(extract, script):
    """Run metadata is what makes a disappointing result diagnosable later."""
    run = extract(script)

    metadata = run.raw_output["metadata"]
    assert metadata["field_extraction_ran"] is True
    assert "bounding_box_space" in metadata
    assert "unread_declarations" in metadata
