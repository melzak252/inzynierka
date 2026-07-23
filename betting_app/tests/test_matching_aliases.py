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


def test_normalize_solary_eclipse_alias() -> None:
    assert normalize_team_name("Solary Eclipse") == "solary"
    assert normalize_team_name("Solary") == "solary"
    assert similarity("Solary Eclipse", "Solary") == 1.0


def test_normalize_les_academy_aliases() -> None:
    assert normalize_team_name("GIANTX Academy") == "giantx"
    assert normalize_team_name("GIANTX iTero") == "giantx"
    assert normalize_team_name("KOI Academy") == "movistar koi"
    assert normalize_team_name("Movistar KOI Fenix") == "movistar koi"
    assert similarity("GIANTX Academy", "GIANTX iTero") == 1.0
    assert similarity("KOI Academy", "Movistar KOI Fenix") == 1.0


def test_normalize_big_alias_after_esports_suffix_cleanup() -> None:
    assert normalize_team_name("BIG") == "big"
    assert normalize_team_name("Berlin International Gaming") == "big"
    assert normalize_team_name("Berlin International") == "big"
    assert similarity("BIG", "Berlin International Gaming") == 1.0


def test_normalize_msi_abbreviations() -> None:
    assert normalize_team_name("HLE") == normalize_team_name("Hanwha Life Esports")
    assert normalize_team_name("TSW") == normalize_team_name("Team Secret Whales")
