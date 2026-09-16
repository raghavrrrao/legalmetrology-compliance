"""The classifier's text preparation: deterministic, and destroys nothing.

Two properties are pinned. `preprocess_text` may change encoding, case and
whitespace and nothing else - every unit, number, abbreviation and symbol a
label prints must survive it, because the same text is what the evidence
signals match against and what a reviewer reads. `feature_tokens` is the one
abstraction step, and its only abstraction is digits to a placeholder.
"""

from __future__ import annotations

import pytest

from labelextract.classification.preprocessing import (
    NUMBER_TOKEN,
    TOKENISER_VERSION,
    feature_tokens,
    ngram_features,
    preprocess_text,
    word_tokens,
)

# --- preprocess_text ----------------------------------------------------------


def test_lowercases_and_collapses_whitespace():
    assert preprocess_text("  Net   Qty:\n\n 500 g \t MRP ") == "net qty: 500 g mrp"


def test_line_breaks_become_single_spaces():
    assert preprocess_text("NUTRITIONAL\r\nINFORMATION\nIngredients") == (
        "nutritional information ingredients"
    )


@pytest.mark.parametrize(
    "token",
    ["fssai", "mrp", "15n tablets", "120 g", "200 ml", "₹350.00", "ins 330",
     "b12", "25°c", "e-mail", "care@shinexpro.in", "1800-10-22-221", "4.2g"],
)
def test_product_relevant_tokens_survive(token):
    """Units, numbers, abbreviations, symbols: kept verbatim (lowercased)."""
    assert token in preprocess_text(f"HEADER {token.upper()} FOOTER")


def test_nfkc_folds_presentation_forms():
    # Full-width digits, a ligature and a no-break space all fold to ASCII.
    assert preprocess_text("５００ g ﬁne print") == "500 g fine print"


def test_typographic_quotes_and_dashes_become_ascii():
    assert preprocess_text("‘MRP’ “x” – y — z") == "'mrp' \"x\" - y - z"


def test_invisible_characters_are_removed():
    assert preprocess_text("net​qty﻿") == "netqty"


def test_devanagari_is_preserved_not_stripped():
    text = "नेमो नमकीन Net Weight 500g"
    cleaned = preprocess_text(text)
    assert cleaned.startswith("नेमो नमकीन")
    assert "net weight 500g" in cleaned


def test_does_not_repair_ocr_errors():
    """`O` is not turned into `0` and `l` is not turned into `1`."""
    assert preprocess_text("5OO g, l5N TABLETS") == "5oo g, l5n tablets"


@pytest.mark.parametrize("value", [None, "", "   ", "\n\t"])
def test_empty_inputs_give_empty_string(value):
    assert preprocess_text(value) == ""


def test_non_string_input_is_coerced_not_refused():
    assert preprocess_text(123) == "123"


def test_is_deterministic_and_idempotent():
    text = "  Nutritional ‘Information’\n Net Qty: 15N TABLETS  "
    once = preprocess_text(text)
    assert preprocess_text(text) == once
    assert preprocess_text(once) == once


# --- tokens ---------------------------------------------------------------------


def test_word_tokens_split_letters_from_digits():
    assert word_tokens(preprocess_text("500g 15N B12 e330")) == [
        "500", "g", "15", "n", "b", "12", "e", "330",
    ]


def test_word_tokens_drop_punctuation_but_keep_every_word():
    assert word_tokens("mrp: ₹349.00 (incl. of all taxes)") == [
        "mrp", "349", "00", "incl", "of", "all", "taxes",
    ]


def test_feature_tokens_replace_every_digit_run_with_the_placeholder():
    assert feature_tokens("net qty 500 g mrp 349.00") == [
        "net", "qty", NUMBER_TOKEN, "g", "mrp", NUMBER_TOKEN, NUMBER_TOKEN,
    ]


def test_feature_tokens_keep_units_next_to_their_numbers():
    """The information is the unit and its neighbour, not the digits."""
    tokens = feature_tokens("net quantity 120 g (125 ml)")
    assert tokens[-4:] == [NUMBER_TOKEN, "g", NUMBER_TOKEN, "ml"]


def test_placeholder_cannot_collide_with_a_word_token():
    assert NUMBER_TOKEN not in word_tokens(NUMBER_TOKEN)


def test_ngram_features_produce_unigrams_then_bigrams():
    assert ngram_features("net qty 500 g", (1, 2)) == [
        "net", "qty", NUMBER_TOKEN, "g",
        "net qty", f"qty {NUMBER_TOKEN}", f"{NUMBER_TOKEN} g",
    ]


def test_ngram_features_on_empty_text_is_empty():
    assert ngram_features("", (1, 2)) == []


@pytest.mark.parametrize("bad", [(0, 1), (2, 1), (1, 0)])
def test_ngram_features_reject_a_bad_range(bad):
    with pytest.raises(ValueError):
        ngram_features("a b", bad)


def test_tokeniser_version_is_a_non_empty_string():
    """The artifact pins this; a blank version would pin nothing."""
    assert isinstance(TOKENISER_VERSION, str) and TOKENISER_VERSION
