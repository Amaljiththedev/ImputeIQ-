"""Semantic roles, method routing precedence, and mechanism labelling."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.column_semantics import SemanticRole, get_columns_by_role
from app.core.diagnose_mechanism import diagnose
from app.core.imputation_engine import IMPUTERS
from app.core.method_router import route


# --------------------------------------------------------------------------
# Routing precedence: role is checked before mechanism
# --------------------------------------------------------------------------

def test_identifier_is_never_imputed_whatever_the_mechanism():
    for mechanism in ["MAR", "MCAR", "MNAR", "Ambiguous (MCAR/MNAR)", "Structural (event count)"]:
        d = route(mechanism, semantic_role="identifier")
        assert d.method == "flag_only", f"{mechanism} routed an identifier to {d.method}"


def test_categorical_uses_mode_not_median():
    for mechanism in ["MAR", "MCAR", "MNAR", "Ambiguous (MCAR/MNAR)"]:
        d = route(mechanism, semantic_role="categorical")
        assert d.method == "mode"


def test_role_beats_structural_zero_flag():
    """A lookup code that happens to look like a small-integer count must not
    be zero-filled just because the structural-zero heuristic matched."""
    d = route("MCAR", structural_zero_warning={"flag": "possible_structural_zero"},
              semantic_role="categorical")
    assert d.method == "mode"


def test_structural_zero_applies_to_continuous_columns():
    d = route("Ambiguous (MCAR/MNAR)",
              structural_zero_warning={"flag": "possible_structural_zero"},
              semantic_role="continuous")
    assert d.method == "zero"
    assert d.low_confidence is True


@pytest.mark.parametrize(
    "mechanism,expected_method",
    [("MCAR", "pmm"), ("MAR", "pmm"), ("MNAR", "median")],
)
def test_continuous_mechanism_routing(mechanism, expected_method):
    assert route(mechanism, semantic_role="continuous").method == expected_method


def test_mar_uses_the_conditional_model_not_an_unconditional_fill():
    """Regression test.

    MAR was routed to median. Median is unbiased only under MCAR (van Buuren
    2018, Table 1.1), so under MAR it biased the mean, the regression weights
    and the correlations -- in exactly the case where the diagnosis step had
    already named the observed driver that should have been conditioned on.
    """
    d = route("MAR (driver(s): smoking_status)", semantic_role="continuous")
    # Predictive mean matching: the stochastic regression row of Table 1.1,
    # drawing each imputation from an observed value so it cannot leave the
    # observed range. Sampling the posterior directly produced negative
    # clinical measurements on real data.
    assert d.method == "pmm"
    assert d.mechanism == "MAR"
    assert d.low_confidence is False


def test_mnar_keeps_a_transparent_baseline_and_stays_flagged():
    """No method is valid under MNAR, so the cautious path is retained rather
    than implying the conditional model has solved it."""
    d = route("MNAR", semantic_role="continuous")
    assert d.method == "median"
    assert d.low_confidence is True


def test_routing_rationale_is_sourced_rather_than_asserted():
    """The MAR rationale previously claimed empirical equivalence with MICE and
    cited nothing. Any rationale that makes a comparative claim must name a
    source."""
    for mechanism in ("MCAR", "MAR"):
        r = route(mechanism, semantic_role="continuous").rationale
        assert "van Buuren" in r, f"{mechanism} rationale cites no source"


def test_unresolved_mechanisms_take_the_cautious_path():
    """Ambiguous and Undetermined both mean the mechanism is not established,
    so neither may be routed as confidently MAR."""
    for label in ["Ambiguous (MCAR/MNAR)", "Undetermined (MAR or MNAR)"]:
        d = route(label, semantic_role="continuous")
        assert d.low_confidence is True, f"{label} was not flagged low confidence"


def test_route_always_returns_a_registered_imputer():
    labels = ["MCAR", "MAR", "MNAR", "Ambiguous (MCAR/MNAR)",
              "Undetermined (MAR or MNAR)", "Structural (event count)", "", "nonsense"]
    roles = [None, "continuous", "categorical", "identifier"]
    for label in labels:
        for role in roles:
            assert route(label, semantic_role=role).method in IMPUTERS


# --------------------------------------------------------------------------
# Semantic role classification
# --------------------------------------------------------------------------

def test_semantic_roles_split_ids_categories_and_measurements():
    n = 200
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "patid": [f"P{i:05d}" for i in range(n)],
        "gender": rng.choice(["M", "F"], n),
        "bmi": rng.normal(27, 4, n).round(1),
    })
    roles = get_columns_by_role(df)
    assert "patid" in roles[SemanticRole.IDENTIFIER]
    assert "gender" in roles[SemanticRole.CATEGORICAL]
    assert "bmi" in roles[SemanticRole.CONTINUOUS]


# --------------------------------------------------------------------------
# Mechanism labelling
# --------------------------------------------------------------------------

def test_strong_driver_is_detected_and_named_as_mar():
    n = 600
    rng = np.random.default_rng(1)
    smoking = rng.choice(["never", "current"], n, p=[0.6, 0.4])
    df = pd.DataFrame({
        "smoking_status": smoking,
        "systolic_bp": rng.normal(130, 15, n).round(1),
        "age": rng.normal(50, 10, n).round(1),
    })
    df.loc[(smoking == "current") & (rng.random(n) < 0.8), "systolic_bp"] = np.nan

    *_, drivers, detail = diagnose(df, "systolic_bp", ["systolic_bp", "age"], ["smoking_status"])
    assert "smoking_status" in drivers
    assert detail.startswith("MAR")


def test_no_driver_yields_an_unresolved_label_never_a_confident_mnar():
    """Regression test.

    The old third branch read "Likely MNAR (by elimination)". Concluding MNAR
    because no driver was found is not supportable: it is equally consistent
    with MAR on a variable that was never measured. Whichever branch is taken,
    the label must not assert MNAR.
    """
    n = 400
    rng = np.random.default_rng(2)
    df = pd.DataFrame({
        "a": rng.normal(0, 1, n),
        "b": rng.normal(0, 1, n),
        "grp": rng.choice(["x", "y"], n),
    })
    df.loc[rng.random(n) < 0.2, "a"] = np.nan  # purely random gaps

    *_, drivers, detail = diagnose(df, "a", ["a", "b"], ["grp"])
    assert drivers == []
    assert detail.startswith(("Ambiguous", "Undetermined"))
    assert "Likely MNAR" not in detail


def test_littles_flag_reports_failure_to_reject_not_confirmation():
    """The returned flag is `p > alpha`, i.e. we failed to reject MCAR. It must
    never be read as positive evidence for MCAR."""
    n = 300
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"a": rng.normal(0, 1, n), "b": rng.normal(0, 1, n)})
    df.loc[rng.random(n) < 0.15, "a"] = np.nan

    p, fails_to_reject, *_ = diagnose(df, "a", ["a", "b"], [])
    assert fails_to_reject == (p > 0.05)


# --------------------------------------------------------------------------
# Mechanism classes used for benchmark scoring
# --------------------------------------------------------------------------

def test_compound_labels_resolve_to_unresolved_not_a_mechanism():
    """Regression test, and the reason a fixed class set was introduced.

    "Ambiguous (MCAR/MNAR)" contains both "MCAR" and "MNAR" as substrings, so
    free-text comparison scored a column the tool had failed to classify as a
    correct answer against either ground truth. That produced accuracies of
    100%.
    """
    from app.core.diagnose_mechanism import MechanismClass, classify_mechanism
    for label in [
        "Ambiguous (MCAR/MNAR)",
        "Ambiguous: consistent with MCAR, MNAR not excluded (p=0.67)",
        "Undetermined (MAR or MNAR)",
        "Undetermined: MCAR rejected, no driver found among measured variables",
    ]:
        assert classify_mechanism(label) is MechanismClass.UNRESOLVED, label


@pytest.mark.parametrize("label,expected", [
    ("MAR", "MAR"),
    ("MAR (driver(s): smoking_status)", "MAR"),
    ("MCAR", "MCAR"),
    ("MNAR", "MNAR"),
    ("Structural (event count)", "STRUCTURAL"),
    ("Identifier (key/ID)", "IDENTIFIER"),
])
def test_confident_labels_map_to_their_mechanism(label, expected):
    from app.core.diagnose_mechanism import classify_mechanism
    assert classify_mechanism(label).value == expected


@pytest.mark.parametrize("label", ["mar", "  MAR  ", "Mar (driver(s): sex)"])
def test_classification_is_insensitive_to_case_and_spacing(label):
    """Comparing fixed classes also removes match failures caused purely by
    differences in wording or spelling."""
    from app.core.diagnose_mechanism import MechanismClass, classify_mechanism
    assert classify_mechanism(label) is MechanismClass.MAR


@pytest.mark.parametrize("label", [None, "", "   ", "something else entirely"])
def test_unrecognised_labels_are_other_not_silently_a_mechanism(label):
    from app.core.diagnose_mechanism import MechanismClass, classify_mechanism
    assert classify_mechanism(label) is MechanismClass.OTHER
