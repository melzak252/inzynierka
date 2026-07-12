from betting_app.services.canonical_match_service import canonical_match_score, normalize_start_time


def _candidate(status: str, start_time: str) -> dict[str, str]:
    return {
        "normalized_team_a": "bilibili gaming",
        "normalized_team_b": "hanwha life esports",
        "start_time_normalized": start_time,
        "league": "MSI",
        "status": status,
    }


def test_identical_expired_match_with_different_start_time_is_not_boosted() -> None:
    score = canonical_match_score(
        "bilibili gaming",
        "hanwha life esports",
        "2026-07-12T07:30:00+00:00",
        "MSI",
        _candidate("expired", "2026-07-11T08:00:00+00:00"),
    )

    assert score < 0.78


def test_identical_upcoming_match_keeps_unstable_label_boost() -> None:
    score = canonical_match_score(
        "bilibili gaming",
        "hanwha life esports",
        "2026-07-12T07:30:00+00:00",
        "MSI",
        _candidate("upcoming", "2026-07-12T08:00:00+00:00"),
    )

    assert score >= 0.85


def test_identical_upcoming_match_days_apart_is_not_boosted() -> None:
    score = canonical_match_score(
        "bilibili gaming",
        "hanwha life esports",
        "2026-07-15T07:30:00+00:00",
        "MSI",
        _candidate("upcoming", "2026-07-12T07:30:00+00:00"),
    )

    assert score < 0.78


def test_polish_month_label_without_year_is_normalized() -> None:
    assert normalize_start_time("Śr 15. Lip, 11:20") == "2026-07-15T11:20:00+00:00"
