"""main.py on tiny fake datasets (the real Kaggle files are far too big to ship)."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_agv_index", ROOT / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Same layout as the real Kaggle files: the character -> anime link lives in the anime
# CSV's `characters` JSON column; the characters CSV has no favorites.
ANIME = (
    "myanimelist_id,title,Members,characters\n"
    '1,Fate/stay night: Unlimited Blade Works,"900,000","[{""id"": 10, ""name"": ""Tohsaka, Rin""}, {""id"": 12, ""name"": ""Rin""}]"\n'
    '2,Fate/Zero,"800,000","[{""id"": 11, ""name"": ""Matou, Rin""}]"\n'
    '3,Sword Art Online 2nd Season,"700,000","[{""id"": 13, ""name"": ""Yuuki, Asuna""}, {""id"": 14, ""name"": ""Rin""}]"\n'
    '4,Tiny Obscure Show,10,"[{""id"": 15, ""name"": ""Yamada, Hanako""}]"\n'
    '5,Broken Json Show,"500,000","[{""id"": 16, ""name"": ""Broken, Bob"" oops"\n'
)
CHARS = (
    "character_id,full_name,alternate_name,name,url\n"
    "10,Rin Tohsaka,遠坂 凛,\"Tohsaka, Rin\",u\n"
    "11,Rin Matou,,\"Matou, Rin\",u\n"
    "12,Rin,,Rin,u\n"
    "13,Asuna Yuuki,結城 明日奈,\"Yuuki, Asuna\",u\n"
    "14,Rin,,Rin,u\n"
    "15,Hanako Yamada,,\"Yamada, Hanako\",u\n"
    "16,Bob Broken,,\"Broken, Bob\",u\n"
    "17,Nobody Anywhere,,\"Anywhere, Nobody\",u\n"
)


FAVORITES = (
    "character_id,favorites\n"
    "10,50000\n"
    "11,3000\n"
    "12,10\n"
    "13,40000\n"
    "14,5\n"
    "15,1\n"
    "16,100\n"
)


@pytest.fixture
def index(tmp_path):
    (tmp_path / "anime.csv").write_text(ANIME, encoding="utf-8")
    (tmp_path / "chars.csv").write_text(CHARS, encoding="utf-8")
    (tmp_path / "fav.csv").write_text(FAVORITES, encoding="utf-8")
    return _load_builder().build(tmp_path / "chars.csv", tmp_path / "anime.csv",
                                 tmp_path / "fav.csv", forced={})


def norm_key(s):
    from agv_text import norm
    return norm(s)


def test_franchise_title_collapse():
    b = _load_builder()
    assert b.franchise_title("Fate/stay night: Unlimited Blade Works") == "Fate/stay night"
    assert b.franchise_title("Sword Art Online 2nd Season") == "Sword Art Online"
    assert b.franchise_title("Re:Zero kara Hajimeru Isekai Seikatsu") == "Re:Zero kara Hajimeru Isekai Seikatsu"


def test_characters_in_no_anime_are_dropped(index):
    assert norm_key("Nobody Anywhere") not in index["names"]    # in no anime at all


def test_series_collapse_to_franchise(index):
    titles = {t[0] for t in index["series"]}
    assert {"Fate/stay night", "Fate/Zero", "Sword Art Online"} <= titles
    assert index["aliases"][norm_key("Sword Art Online 2nd Season")] == index["aliases"][norm_key("Sword Art Online")]


def test_score_is_favorites_and_kanji_name_is_indexed(index):
    by_name = {c[0][0]: c for c in index["chars"]}
    assert by_name["Tohsaka, Rin"][2] == 50000
    assert norm_key("遠坂凛") in index["names"] or norm_key("遠坂, 凛") in index["names"]


def test_inverts_character_link_and_salvages_broken_json(index):
    names = {c[0][0] for c in index["chars"]}
    assert {"Tohsaka, Rin", "Matou, Rin", "Yuuki, Asuna"} <= names
    assert "Broken, Bob" in names        # malformed JSON cell: id still recovered by the regex


def test_output_is_version_1_json(index):
    assert index["version"] == 1
    json.dumps(index, ensure_ascii=False)
