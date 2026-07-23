from __future__ import annotations

import os

from betting_app.core.db import dispose_engine, init_db, transaction
from betting_app.services.canonical_match_service import canonical_team_key
from betting_app.services.mapping_service import suggest_mapping, upsert_alias
from betting_app.services.team_alias_service import AliasContext, resolve_scoped_alias


def _init_tmp_db(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'aliases.sqlite3'}"
    dispose_engine()
    init_db()


def test_short_alias_requires_scope(tmp_path) -> None:
    _init_tmp_db(tmp_path)
    try:
        upsert_alias(
            "USE",
            "Unicorns Of Love Sexy Edition",
            source="golgg-short",
            source_system="golgg",
            league_pattern="Prime League",
        )

        assert resolve_scoped_alias("USE", context=AliasContext()).target_name is None
        assert resolve_scoped_alias("USE", context=AliasContext(source_system="golgg", league="NACL")).target_name is None

        resolved = resolve_scoped_alias("USE", context=AliasContext(source_system="golgg", league="Prime League"))
        assert resolved.target_name == "Unicorns Of Love Sexy Edition"
    finally:
        os.environ.pop("DATABASE_URL", None)
        dispose_engine()


def test_canonical_team_key_uses_db_scoped_alias(tmp_path) -> None:
    _init_tmp_db(tmp_path)
    try:
        upsert_alias(
            "KHK",
            "Kaufland Hangry Knights",
            source="golgg-short",
            source_system=None,
            league_pattern="Prime League",
        )

        assert canonical_team_key("KHK") == "khk"
        assert canonical_team_key("KHK", league="Prime League") == "hangryknights"
    finally:
        os.environ.pop("DATABASE_URL", None)
        dispose_engine()


def test_suggest_mapping_accepts_scoped_alias_context(tmp_path) -> None:
    _init_tmp_db(tmp_path)
    try:
        with transaction() as connection:
            connection.execute(
                "INSERT INTO golgg_teams(team_name, normalized_name) VALUES (?, ?)",
                ("Bilibili Gaming", "bilibili gaming"),
            )
        upsert_alias(
            "BLG",
            "Bilibili Gaming",
            source="golgg-short",
            source_system="golgg",
            league_pattern="MSI",
        )

        assert suggest_mapping("BLG") == (None, 0.0, None)
        assert suggest_mapping("BLG", source_system="golgg", league="MSI 2026") == (
            "Bilibili Gaming",
            1.0,
            "golgg-short:golgg:MSI:*:*:*",
        )
    finally:
        os.environ.pop("DATABASE_URL", None)
        dispose_engine()
