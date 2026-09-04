"""Published ENC 2027 Leaguepedia national-team roster candidates.

Source: https://lol.fandom.com/wiki/Esports_Nations_Cup_2027
The Solidarity Slot has no announced nation or roster and is intentionally absent.
"""

from __future__ import annotations

from typing import Final, TypedDict


class EncRosterSource(TypedDict):
    nation: str
    entry_stage: str
    ranking: int | None
    players: tuple[str, ...]


def _entry(nation: str, entry_stage: str, ranking: int | None, players: str) -> EncRosterSource:
    return {
        "nation": nation,
        "entry_stage": entry_stage,
        "ranking": ranking,
        "players": tuple(players.split("|")),
    }


ENC_ROSTER_SOURCE_URL: Final = "https://lol.fandom.com/wiki/Esports_Nations_Cup_2027"
ENC_PARTICIPANTS: Final[tuple[EncRosterSource, ...]] = (
    _entry("China", "group_stage", 1, "Bin|Flandre|Tian|Monki|Knight|JackeyLove|ON|BigWei|Poppy"),
    _entry("South Korea", "group_stage", 2, "Zeus|Canyon|Faker|Zeka|Gumayusi|Keria|Hirai"),
    _entry("France", "group_stage", 3, "Adam|SkewMond|Sheo|nuc|Caliste|Hans Sama|Zoelys|Zeph"),
    _entry("Vietnam", "group_stage", 4, "Kiaya|Hizto|SofM|Dire|Aress|Eddie|Taki|Naul"),
    _entry("Brazil", "group_stage", 5, "Xyno|Zynts|Tatu|Tutsz|Ayu|Morttheus|frosty|tockers"),
    _entry("United States", "group_stage", 6, "Dhokla|Blaber|Gryffinn|APA|Darkwings|Yeon|huhi|Inero"),
    _entry("Chinese Taipei", "group_stage", 7, "1Jiang|JunJia|HongQ|Doggo|ShiauC|WarHorse"),
    _entry("Denmark", "group_stage", 8, "Wunder|Carlsen|Cboi|Woldjo|Caps|Zven|Doss|Pad"),
    _entry("Türkiye", "play_in", 9, "BrokenBlade|Rhilech|Closer|Serin|Aetinoth|Fleshy|Parus|Craft1x|Arkhe"),
    _entry("Greece", "play_in", 10, "Empyros|Pallet|Drofan|Vladi|Peppe|Comp|Labrov|TheRock|Tython"),
    _entry("Poland", "play_in", 11, "Tracyn|Inspired|Jankos|Czajek|Harpoon|Busio|Trymbi|Nahovsky"),
    _entry("Argentina", "play_in", 12, "ZOEN|Josedeodo|Kaze|Enga|Ceo|Ackerman|Lyonz|Pointless|Nothing"),
    _entry("Spain", "play_in", 13, "Myrwn|Oscarinin|Elyoya|Hydra|Flakked|Legolas|Alvaro|Mithy"),
    _entry("Canada", "play_in", 14, "Zamudo|KryRa|Sheiden|Jojopyun|Spirax|Massu|Vulcan|Dylan Falco"),
    _entry("Sweden", "play_in", 15, "Baus|Kryze|Yike|SlowQ|Mishigu|UNF0RGIVEN|Rekkles|YamatoCannon|Treatz"),
    _entry("Czechia", "play_in", 16, "Bobista|Twight|OMON|Humanoid|Carzzy|Patrik|Jackies|Freeze"),
    _entry("Mexico", "play_in", None, "seiya|Grell|Skyy|Gavotto|VirusFx|Deam|Leon"),
    _entry("Guatemala", "play_in", None, "Putilt|BlindWalker|Piyey|SunTiger|Onier|Adniel"),
    _entry("Chile", "play_in", None, "Zothve|Neo|Cody|Strensh|Viciun|ShuHari|Glon|ReigN"),
    _entry("Peru", "play_in", None, "Brayaron|Oddie|Piqueos|Scenari0|Shiku|Kouke"),
    _entry("Germany", "play_in", None, "Irrelevant|Habubu|Reeker|Keduii|Lilipp|Arvindir|Lothi"),
    _entry("Belgium", "play_in", None, "Rayzorac|Bwipo|Nisqy|Evangelyne|Targamas|Kaas"),
    _entry("Lithuania", "play_in", None, "Eckas|Lyncas|Toffe|Yashiro|Parein|KNOK1"),
    _entry("Romania", "play_in", None, "Shelfmade|Frost|Ronaldo|Yakkey|whiteinn|Razvan"),
    _entry("New Zealand", "play_in", None, "Chippys|Whynot|Shok|Raes|Lost|Benvi|Vestion"),
    _entry("Philippines", "play_in", None, "Relhia|Devoured|Cherb|Dawn|Cresho|Leathergoods"),
    _entry("Hong Kong", "play_in", None, "YSKM|Holo|Pretender|BuLuKaKa|1xn|Kaiwing|Skywalk"),
    _entry("Mongolia", "play_in", None, "EQon|Yuuji|River|Jawkan|Trillv|Eucliwood"),
    _entry("Algeria", "play_in", None, "Potent|Kobs|Kamiloo|Rin|Aymen|Striker|Hainell"),
    _entry("Tunisia", "play_in", None, "Chakroun|Dean|Koussay|Xicor|insane|ThinUnclePhil"),
    _entry("Saudi Arabia", "play_in", None, "handm|Ajwad|OniiKhan|Nawaf|sas|Edward"),
)
