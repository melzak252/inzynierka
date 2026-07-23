from betting_app.scrapers.golgg import score_for_link_order


def test_score_for_link_order_handles_golgg_abbrev_vs_full_name_reversed_result_cells() -> None:
    team_a_score, team_b_score = score_for_link_order(
        team_a="BLG",
        team_b="T1",
        result_left_team="T1",
        result_right_team="Bilibili Gaming",
        score_left=2,
        score_right=3,
        won="Bilibili Gaming",
    )

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
