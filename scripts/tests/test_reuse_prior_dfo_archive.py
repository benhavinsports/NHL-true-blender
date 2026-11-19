"""GitHub evidence fallback must preserve source provenance, not invent starters."""
from datetime import date, timedelta

from scripts.reuse_prior_dfo_archive import select_prior_capture, CAPTURE_RUN


def fixtures():
    start = date(2026, 9, 29)
    days = [(start + timedelta(days=i)).isoformat() for i in range(50)]
    assert days[-1] == "2026-11-17"
    manifest = {"start": days[0], "end": days[-1], "scheduledDates": days}
    prior = {
        "source": "Daily Faceoff dated historical starting-goalie pages",
        "dateRange": [days[0], days[-1]], "scheduledDatesChecked": 50,
        "accessibleDatedPages": 50, "completeGamePairs": 331,
        "pages": [
            {"date": d, "url": f"https://www.dailyfaceoff.com/starting-goalies/{d}",
             "httpStatus": 200, "availableAsDatedHistoricalPage": True,
             "pageSha256": "a" * 64, "games": []}
            for d in days],
    }
    return manifest, prior


def test_recovered_source_retains_original_dated_pages_and_capture_identity():
    manifest, prior = fixtures()
    recovered = select_prior_capture({"accessibleDatedPages": 0}, prior, manifest)
    assert recovered["pages"] == prior["pages"]
    assert recovered["priorEvidenceCaptureRunId"] == CAPTURE_RUN
    assert recovered["notCurrentLiveProviderObservation"] is True
    assert recovered["providerOutageDidNotReplaceOriginalReportTimestamps"] is True


def test_never_overrides_a_successful_present_collection():
    manifest, prior = fixtures()
    assert select_prior_capture({"accessibleDatedPages": 1}, prior, manifest) is None


def test_rejects_partial_wrong_date_or_unverified_source():
    manifest, prior = fixtures()
    assert select_prior_capture({}, {**prior, "pages": prior["pages"][:-1]}, manifest) is None
    assert select_prior_capture({}, {**prior, "source": "unverified"}, manifest) is None
    bad = dict(manifest, end="2026-11-18")
    assert select_prior_capture({}, prior, bad) is None
    malformed = dict(prior)
    malformed["pages"] = [dict(x) for x in prior["pages"]]
    malformed["pages"][0]["pageSha256"] = None
    assert select_prior_capture({}, malformed, manifest) is None
