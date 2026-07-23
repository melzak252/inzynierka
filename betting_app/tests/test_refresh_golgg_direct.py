from datetime import datetime

from betting_app.scripts.refresh_golgg_direct import select_recent_existing_matches


def test_select_recent_existing_matches_picks_only_known_recent_matches() -> None:
    matches = [
        {"match_id": "old", "date": "2026-05-01"},
        {"match_id": "recent", "date": "2026-07-04"},
        {"match_id": "new", "date": "2026-07-04"},
    ]

    selected = select_recent_existing_matches(
        matches,
        {"old", "recent"},
        days=45,
        now=datetime(2026, 7, 23),
    )

    assert [match["match_id"] for match in selected] == ["recent"]
