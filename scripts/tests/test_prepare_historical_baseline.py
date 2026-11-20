"""Regression guard for the pinned old G10.5 versus current replay dependencies."""
import pytest
from scripts.prepare_historical_baseline import (
    LEGACY, COMPAT, adapt_baseline_source,
)


def test_compatibility_accepts_new_context_without_using_it():
    old = (LEGACY + "\n"
           "    return candidate['goals'] > challengers[0]['goals']\n")
    updated = adapt_baseline_source(old)
    assert updated == old.replace(LEGACY, COMPAT)
    scope = {}
    exec(compile(updated, "<historical-baseline-fixture>", "exec"), scope)
    fn = scope["challenger_proof"]
    assert fn({"goals": 3}, [{"goals": 2}], {}, opponent_coverage={"tonight": True}) is True
    assert fn({"goals": 3}, [{"goals": 2}], {}, opponent_coverage={"tonight": False}) is True


def test_unknown_legacy_signature_fails_closed():
    with pytest.raises(ValueError, match="signature changed"):
        adapt_baseline_source("def challenger_proof(candidate, challengers): pass\n")


def test_inconsistent_legacy_contract_fails_closed():
    old = LEGACY + "\n    return opponent_coverage\n"
    with pytest.raises(ValueError, match="already uses"):
        adapt_baseline_source(old)
