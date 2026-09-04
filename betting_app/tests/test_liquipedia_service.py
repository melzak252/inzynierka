"""Tests for Liquipedia client and best_of synchronizer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from betting_app.services.liquipedia_service import LiquipediaClient, LiquipediaMatch, sync_liquipedia_best_of

SAMPLE_LIQUIPEDIA_HTML = """
<div class="match-info">
  <span class="timer-object" data-timestamp="1788508800">September 4, 2026 - 17:00 KST</span>
  <div class="match-info-header">
    <div class="match-info-header-opponent match-info-header-opponent-left">
      [[File:KT.png|100x50px|link=KT Rolster]] [[KT Rolster|KT]]
    </div>
    <div class="match-info-header-scoreholder">
      1 : 0 (Bo5)
    </div>
    <div class="match-info-header-opponent">
      [[File:DK.png|100x50px|link=Dplus]] [[Dplus|DK]]
    </div>
  </div>
  <div class="match-info-tournament">
    [[File:LCK.png|50x50px|link=LCK/2026/Playoffs#Playoffs]] [[LCK/2026/Playoffs#Playoffs|LCK 2026 - Playoffs]]
  </div>
</div>
<div class="match-info">
  <span class="timer-object" data-timestamp="1788512400">September 4, 2026 - 17:00 CST</span>
  <div class="match-info-header">
    <div class="match-info-header-opponent match-info-header-opponent-left">
      [[File:AL.png]] [[Anyone's Legend|AL]]
    </div>
    <div class="match-info-header-scoreholder">
      vs (Bo3)
    </div>
    <div class="match-info-header-opponent">
      [[File:LGD.png]] [[LGD Gaming|LGD]]
    </div>
  </div>
  <div class="match-info-tournament">
    [[LPL/2026/Split 3|LPL 2026]]
  </div>
</div>
"""


def test_liquipedia_client_parses_matches_html() -> None:
    client = LiquipediaClient()
    matches = client._parse_matches_html(SAMPLE_LIQUIPEDIA_HTML)

    assert len(matches) == 2

    m1 = matches[0]
    assert m1.team1 == "KT Rolster"
    assert m1.team2 == "Dplus"
    assert m1.best_of == 5
    assert m1.tournament == "LCK 2026 - Playoffs"
    assert m1.start_time == datetime.fromtimestamp(1788508800, tz=UTC)

    m2 = matches[1]
    assert m2.team1 == "Anyone's Legend"
    assert m2.team2 == "LGD Gaming"
    assert m2.best_of == 3
    assert m2.tournament == "LPL 2026"
    assert m2.start_time == datetime.fromtimestamp(1788512400, tz=UTC)


def test_clean_team_text() -> None:
    assert LiquipediaClient._clean_team_text("[[File:Logo.png]] [[T1|SKT]]") == "T1"
    assert LiquipediaClient._clean_team_text("[[G2 Esports]]") == "G2 Esports"
    assert LiquipediaClient._clean_team_text("Fnatic") == "Fnatic"


@patch("betting_app.services.liquipedia_service.LiquipediaClient.fetch_recent_and_upcoming_matches")
@patch("betting_app.services.liquipedia_service.connect")
@patch("betting_app.services.liquipedia_service.transaction")
def test_sync_liquipedia_best_of_updates_divergent_matches(
    mock_transaction: MagicMock,
    mock_connect: MagicMock,
    mock_fetch: MagicMock,
) -> None:
    mock_fetch.return_value = [
        LiquipediaMatch(
            team1="KT Rolster",
            team2="Dplus KIA",
            best_of=5,
            tournament="LCK",
            start_time=datetime.now(tz=UTC),
        ),
        LiquipediaMatch(
            team1="Fnatic",
            team2="G2 Esports",
            best_of=3,
            tournament="LEC",
            start_time=datetime.now(tz=UTC),
        ),
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "id": 101,
            "normalized_team_a": "kt-rolster",
            "normalized_team_b": "dplus-kia",
            "best_of": 1,  # Needs update to 5
            "status": "upcoming",
        },
        {
            "id": 102,
            "normalized_team_a": "fnatic",
            "normalized_team_b": "g2-esports",
            "best_of": 3,  # Already 3
            "status": "upcoming",
        },
    ]
    mock_connect.return_value.__enter__.return_value = mock_conn

    mock_tx_conn = MagicMock()
    mock_transaction.return_value.__enter__.return_value = mock_tx_conn

    res = sync_liquipedia_best_of(limit=10)

    assert res["fetched"] == 2
    assert res["matched"] == 2
    assert res["updated"] == 1

    mock_tx_conn.execute.assert_called_once_with(
        "UPDATE canonical_matches SET best_of = ? WHERE id = ?",
        (5, 101),
    )
