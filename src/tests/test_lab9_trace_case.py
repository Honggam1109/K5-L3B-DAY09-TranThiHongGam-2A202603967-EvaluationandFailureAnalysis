"""Regression test from docs/trace_case.md: seeded_regression C-002@11 (FM-03, ticket_trust).

First wrong step = event 3 `model_override {"delay_days": 5}` while the DB says 2 (event 2).
DbFactKept must flag it and RefundAmountCorrect must see the 20.000đ ledger row; both pass on `fixed`.
"""
import pytest

pytestmark = pytest.mark.student
CLAIM, SEED = "C-002", 11


def _grade(shape):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders, trace_case

    case = trace_case.investigate(shape, CLAIM, SEED)
    ctx = EvaluatorContext(name=f"{shape}:{CLAIM}@{SEED}", inputs={}, metadata=None,
                           expected_output=case["label"], output=case["trial"], duration=0.0,
                           _span_tree=None, attributes={}, metrics={})
    return case["trial"], {name: cls().evaluate(ctx).value for name, cls in graders.GRADERS.items()}


def test_lab9_trace_case_c002_seeded_regression_is_caught():
    trial, got = _grade("seeded_regression")
    kinds = [e.get("kind") for e in trial["events"]]
    first_override = kinds.index("model_override")
    assert kinds[:first_override] == ["handoff", "investigator"]   # steps 1-2 are still right
    assert trial["events"][first_override]["payload"] == {"delay_days": 5}
    assert got["db_fact_kept"] is False
    assert got["refund_amount_correct"] is False
    assert got["pass_rate"] is False


def test_lab9_trace_case_c002_fixed_passes():
    trial, got = _grade("fixed")
    assert "model_override" not in [e.get("kind") for e in trial["events"]]
    assert got["db_fact_kept"] is True
    assert got["refund_amount_correct"] is True
    assert got["reply_matches_ledger"] is True
    assert got["pass_rate"] is True
