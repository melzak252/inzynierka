import os

from betting_app.core.db import dispose_engine, init_db
from betting_app.scrapers.golgg import score_for_link_order
from betting_app.services.mapping_service import upsert_alias


def _init_tmp_db(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'golgg_aliases.sqlite3'}"
    dispose_engine()
    init_db()


def test_score_for_link_order_handles_golgg_abbrev_vs_full_name_reversed_result_cells(tmp_path) -> None:
    _init_tmp_db(tmp_path)
    try:
        upsert_alias(
            "BLG",
            "Bilibili Gaming",
            source="golgg-short",
            source_system="golgg",
            league_pattern="MSI",
        )
        team_a_score, team_b_score = score_for_link_order(
            team_a="BLG",
            team_b="T1",
            result_left_team="T1",
            result_right_team="Bilibili Gaming",
            score_left=2,
            score_right=3,
            won="Bilibili Gaming",
            tournament_name="MSI 2026",
        )
    finally:
        os.environ.pop("DATABASE_URL", None)
        dispose_engine()

    assert (team_a_score, team_b_score) == (3, 2)


def test_score_for_link_order_keeps_matching_result_cell_order() -> None:
    team_a_score, team_b_score = score_for_link_order(
        team_a="T1",
        team_b="Team Liquid",
        result_left_team="T1",
        result_right_team="Team Liquid",
        score_left=1,
        score_right=0,
        won="T1",
    )

    assert (team_a_score, team_b_score) == (1, 0)
