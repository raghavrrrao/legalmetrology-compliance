"""Deterministic text preparation for the product classifier.

Two functions, and the boundary between them is deliberate:

    preprocess_text    OCR text  -> cleaned text    (what a reviewer sees)
    feature_tokens     cleaned   -> feature strings (what the model sees)

`preprocess_text` changes *encoding and layout* only: Unicode form, a handful
of typographic characters, case, whitespace. It keeps every number, unit,
abbreviation and symbol - `FSSAI`, `MRP`, `15N TABLETS`, `120 g`, `200 ml`,
`₹` all survive it, because the cleaned text is also the text the evidence
signals are matched against and the text a person reads to check a
classification. Nothing here repairs OCR errors: mapping `O` to `0` would
turn an unreliable reading into a confident wrong one, and the classifier is
expected to cope with noise rather than have it hidden.

`feature_tokens` is the abstraction step, and it is the only one. It splits
the cleaned text into word tokens and replaces every run of digits with a
single placeholder, so that `net quantity 500 g` and `net quantity 120 g`
produce the same bigram. The exact digits of a price, a licence number, a
batch code or a phone number say nothing about what kind of product this is,
and keeping them would give the model one feature per product that never
recurs. The placeholder keeps the fact that a number was there and what it
was next to, which is what carries information (`<num> g`, `<num> ml`,
`<num> tablets`, `<num> kcal`).

Both functions are pure and deterministic. The trainer and the classifier
call the same two functions on the same text, and the artifact records the
version of this module so a model is never scored against a tokenisation it
was not trained with.
"""

from __future__ import annotations

import re
import unicodedata

#: Bump whenever `preprocess_text` or `feature_tokens` changes behaviour. The
#: artifact records it; a mismatch refuses to load rather than silently
#: scoring a model against features it never saw.
TOKENISER_VERSION = "1"

#: The token every run of digits becomes. Chosen so it cannot collide with a
#: word token: `_TOKEN` never matches `<` or `>`.
NUMBER_TOKEN = "<num>"

#: Typographic characters OCR emits that carry no meaning of their own and
#: that NFKC leaves alone. Mapped after normalisation, before lowercasing.
#: Written as escapes so the invisible ones are visible in the source.
_TYPOGRAPHIC = str.maketrans(
    {
        "\u2018": "'",  # left single quotation mark
        "\u2019": "'",  # right single quotation mark
        "\u201a": "'",  # single low-9 quotation mark
        "\u201b": "'",  # single high-reversed-9 quotation mark
        "\u201c": '"',  # left double quotation mark
        "\u201d": '"',  # right double quotation mark
        "\u201e": '"',  # double low-9 quotation mark
        "\u201f": '"',  # double high-reversed-9 quotation mark
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2015": "-",  # horizontal bar
        "\u2026": " ",  # horizontal ellipsis
        "\u200b": "",  # zero-width space
        "\ufeff": "",  # byte-order mark
    }
)

_WHITESPACE = re.compile(r"\s+")

#: A word token: a run of letters or digits in any script. Underscore is
#: excluded from `\w` on purpose; it is punctuation here, not a letter.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

#: Splits a token at letter/digit boundaries: `500g` -> `500`, `g`;
#: `15n` -> `15`, `n`; `b12` -> `b`, `12`.
_LETTERS_OR_DIGITS = re.compile(r"\d+|[^\W\d_]+", re.UNICODE)


def preprocess_text(text: str | None) -> str:
    """Return `text` normalised for classification. Never raises on bad input.

    Steps, in order, each of them reversible in meaning if not in bytes:

    1. NFKC normalisation - full-width digits, ligatures and presentation
       forms fold onto their canonical characters. A change of encoding, not
       of content.
    2. A small table of typographic quotes, dashes and invisible characters
       becomes their plain equivalent.
    3. Lowercase.
    4. Every run of whitespace, including line breaks, becomes one space, and
       the result is stripped.

    `None`, an empty string, or a string of only whitespace returns `""`.
    A non-string is coerced with `str()` rather than refused, because the
    classifier is a secondary observation and must not fail a reading over
    the type of a diagnostic.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TYPOGRAPHIC)
    text = text.lower()
    return _WHITESPACE.sub(" ", text).strip()


def word_tokens(cleaned: str) -> list[str]:
    """The word tokens of already-preprocessed text, digits kept verbatim.

    Used to measure how much text there is (the "insufficient text" guard)
    and by tests that want to see what the tokeniser did before abstraction.
    """
    tokens: list[str] = []
    for token in _TOKEN.findall(cleaned):
        tokens.extend(_LETTERS_OR_DIGITS.findall(token))
    return tokens


def feature_tokens(cleaned: str) -> list[str]:
    """The unigram feature stream of preprocessed text.

    `word_tokens` with every all-digit token replaced by `NUMBER_TOKEN`.
    Order is preserved so n-grams can be formed from it.
    """
    return [
        NUMBER_TOKEN if token.isdigit() else token
        for token in word_tokens(cleaned)
    ]


def ngram_features(cleaned: str, ngram_range: tuple[int, int]) -> list[str]:
    """Unigrams through n-grams of `feature_tokens`, space-joined.

    This is the analyzer both the trainer and the classifier use, so the
    feature space is defined in exactly one place. Produces the same strings
    scikit-learn's word n-gram analyzer would for the same token stream
    (`"a b"` for the bigram of `a` and `b`), which is what makes the exported
    vocabulary readable and the equivalence test meaningful.
    """
    tokens = feature_tokens(cleaned)
    low, high = ngram_range
    if low < 1 or high < low:
        raise ValueError(f"invalid ngram_range {ngram_range!r}")
    features: list[str] = []
    for n in range(low, high + 1):
        for start in range(len(tokens) - n + 1):
            features.append(" ".join(tokens[start:start + n]))
    return features
