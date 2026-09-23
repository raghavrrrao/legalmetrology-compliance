"""One verdict for a package photographed from several sides.

Two properties, and both are about the boundary between a photograph and a
package:

**One inspection, one result.** Several photographs are evaluated once, by the
rule engine, over every declaration that was read. There is no second verdict
to reconcile and no combining of results - which matters because the plausible
wrong implementation (analyse each photograph, then merge the verdicts) would
report a package as failing to declare a net quantity that is printed on its
back panel.

**Evidence keeps its photograph.** A finding drawn from a reading cites the
photograph that reading came from, so an interface can say "Evidence · Image 2"
and be right. A finding of *absence* cites the primary photograph and means
nothing more by it: the declaration was absent from the whole set, and no panel
is more its evidence than another.

Recognition is stubbed and only recognition; the engine, the rules, the
applicability resolver and the serializers are the real ones.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from labelextract import registry
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.interfaces import OcrEngine
from labelextract.pipeline import ExtractionPipeline

from apps.compliance.models import ComplianceCheck, ComplianceEvidence
from apps.compliance.services import analysis_service
from apps.extraction.models import ExtractionRun

pytestmark = pytest.mark.django_db

_SPLIT_PIPELINE = "multi-image-split-declarations"
_NON_SI_PIPELINE = "multi-image-split-non-si"
_TEST_VERSION = "0.0.0"


class _UnusedOcrEngine(OcrEngine):
    """Satisfies the pipeline's constructor; `run` is overridden below."""

    name = "multi-image-analysis-unused-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        raise AssertionError("run() is overridden; this must not be reached")


class _SplitDeclarationPipeline(ExtractionPipeline):
    """A package whose declarations are printed on two different panels.

    The first photograph shows only a brand line and no declaration; the second
    shows the net quantity. This is the case the whole feature exists for: no
    single photograph carries everything, and only a reading assembled from
    both can answer what the package declares.
    """

    calls = 0

    #: What the second panel declares. Overridden below by the variant that
    #: needs a declaration a rule will fail, so that a failure's evidence has a
    #: real source photograph to be traced to.
    declaration = ("Net Qty: 500 g", {"quantity": 500, "unit": "g"})

    def run(self, image: ImageRef) -> ExtractionResult:
        index = type(self).calls
        type(self).calls += 1

        if index == 0:
            text = "GARDEN FRESH BISCUITS"
            fields = ()
        else:
            text, normalised = type(self).declaration
            fields = (
                ExtractedField(
                    key=LabelFieldKey.NET_QUANTITY,
                    raw_value=text,
                    normalized_value=normalised,
                    confidence=0.88,
                    box=BoundingBox(x=8, y=40, width=260, height=20),
                ),
            )

        return ExtractionResult(
            status=ExtractionStatus.COMPLETED,
            engine_name=self.name,
            engine_version=self.version,
            processing_ms=12,
            ocr=OcrResult(
                blocks=(
                    TextBlock(
                        text=text,
                        box=BoundingBox(x=8, y=40, width=260, height=20),
                        confidence=0.88,
                    ),
                ),
                raw={"panel": index},
            ),
            fields=fields,
            metadata={"unread_declarations": []},
        )


class _NonSiDeclarationPipeline(_SplitDeclarationPipeline):
    """The same split package, declared in pounds.

    Rule 13(5) permits no system of units other than SI for the net quantity,
    so `si_unit` fails this - and the failure is drawn *from the reading*,
    which is what gives its evidence a source photograph to cite.
    """

    calls = 0
    declaration = ("Net Qty: 1.1 lb", {"quantity": 1.1, "unit": "lb"})


@pytest.fixture(autouse=True)
def _register_split_pipelines(settings):
    registered = set(registry.available_pipelines())

    def _ensure(name, cls):
        if (name, _TEST_VERSION) not in registered:
            registry.register_pipeline(
                name,
                _TEST_VERSION,
                lambda cls=cls, name=name: cls(
                    name=name,
                    version=_TEST_VERSION,
                    ocr_engine=_UnusedOcrEngine(),
                ),
            )

    _ensure(_SPLIT_PIPELINE, _SplitDeclarationPipeline)
    _ensure(_NON_SI_PIPELINE, _NonSiDeclarationPipeline)
    _SplitDeclarationPipeline.calls = 0
    _NonSiDeclarationPipeline.calls = 0
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _SPLIT_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION
    yield
    _SplitDeclarationPipeline.calls = 0
    _NonSiDeclarationPipeline.calls = 0


@pytest.fixture
def non_si_panel(settings):
    """Swap in the package whose net quantity is declared in pounds."""
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _NON_SI_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    settings.DEMO_PUBLIC_ANALYSIS_API = True


def _uploads(png_bytes, count=2):
    return [
        SimpleUploadedFile(f"panel-{index}.png", png_bytes, content_type="image/png")
        for index in range(1, count + 1)
    ]


# --- one inspection, one result ----------------------------------------------


def test_two_photographs_produce_one_compliance_check(
    png_bytes, media_root, category, make_rule
):
    make_rule("LMPC-NET-QTY-001", field_key="net_quantity")

    outcome = analysis_service.analyse_uploads(_uploads(png_bytes), category=category)

    assert ComplianceCheck.objects.count() == 1
    assert ExtractionRun.objects.count() == 1
    assert outcome.check.extraction_run_id == outcome.run.pk
    assert len(outcome.images) == 2


