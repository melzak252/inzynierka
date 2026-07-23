from betting_app.core.matching import normalize_team_name, similarity


def test_normalize_esports_suffix_spelled_as_e_sports() -> None:
    assert normalize_team_name("Estral E-Sports") == "estral"
    assert normalize_team_name("Estral Esports") == "estral"
    assert similarity("Estral E-Sports", "Estral Esports") == 1.0


def test_normalize_ub_alma_mater_alias() -> None:
    assert normalize_team_name("UB Alma Mater") == "universitat de barcelona"
    assert normalize_team_name("Universitat de Barcelona") == "universitat de barcelona"
    assert similarity("UB Alma Mater", "Universitat de Barcelona") == 1.0


def test_normalize_kabum_ild_alias() -> None:
    assert normalize_team_name("KaBuM! Ilha das Lendas") == "kabum idl"
    assert normalize_team_name("KaBuM! IDL") == "kabum idl"
    assert similarity("KaBuM! Ilha das Lendas", "KaBuM! IDL") == 1.0
