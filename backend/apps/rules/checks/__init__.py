"""Registry of rule validators.

A `ComplianceRule.check_type` names one of these. Each validator answers a
narrow, mechanical question about extracted data and returns a `CheckOutcome`.

The split that matters: a validator asks a *factual* question ("was this
declaration found?"). The rule row supplies the *legal* claim ("this
declaration is required for this commodity"). Neither is useful alone, and
keeping them apart is what lets us ship working machinery with zero legal
content - which is exactly the state of this branch.

A check registers **two** callables together: the validator, and a validator
for its own `parameters`. Bundling them is deliberate. Parameter validation
used to live in the rule loader behind `if check_type != "field_presence"`,
which meant every check type added later would silently receive no validation
at all, and a typo in a rule file would surface only when a real product was
being evaluated. Registering them as a pair makes that impossible to forget:
adding a check type is one self-contained module.

Adding a validator
------------------
1. Write a module here exposing a `Validator` and a `ParameterValidator`.
2. Register both in `_register_builtin_checks()` below.
3. Document the `parameters` shape in `rules/SCHEMA.md`.

The loader rejects rule files naming an unregistered `check_type`, so a typo
fails at load time rather than silently skipping a rule at evaluation time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from apps.rules.checks.base import (
    CheckContext,
    CheckOutcome,
    CheckStatus,
    InvalidCheckParameters,
)

#: Evaluates a rule against extracted data. Must not raise for ordinary
#: "did not match" cases - those are a FAILED or INCONCLUSIVE outcome.
Validator = Callable[[dict, CheckContext], CheckOutcome]

#: Validates a rule's `parameters` at load time. Raises InvalidCheckParameters
#: with a message naming the offending key. Returns None.
ParameterValidator = Callable[[dict], None]


@dataclass(frozen=True)
class CheckSpec:
    """Everything the system knows about one check type."""

    check_type: str
    validator: Validator
    parameter_validator: ParameterValidator
    description: str


#: Check types named in the project plan but not implemented yet. Listed only
#: so the rule loader can tell an author "planned, not yet available" instead
#: of "unknown check_type", which reads like a typo. Nothing here is
#: registered, callable, or usable - a rule naming one of these is rejected.
PLANNED_CHECK_TYPES: dict[str, str] = {
    "value_check": "Compare a declaration against an expected value.",
    "format_check": "Validate the shape of a declaration (date format, units).",
    "numeric_check": "Range and arithmetic checks on numeric declarations.",
    "conditional_check": "Apply a check only when another condition holds.",
    "visual_check": (
        "Measure rendered properties such as declaration height. Uses "
        "CheckContext.image and ExtractedLabelField.bounding_box."
    ),
}

_CHECKS: dict[str, CheckSpec] = {}


class UnknownCheckTypeError(KeyError):
    """Raised when a rule names a validator that is not registered."""


def register_check(
    check_type: str,
    validator: Validator,
    *,
    parameter_validator: ParameterValidator | None = None,
    description: str = "",
) -> None:
    """Register `validator` under `check_type`.

    `parameter_validator` defaults to one that accepts anything. Supply a real
    one for any check that reads a parameter - it is the only thing standing
    between a typo in a rule file and a rule that never matches.

    Raises:
        ValueError: something is already registered under this name. Silently
            replacing would make behaviour depend on import order.
    """
    if check_type in _CHECKS:
        raise ValueError(f"Check type already registered: {check_type}")
    _CHECKS[check_type] = CheckSpec(
        check_type=check_type,
        validator=validator,
        parameter_validator=parameter_validator or _accept_any_parameters,
        description=description,
    )


def get_check(check_type: str) -> Validator:
    """Return the validator for `check_type`.

    Raises:
        UnknownCheckTypeError: nothing is registered under this name.
    """
    return get_spec(check_type).validator


def get_spec(check_type: str) -> CheckSpec:
    """Return the full registration for `check_type`.

    Raises:
        UnknownCheckTypeError: nothing is registered under this name.
    """
    try:
        return _CHECKS[check_type]
    except KeyError:
        raise UnknownCheckTypeError(
            f"Unknown check_type {check_type!r}. Registered: {sorted(_CHECKS)}"
        ) from None


def validate_parameters(check_type: str, parameters: dict) -> None:
    """Validate `parameters` for `check_type`.

    Called by the rule loader so a malformed rule is rejected at load time
    rather than at evaluation time, when it would be attached to a real
    product's compliance result.

    Raises:
        UnknownCheckTypeError: the check type is not registered.
        InvalidCheckParameters: the parameters are wrong for this check.
    """
    get_spec(check_type).parameter_validator(parameters)


def available_check_types() -> Iterator[str]:
    yield from sorted(_CHECKS)


def is_registered(check_type: str) -> bool:
    return check_type in _CHECKS


def _accept_any_parameters(parameters: dict) -> None:
    """Default parameter validator for checks that take no parameters."""


def _register_builtin_checks() -> None:
    from apps.rules.checks.field_presence import (
        check_field_presence,
        validate_field_presence_parameters,
    )

    register_check(
        "field_presence",
        check_field_presence,
        parameter_validator=validate_field_presence_parameters,
        description="Was this declaration found in the extracted label data?",
    )


_register_builtin_checks()

__all__ = [
    "CheckContext",
    "CheckOutcome",
    "CheckSpec",
    "CheckStatus",
    "InvalidCheckParameters",
    "PLANNED_CHECK_TYPES",
    "ParameterValidator",
    "UnknownCheckTypeError",
    "Validator",
    "available_check_types",
    "get_check",
    "get_spec",
    "is_registered",
    "register_check",
    "validate_parameters",
]