def test_a_declaration_on_the_second_panel_satisfies_the_rule(
    png_bytes, media_root, category, make_rule
):
    """The point of the whole feature.

    Photograph 1 shows no net quantity. Judged alone it would be a failure -
    and it would be a *wrong* failure, because the package does declare one, on
    the panel in photograph 2.
    """
    make_rule("LMPC-NET-QTY-001", field_key="net_quantity")

    outcome = analysis_service.analyse_uploads(_uploads(png_bytes), category=category)

    finding = outcome.check.findings.get(rule_code="LMPC-NET-QTY-001")
    assert finding.status == "passed"
    assert outcome.check.rules_failed == 0
    assert outcome.check.violations.count() == 0


def test_the_same_package_photographed_only_from_the_front_still_fails(
    png_bytes, media_root, category, make_rule
):
    """The control for the test above.

    Without the second panel the declaration genuinely was not read, and the
    engine says so. If this passed too, the previous test would be proving
    nothing about the set.
    """
    make_rule("LMPC-NET-QTY-001", field_key="net_quantity")

    outcome = analysis_service.analyse_uploads(
        _uploads(png_bytes, count=1), category=category
    )

    finding = outcome.check.findings.get(rule_code="LMPC-NET-QTY-001")
    assert finding.status == "failed"


def test_nothing_evaluates_a_photograph_on_its_own(
    png_bytes, media_root, category, make_rule
):
    """No per-photograph checks are created anywhere along the way."""
    make_rule("LMPC-NET-QTY-001", field_key="net_quantity")

    analysis_service.analyse_uploads(_uploads(png_bytes, count=3), category=category)

    assert ComplianceCheck.objects.count() == 1


# --- evidence keeps its photograph -------------------------------------------


def test_a_finding_links_to_the_reading_it_used(
    png_bytes, media_root, category, make_rule
):
    make_rule("LMPC-NET-QTY-001", field_key="net_quantity")

    outcome = analysis_service.analyse_uploads(_uploads(png_bytes), category=category)
    finding = outcome.check.findings.get(rule_code="LMPC-NET-QTY-001")

    assert finding.extracted_field is not None
    # Read off the second panel, and the link says so.
    assert finding.extracted_field.image_id == outcome.images[1].pk


def test_evidence_for_a_failure_cites_the_photograph_its_reading_came_from(
    png_bytes, media_root, category, make_rule, non_si_panel
):
    """A bounding box measured on the back panel must not be drawn on the front.

    `si_unit` fails a net quantity declared in pounds, and the failure is drawn
    from the reading - so its evidence has a real source photograph rather than
    an absence to fall back on.
    """
    make_rule("LMPC-QTY-UNIT-001", check_type="si_unit", parameters={})

    outcome = analysis_service.analyse_uploads(_uploads(png_bytes), category=category)

    evidence = ComplianceEvidence.objects.get(
        violation__compliance_check=outcome.check
    )
    assert evidence.image_id == outcome.images[1].pk
    assert evidence.image_id != outcome.run.image_id


def test_evidence_for_an_absence_falls_back_to_the_primary_photograph(
    png_bytes, media_root, category, make_rule
):
    """There is no reading to have a source, so no panel is more the evidence.

    The fallback is the primary photograph, and it is explicitly not a claim
    that the declaration should have been on that panel.
    """
    make_rule("LMPC-MFG-DATE-001", field_key="date_of_manufacture")

    outcome = analysis_service.analyse_uploads(_uploads(png_bytes), category=category)

    evidence = ComplianceEvidence.objects.get(
        violation__compliance_check=outcome.check
    )
    assert evidence.extracted_field is None
    assert evidence.image_id == outcome.run.image_id
    assert evidence.image_id == outcome.images[0].pk


# --- the result, as a client receives it --------------------------------------


def test_the_result_says_how_many_photographs_it_was_made_from(
    client, png_bytes, media_root, category, make_rule
):
    make_rule("LMPC-NET-QTY-001", field_key="net_quantity")

    response = client.post(
        reverse("v1:image-analyse"),
        {"image": _uploads(png_bytes, count=3), "category_code": category.code},
        format="multipart",
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["images"]) == 3
    assert [entry["position"] for entry in body["images"]] == [1, 2, 3]
    # One verdict for the set, never three.
    assert isinstance(body["result"], str)
    assert body["image"]["id"] == body["images"][0]["image"]["id"]


def test_the_result_carries_the_photograph_behind_each_piece_of_evidence(
    client, png_bytes, media_root, category, make_rule, non_si_panel
):
    make_rule("LMPC-QTY-UNIT-001", check_type="si_unit", parameters={})

    body = client.post(
        reverse("v1:image-analyse"),
        {"image": _uploads(png_bytes), "category_code": category.code},
        format="multipart",
    ).json()

    second_image_id = body["images"][1]["image"]["id"]
    evidence = body["violations"][0]["evidence"][0]
    assert evidence["image_id"] == second_image_id


def test_a_single_image_result_still_carries_one_image_entry(
    client, png_bytes, media_root, category, make_rule
):
    """The contract a client written before image sets relies on, unchanged."""
    make_rule("LMPC-NET-QTY-001", field_key="net_quantity")

    body = client.post(
        reverse("v1:image-analyse"),
        {
            "image": SimpleUploadedFile(
                "label.png", png_bytes, content_type="image/png"
            ),
            "category_code": category.code,
        },
        format="multipart",
    ).json()

    assert body["image"] is not None
    assert len(body["images"]) == 1
    assert body["images"][0]["image"]["id"] == body["image"]["id"]
