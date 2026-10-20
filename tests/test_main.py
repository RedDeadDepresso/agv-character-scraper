"""main.py on a tiny fake Archive (the real dump is hundreds of MB)."""

import hashlib
import json
import zipfile

import pytest

import main
from agv_text import norm


def jl(*recs):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n"


SUBJECTS = jl(
    # 1: kept (anime, user tag 日本)
    {"id": 1, "type": 2, "name": "Fate/stay night", "name_cn": "命运/停留之夜",
     "infobox": "{{Infobox animanga/TVAnime\n|中文名= 命运/停留之夜\n|别名={\n[简称|FSN]\n[英文名|Fate/stay night (EN)]\n}\n}}",
     "tags": [{"name": "日本", "count": 12}, {"name": "原创", "count": 1}], "meta_tags": []},
    # 10: kept (game, meta tag, case-insensitive)
    {"id": 10, "type": 4, "name": "Fate/hollow ataraxia", "name_cn": "", "infobox": "",
     "tags": [], "meta_tags": ["Visual Novel"]},
    # 20: manga with the tag -> wrong type
    {"id": 20, "type": 1, "name": "Some Manga", "tags": [{"name": "日本", "count": 9}], "meta_tags": []},
    # 30: anime without a matching tag
    {"id": 30, "type": 2, "name": "Untagged", "tags": [{"name": "原创", "count": 9}], "meta_tags": ["TV"]},
    # 40: JRPG
    {"id": 40, "type": 4, "name": "ファイナルファンタジーX", "name_cn": "最终幻想10",
     "infobox": "{{Infobox Game\n|别名={\n[英文名|Final Fantasy X]\n}\n}}",
     "tags": [{"name": "JRPG", "count": 3}], "meta_tags": []},
)

LINKS = jl(
    {"character_id": 100, "subject_id": 10, "type": 1, "order": 0},   # 10 and 1 -> 1 (lowest)
    {"character_id": 100, "subject_id": 1, "type": 1, "order": 0},
    {"character_id": 101, "subject_id": 20, "type": 1, "order": 0},   # only in the manga
    {"character_id": 102, "subject_id": 30, "type": 1, "order": 0},   # only in the untagged anime
    {"character_id": 103, "subject_id": 10, "type": 1, "order": 0},
    {"character_id": 104, "subject_id": 40, "type": 1, "order": 0},
)

CHARACTERS = jl(
    {"id": 100, "role": 1, "name": "遠坂 凛", "collects": 5000, "comments": 1,
     "infobox": "{{Infobox Crt\n|简体中文名= 远坂凛\n|生日= 2月3日（水瓶座）\n|别名={\n[第二中文名|远坂 凛]\n[英文名|Rin Tohsaka]\n"
                "[日文名|遠坂 凛]\n[纯假名|とおさか りん]\n[罗马字|Tousaka Rin]\n[昵称|赤い悪魔]\n}\n}}"},
    {"id": 101, "role": 1, "name": "Manga Person", "collects": 1, "infobox": ""},
    {"id": 102, "role": 1, "name": "Untagged Person", "collects": 1, "infobox": ""},
    {"id": 103, "role": 1, "name": "ルルーシュ・ランペルージ", "collects": 40, "infobox": "{{Infobox Crt\n|简体中文名= 鲁路修·兰佩路基\n}}"},
    {"id": 104, "role": 1, "name": "Tidus", "collects": 777, "infobox": "broken infobox"},
)


@pytest.fixture
def data(tmp_path):
    (tmp_path / "subject.jsonlines").write_text(SUBJECTS, encoding="utf-8")
    (tmp_path / "subject-characters.jsonlines").write_text(LINKS, encoding="utf-8")
    (tmp_path / "character.jsonlines").write_text(CHARACTERS, encoding="utf-8")
    return tmp_path


def t2s_like(s):            # a stand-in for OpenCC s2t
    return s.replace("远", "遠").replace("鲁", "魯")


@pytest.fixture
def index(data):
    return main.build_index(data, t2s_like)


# --- selection -------------------------------------------------------------

def test_subject_selection(data):
    assert sorted(main.select_subjects(data / "subject.jsonlines")) == [1, 10, 40]


def test_character_keeps_lowest_subject_id_without_dates(data):
    subjects = main.select_subjects(data / "subject.jsonlines")
    assert main.first_subject_per_character(data / "subject-characters.jsonlines", subjects) == {
        100: 1, 103: 10, 104: 40}


def test_character_keeps_the_earliest_released_subject(tmp_path):
    tag = [{"name": "JRPG", "count": 1}]
    (tmp_path / "subject.jsonlines").write_text(jl(
        {"id": 15489, "type": 2, "name": "Persona 4 the Animation", "date": "2011-10-06", "tags": tag},   # lower id...
        {"id": 20000, "type": 4, "name": "Persona 4", "date": "2008-07-10", "tags": tag},                 # ...but released first
        {"id": 7, "type": 4, "name": "Undated", "tags": tag},
        {"id": 8, "type": 4, "name": "Bare year", "date": "2009", "tags": tag},
        {"id": 9, "type": 4, "name": "Bad date", "date": "n/a", "tags": tag},
    ), encoding="utf-8")
    (tmp_path / "links.jsonlines").write_text(jl(
        {"character_id": 1, "subject_id": 15489}, {"character_id": 1, "subject_id": 20000},   # game wins
        {"character_id": 2, "subject_id": 7}, {"character_id": 2, "subject_id": 15489},       # a dated subject beats an undated one
        {"character_id": 3, "subject_id": 9}, {"character_id": 3, "subject_id": 7},           # none dated: lowest id
        {"character_id": 4, "subject_id": 20000}, {"character_id": 4, "subject_id": 8},       # 2008-07-10 < 2009
    ), encoding="utf-8")
    subjects = main.select_subjects(tmp_path / "subject.jsonlines")
    assert main.first_subject_per_character(tmp_path / "links.jsonlines", subjects) == {1: 20000, 2: 15489, 3: 7, 4: 20000}


def test_release_key():
    assert main.release_key({"date": "2008-07-10"}, 5) < main.release_key({"date": "2011-10-06"}, 1)
    assert main.release_key({"date": "2008-07-10"}, 5) < main.release_key({}, 1)            # undated sorts last
    assert main.release_key({"date": "2008-07-10"}, 1) < main.release_key({"date": "2008-07-10"}, 2)   # tie: id


# --- index -----------------------------------------------------------------

def test_format(index):
    assert index["version"] == 1
    assert index["langs"] == ["en_us", "ja_jp", "zh_cn", "zh_tw"]
    assert len(index["series"]) == 3                     # subjects 1, 10, 40 (ascending id)
    assert all(len(s) == 4 for s in index["series"]) and all(len(c[0]) == 4 for c in index["chars"])
    json.dumps(index, ensure_ascii=False)


def test_series_titles(index):
    fsn, hollow, ff = index["series"]
    assert fsn == ["Fate/stay night (EN)", "Fate/stay night", "命运/停留之夜", "命运/停留之夜"]   # fake s2t leaves it as is
    assert hollow[:2] == ["Fate/hollow ataraxia", "Fate/hollow ataraxia"]
    assert ff == ["Final Fantasy X", "ファイナルファンタジーX", "最终幻想10", "最终幻想10"]


def test_series_aliases_include_every_title(index):
    a = index["aliases"]
    assert a[norm("FSN")] == a[norm("命运/停留之夜")] == a[norm("Fate/stay night")] == 0
    assert a[norm("Final Fantasy X")] == 2


def test_characters_and_their_series(index):
    by_score = {c[2]: c for c in index["chars"]}
    assert set(by_score) == {5000, 40, 777}               # 101 and 102 are dropped
    assert by_score[5000][1] == [0]                       # in subjects 1 and 10 -> subject 1
    assert by_score[40][1] == [1]
    assert by_score[777][1] == [2]


def test_character_names_per_language(index):
    rin = next(c for c in index["chars"] if c[2] == 5000)[0]
    assert rin == ["Tousaka, Rin", "遠坂, 凛", "远坂凛", "遠坂凛"]
    lelouch = next(c for c in index["chars"] if c[2] == 40)[0]
    assert lelouch[2] == "兰佩路基, 鲁路修"               # Given·Family reversed
    tidus = next(c for c in index["chars"] if c[2] == 777)[0]
    assert tidus[:2] == ["Tidus", "Tidus"]                # broken infobox: dump fields only


def test_name_lookup_forms(index):
    n = index["names"]
    rin = next(i for i, c in enumerate(index["chars"]) if c[2] == 5000)
    for form in ("遠坂凛", "凛遠坂", "Tousaka Rin", "Rin Tousaka", "Rin Tohsaka", "Tohsaka Rin",
                 "とおさかりん", "赤い悪魔", "远坂凛", "遠坂凛", "Tousaka, Rin"):
        assert rin in n[norm(form)], form
    assert 40 in {index["chars"][i][2] for i in n[norm("鲁路修兰佩路基")]}


def test_without_opencc_there_is_no_traditional(data):
    idx = main.build_index(data, None)
    assert idx["langs"] == ["en_us", "ja_jp", "zh_cn"]
    assert all(len(c[0]) == 3 for c in idx["chars"])


# --- series.json exclusion -------------------------------------------------

SERIES = [
    {"game": "Final Fantasy X", "bangumi_id": 40, "title": {"en_us": "Final Fantasy X"}, "aliases": ["FFX"]},
    {"game": "Fate", "bangumi_id": "1", "title": {"en_us": "Fate"}, "aliases": []},
    {"game": "No id yet", "title": {"en_us": "Fate/hollow ataraxia"}, "aliases": []},
    {"game": "Zero id", "bangumi_id": 0, "title": {}, "aliases": []},
    {"game": "Not a number", "bangumi_id": "abc", "title": {}, "aliases": []},
    "junk entry",
]


def test_excluded_ids():
    assert main.excluded_ids(SERIES) == {40, 1}


def test_subjects_in_series_json_are_excluded_by_bangumi_id(data):
    ex = main.excluded_ids(SERIES)
    # 40 and 1 are excluded by id. 10 is kept although an entry without bangumi_id has its title.
    assert sorted(main.select_subjects(data / "subject.jsonlines", ex)) == [10]


def test_a_title_in_series_json_no_longer_excludes(data):
    ex = main.excluded_ids([{"game": "Fate/stay night", "title": {"en_us": "Fate/stay night"},
                             "aliases": ["Final Fantasy X"]}])
    assert ex == frozenset()
    assert sorted(main.select_subjects(data / "subject.jsonlines", ex)) == [1, 10, 40]


def test_excluded_subject_does_not_claim_its_characters(data):
    ex = main.excluded_ids([{"game": "Fate/stay night", "bangumi_id": 1}])
    idx = main.build_index(data, t2s_like, ex)
    assert len(idx["series"]) == 2                           # subjects 10 and 40
    rin = next(c for c in idx["chars"] if c[2] == 5000)
    assert idx["series"][rin[1][0]][1] == "Fate/hollow ataraxia"   # 100: 1 is gone -> next lowest, 10


def test_character_only_in_excluded_subjects_is_dropped(data):
    ex = main.excluded_ids([{"game": "ファイナルファンタジーX", "bangumi_id": 40}])
    idx = main.build_index(data, t2s_like, ex)
    assert 777 not in {c[2] for c in idx["chars"]}           # Tidus was only in subject 40


def test_no_exclusion_by_default(data):
    assert sorted(main.select_subjects(data / "subject.jsonlines")) == [1, 10, 40]


# --- VTubers --------------------------------------------------------------

VTUBERS = [
    {"uuid": "a", "type": "vtuber", "bot": False, "accounts": [],
     "name": {"extra": ["Ina"], "cn": "一伊那尓栖", "en": "Ninomae Ina'nis", "jp": "一伊那尓栖", "default": "cn"}},
    {"uuid": "b", "type": "vtuber", "name": {"extra": [], "cn": "晴朗蓝", "default": "cn"}},
    {"uuid": "c", "type": "vtuber", "name": {"extra": [], "CN": "大写键", "JP": "大文字", "EN": "Upper Key", "default": "CN"}},
    {"uuid": "d", "type": "vtuber", "name": {"extra": [], "ID": "Hololive ID", "default": "ID"}},   # unknown key only
    {"uuid": "g", "type": "group", "name": {"extra": [], "cn": "A-SOUL", "default": "cn"}},          # an agency
    {"uuid": "f", "type": "fan", "name": {"extra": [], "cn": "粉丝", "default": "cn"}},
    {"uuid": "e", "type": "vtuber", "name": {"extra": [], "default": "cn"}},                          # no name
]


def test_vtuber_names():
    per, every = main.vtuber_names(VTUBERS[0], t2s_like)
    assert per == ["Ninomae Ina'nis", "一伊那尓栖", "一伊那尓栖", "一伊那尓栖"]
    assert "cn" not in every and set(every) >= {"Ina", "Ninomae Ina'nis"}       # "default": "cn" is no name
    assert main.vtuber_names(VTUBERS[1], None)[0] == ["", "", "晴朗蓝", ""]
    assert main.vtuber_names(VTUBERS[2], None)[0] == ["Upper Key", "大文字", "大写键", ""]   # CN / JP / EN
    assert main.vtuber_names(VTUBERS[3], None)[0][0] == "Hololive ID"            # first name as a fallback


def test_vtubers_are_added_last_in_one_series(data):
    base = main.build_index(data, t2s_like)
    idx = main.build_index(data, t2s_like, vtubers=VTUBERS)
    n = len(base["chars"])
    assert idx["chars"][:n] == base["chars"] and idx["series"][:-1] == base["series"]
    assert idx["series"][-1] == ["VTubers"] * 4
    added = idx["chars"][n:]
    assert len(added) == 4                                      # 3 named vtubers + the unknown-key one
    assert all(c[1] == [len(idx["series"]) - 1] and c[2] == 0 for c in added)
    assert idx["aliases"][norm("VTubers")] == idx["aliases"][norm("vtuber")] == len(idx["series"]) - 1


def test_vtuber_lookup_names_come_after_existing_matches(data):
    idx = main.build_index(data, t2s_like, vtubers=VTUBERS + [
        {"type": "vtuber", "name": {"extra": [], "en": "Tidus", "default": "en"}}])
    hits = idx["names"][norm("Tidus")]
    assert [idx["chars"][i][2] for i in hits] == [777, 0]       # the game character, then the VTuber
    ina = idx["names"][norm("Ninomae Inanis")]                    # punctuation-insensitive
    assert idx["chars"][ina[0]][0][0] == "Ninomae Ina'nis"
    assert idx["names"][norm("Ina")] == ina


def test_no_vtubers_by_default(data):
    idx = main.build_index(data, t2s_like)
    assert "VTubers" not in [s[0] for s in idx["series"]]


# --- English series titles from bangumi-data ------------------------------

BANGUMI_DATA = {"siteMeta": {}, "items": [
    # matched by title only (no bangumi site)
    {"title": "魔法少女まどか☆マギカ", "titleTranslate": {"zh-Hans": ["魔法少女小圆"],
                                                    "en": ["Puella Magi Madoka Magica", "Madoka"]}, "sites": []},
    {"title": "名前のない作品", "titleTranslate": {"zh-Hans": ["无名"]}, "sites": []},          # no English title
    {"title": "英語あり", "titleTranslate": {"en": ["Other English Title"]},
     "sites": [{"site": "bangumi", "id": "51"}]},
    # the spelling differs from Bangumi's, so only the id finds it
    {"title": "別の表記のタイトル", "titleTranslate": {"en": ["Found By Id"]},
     "sites": [{"site": "annict", "id": "9"}, {"site": "bangumi", "id": "53"}]},
    # same title as subject 54's, but its id says it is another subject: the id wins
    {"title": "同じタイトル", "titleTranslate": {"en": ["Wrong Entry"]}, "sites": [{"site": "bangumi", "id": "999"}]},
    {"title": "同じタイトルの別物", "titleTranslate": {"en": ["Right Entry"]}, "sites": [{"site": "bangumi", "id": "54"}]},
    {"nonsense": True}, "junk",
]}


@pytest.fixture
def jp_data(tmp_path):
    (tmp_path / "subject.jsonlines").write_text(jl(
        {"id": 50, "type": 2, "name": "魔法少女まどか☆マギカ", "name_cn": "魔法少女小圆", "infobox": "",
         "tags": [{"name": "日本", "count": 1}]},
        {"id": 51, "type": 2, "name": "英語あり", "infobox": "{{Infobox animanga/TVAnime\n|别名={\n[英文名|Has English]\n}\n}}",
         "tags": [{"name": "日本", "count": 1}]},
        {"id": 52, "type": 2, "name": "名前のない作品", "infobox": "", "tags": [{"name": "日本", "count": 1}]},
        {"id": 53, "type": 2, "name": "ID違いのタイトル", "infobox": "", "tags": [{"name": "日本", "count": 1}]},
        {"id": 54, "type": 2, "name": "同じタイトル", "infobox": "", "tags": [{"name": "日本", "count": 1}]},
    ), encoding="utf-8")
    (tmp_path / "subject-characters.jsonlines").write_text(jl(
        {"character_id": 500, "subject_id": 50}, {"character_id": 501, "subject_id": 51},
        {"character_id": 502, "subject_id": 52}, {"character_id": 503, "subject_id": 53},
        {"character_id": 504, "subject_id": 54}), encoding="utf-8")
    (tmp_path / "character.jsonlines").write_text(jl(
        {"id": 500, "name": "鹿目 まどか", "collects": 9, "infobox": ""},
        {"id": 501, "name": "A", "collects": 1, "infobox": ""},
        {"id": 502, "name": "B", "collects": 1, "infobox": ""},
        {"id": 503, "name": "C", "collects": 1, "infobox": ""},
        {"id": 504, "name": "D", "collects": 1, "infobox": ""}), encoding="utf-8")
    return tmp_path


def test_english_titles_lookups():
    by_id, by_title = main.english_titles(BANGUMI_DATA["items"])
    assert by_id == {51: "Other English Title", 53: "Found By Id", 999: "Wrong Entry", 54: "Right Entry"}
    assert by_title[norm("魔法少女まどか☆マギカ")] == "Puella Magi Madoka Magica"   # first English title
    assert norm("名前のない作品") not in by_title                                    # no English title


def test_series_without_english_gets_it_by_id_then_by_title(jp_data):
    idx = main.build_index(jp_data, None, english=main.english_titles(BANGUMI_DATA["items"]))
    en = {s[1]: s[0] for s in idx["series"]}
    assert en["魔法少女まどか☆マギカ"] == "Puella Magi Madoka Magica"   # by title
    assert en["ID違いのタイトル"] == "Found By Id"                      # by subject id, titles differ
    assert en["同じタイトル"] == "Right Entry"                          # the id beats the title match
    assert en["英語あり"] == "Has English"                              # Bangumi's own English is kept
    assert en["名前のない作品"] == ""                                    # nothing to find: stays empty
    i = next(i for i, s in enumerate(idx["series"]) if s[1] == "ID違いのタイトル")
    assert idx["aliases"][norm("Found By Id")] == i                     # and it is an alias


def test_latin_alias_is_the_last_resort_for_the_english_title(tmp_path):
    tag = [{"name": "日本", "count": 1}]
    (tmp_path / "subject.jsonlines").write_text(jl(
        # the English title is a plain alias (no 英文名 key); the initialism must not win
        {"id": 1, "type": 2, "name": "カウボーイビバップ", "name_cn": "星际牛仔", "tags": tag,
         "infobox": "{{Infobox animanga/TVAnime\n|别名={\n[CB]\n[Cowboy Bebop]\n[牛仔]\n}\n}}"},
        {"id": 2, "type": 2, "name": "別作品", "tags": tag, "infobox": "{{Infobox animanga/TVAnime\n|别名={\n[AB]\n}\n}}"},
    ), encoding="utf-8")
    (tmp_path / "subject-characters.jsonlines").write_text(
        jl({"character_id": 1, "subject_id": 1}, {"character_id": 2, "subject_id": 2}), encoding="utf-8")
    (tmp_path / "character.jsonlines").write_text(
        jl({"id": 1, "name": "A", "infobox": ""}, {"id": 2, "name": "B", "infobox": ""}), encoding="utf-8")
    idx = main.build_index(tmp_path, None)
    assert [s[0] for s in idx["series"]] == ["Cowboy Bebop", ""]       # no 3-letter alias for the second one
    assert idx["aliases"][norm("Cowboy Bebop")] == 0


def test_bangumi_data_beats_a_latin_alias(tmp_path):
    tag = [{"name": "日本", "count": 1}]
    (tmp_path / "subject.jsonlines").write_text(jl(
        {"id": 1, "type": 2, "name": "カウボーイビバップ", "tags": tag,
         "infobox": "{{Infobox animanga/TVAnime\n|别名={\n[Cowboy Bebop (alias)]\n}\n}}"}), encoding="utf-8")
    (tmp_path / "subject-characters.jsonlines").write_text(jl({"character_id": 1, "subject_id": 1}), encoding="utf-8")
    (tmp_path / "character.jsonlines").write_text(jl({"id": 1, "name": "A", "infobox": ""}), encoding="utf-8")
    idx = main.build_index(tmp_path, None, english=({1: "Cowboy Bebop"}, {}))
    assert idx["series"][0][0] == "Cowboy Bebop"


def test_a_game_does_not_take_the_english_title_of_its_anime(tmp_path):
    tag = [{"name": "JRPG", "count": 1}]
    (tmp_path / "subject.jsonlines").write_text(jl(
        {"id": 8000, "type": 4, "name": "ペルソナ4", "name_cn": "女神异闻录4", "tags": tag, "infobox": ""},   # the game
        {"id": 15489, "type": 2, "name": "ペルソナ4", "name_cn": "女神异闻录4 动画版", "tags": tag, "infobox": ""},  # the anime
    ), encoding="utf-8")
    (tmp_path / "subject-characters.jsonlines").write_text(
        jl({"character_id": 1, "subject_id": 8000}, {"character_id": 2, "subject_id": 15489}), encoding="utf-8")
    (tmp_path / "character.jsonlines").write_text(
        jl({"id": 1, "name": "A", "infobox": ""}, {"id": 2, "name": "B", "infobox": ""}), encoding="utf-8")
    items = [{"title": "ペルソナ4", "titleTranslate": {"en": ["PERSONA 4 the ANIMATION"]},
              "sites": [{"site": "bangumi", "id": "15489"}]}]                      # bangumi-data: anime only
    idx = main.build_index(tmp_path, None, english=main.english_titles(items))
    by_cn = {s[2]: s[0] for s in idx["series"]}
    assert by_cn["女神异闻录4"] == ""                                              # the game: not the anime's title
    assert by_cn["女神异闻录4 动画版"] == "PERSONA 4 the ANIMATION"                 # the anime itself still gets it


def test_nothing_changes_without_bangumi_data(jp_data):
    assert [s[0] for s in main.build_index(jp_data, None)["series"]] == ["", "Has English", "", "", ""]


# --- English character names from the MAL dataset --------------------------

MAL_CSV = (
    "character_id,name,alternate_name,about\n"
    '1,"Kaname, Madoka",鹿目 まどか,"multi-line\nabout, with a comma"\n'
    '2,"Spiegel, Spike",スパイク・スピーゲル,\n'
    '3,"Ein",アイン,\n'
    '4,"Eins",アイン,\n'                               # same Japanese name, different English: ambiguous
    '5,"Dup, Same",重複,\n'
    '6,"Dup, Same",重複,\n'                            # same English twice: not ambiguous
    '7,"No Alt",,\n'
    '8,,名前なし,\n'                                   # no English name
    '9,"Reversed, Name",名前 逆,\n'
)


@pytest.fixture
def mal_csv(tmp_path):
    f = tmp_path / "mal_characters_detailed.csv"
    f.write_text(MAL_CSV, encoding="utf-8")
    return f


def test_read_english_names(mal_csv):
    t = main.read_english_names(mal_csv)
    assert t[norm("鹿目まどか")] == "Kaname, Madoka"                   # norm ignores the space
    assert t[norm("スパイク・スピーゲル")] == "Spiegel, Spike"
    assert t[norm("重複")] == "Dup, Same"
    assert norm("アイン") not in t                                       # ambiguous: left out
    assert norm("名前なし") not in t and len(t) == 4


def test_english_name_tries_both_orders(mal_csv):
    t = main.read_english_names(mal_csv)
    assert main.english_name("鹿目 まどか", t) == "Kaname, Madoka"
    assert main.english_name("逆 名前", t) == "Reversed, Name"            # dataset has the other order
    assert main.english_name("誰か 知らない", t) == ""


def test_characters_without_english_get_it_from_the_mal_dataset(jp_data, mal_csv):
    table = main.read_english_names(mal_csv)
    idx = main.build_index(jp_data, None, english_names=table)
    madoka = next(c for c in idx["chars"] if c[2] == 9)
    assert madoka[0][:2] == ["Kaname, Madoka", "鹿目, まどか"]
    assert madoka[0][0] and next(c for c in idx["chars"] if c[2] == 1)[0][0] == "A"   # Latin names untouched
    assert idx["chars"].index(madoka) in idx["names"][norm("Kaname Madoka")]          # found by English too
    assert idx["chars"].index(madoka) in idx["names"][norm("Madoka Kaname")]


def test_existing_english_names_are_not_replaced(data):
    # character 100 already has "Tousaka, Rin" (romaji) in Bangumi
    idx = main.build_index(data, t2s_like, english_names={norm("遠坂凛"): "Wrong, Name"})
    assert next(c for c in idx["chars"] if c[2] == 5000)[0][0] == "Tousaka, Rin"


def test_no_english_names_without_the_dataset(jp_data):
    assert next(c for c in main.build_index(jp_data, None)["chars"] if c[2] == 9)[0][0] == ""


@pytest.fixture
def kaggle(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "data")
    st = {"downloads": 0, "members": {"anime-characters/mal_characters_detailed.csv": MAL_CSV,
                                      "anime-characters/other.csv": "x\n"}}

    def fake_download(url, dest, digest=""):
        assert url == main.MAL_URL
        st["downloads"] += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w") as z:
            for name, text in st["members"].items():
                z.writestr(name, text)

    monkeypatch.setattr(main, "download", fake_download)
    return st


def test_mal_dataset_downloaded_extracted_and_archive_deleted(kaggle):
    path = main.update_mal_dataset()
    assert path == main.DATA_DIR / "mal_characters_detailed.csv" and path.read_text(encoding="utf-8") == MAL_CSV
    assert [p.name for p in main.DATA_DIR.iterdir()] == ["mal_characters_detailed.csv"]   # only the csv


def test_mal_dataset_download_skipped_when_the_csv_exists(kaggle):
    main.update_mal_dataset()
    main.update_mal_dataset()
    assert kaggle["downloads"] == 1


def test_mal_dataset_failures_stop_and_leave_nothing_behind(kaggle):
    kaggle["members"] = {"other.csv": "x\n"}                       # the csv is not in the archive
    with pytest.raises(SystemExit):
        main.update_mal_dataset()
    assert list(main.DATA_DIR.iterdir()) == []                       # no archive, no .part, no csv


# --- data.json download / commit check --------------------------------------

@pytest.fixture
def bdata(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(main, "BANGUMI_COMMIT_FILE", tmp_path / "bangumi_data_last_commit.txt")
    st = {"sha": "aaa111bbb", "downloads": 0}

    def fake_json(url):
        assert url == main.BANGUMI_DATA_COMMITS_URL
        if st["sha"] is None:
            raise OSError("offline")
        return [{"sha": st["sha"]}]

    def fake_download(url, dest, digest=""):
        assert url == main.BANGUMI_DATA_URL
        st["downloads"] += 1
        dest.write_text(json.dumps(BANGUMI_DATA), encoding="utf-8")

    monkeypatch.setattr(main, "fetch_json", fake_json)
    monkeypatch.setattr(main, "download", fake_download)
    return st


def test_bangumi_data_downloaded_and_commit_saved_in_root(bdata):
    path = main.update_bangumi_data()
    assert path == main.DATA_DIR / "data.json" and json.loads(path.read_text(encoding="utf-8")) == BANGUMI_DATA
    assert main.BANGUMI_COMMIT_FILE.read_text(encoding="utf-8") == "aaa111bbb"
    assert [p.name for p in main.DATA_DIR.iterdir()] == ["data.json"]                # no .part left


def test_bangumi_data_skipped_unless_commit_changed_or_file_missing(bdata):
    main.update_bangumi_data()
    main.update_bangumi_data()
    assert bdata["downloads"] == 1                       # same commit
    bdata["sha"] = "ccc222ddd"
    main.update_bangumi_data()
    assert bdata["downloads"] == 2 and main.BANGUMI_COMMIT_FILE.read_text(encoding="utf-8") == "ccc222ddd"
    (main.DATA_DIR / "data.json").unlink()
    main.update_bangumi_data()
    assert bdata["downloads"] == 3                       # same commit, but the file was gone


def test_bangumi_data_offline_uses_the_existing_file_or_stops(bdata):
    bdata["sha"] = None
    with pytest.raises(SystemExit):
        main.update_bangumi_data()                       # nothing to fall back on
    bdata["sha"] = "aaa111bbb"
    main.update_bangumi_data()
    bdata["sha"] = None
    assert main.update_bangumi_data().exists() and bdata["downloads"] == 1


def test_bad_download_keeps_the_old_file_and_commit(bdata, monkeypatch):
    main.update_bangumi_data()
    bdata["sha"] = "ccc222ddd"
    monkeypatch.setattr(main, "download", lambda url, dest, digest="": dest.write_text("<html>", encoding="utf-8"))
    path = main.update_bangumi_data()                    # warns, keeps using the old file
    assert json.loads(path.read_text(encoding="utf-8")) == BANGUMI_DATA
    assert main.BANGUMI_COMMIT_FILE.read_text(encoding="utf-8") == "aaa111bbb"      # retried next run
    assert not (main.DATA_DIR / "data.json.part").exists()


# --- helpers ---------------------------------------------------------------

def test_name_helpers():
    assert main.japanese_name("遠坂　凛") == "遠坂, 凛"            # full-width space
    assert main.japanese_name("Saber") == "Saber"
    assert main.chinese_name("鲁路修·兰佩路基") == "兰佩路基, 鲁路修"
    assert main.chinese_name("远坂凛") == "远坂凛"


# --- download / skip logic -------------------------------------------------

def make_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("dump/subject.jsonlines", SUBJECTS)
        z.writestr("dump/subject-characters.jsonlines", LINKS)
        z.writestr("dump/character.jsonlines", CHARACTERS)
        for extra in ("episode", "person", "person-characters", "person-relations", "subject-persons",
                      "subject-relations"):
            z.writestr(f"dump/{extra}.jsonlines", "{}\n")


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(main, "LATEST_FILE", tmp_path / "latest.json")
    state = {"remote": {"name": "dump-1.zip", "browser_download_url": "https://x/dump-1.zip",
                        "digest": "", "size": 1}, "downloads": 0}

    def fake_download(url, dest, digest=""):
        state["downloads"] += 1
        make_zip(dest)

    monkeypatch.setattr(main, "fetch_latest", lambda: state["remote"])
    monkeypatch.setattr(main, "download", fake_download)
    return state


def test_download_extracts_only_what_is_needed_and_saves_latest(archive):
    main.update_data()
    d = main.DATA_DIR
    assert sorted(p.name for p in d.iterdir()) == sorted(main.NEEDED)          # no zip, no extras
    assert json.loads(main.LATEST_FILE.read_text(encoding="utf-8")) == archive["remote"]  # in the root
    assert (d / "subject.jsonlines").read_text(encoding="utf-8") == SUBJECTS     # archive is gone too


def test_skips_download_when_latest_is_unchanged_then_redownloads(archive):
    main.update_data()
    main.update_data()
    assert archive["downloads"] == 1
    archive["remote"] = dict(archive["remote"], name="dump-2.zip")
    main.update_data()
    assert archive["downloads"] == 2


def test_redownloads_when_an_extracted_file_is_missing(archive):
    main.update_data()
    (main.DATA_DIR / "character.jsonlines").unlink()
    main.update_data()
    assert archive["downloads"] == 2


def test_offline_uses_existing_data(archive, monkeypatch):
    main.update_data()

    def offline():
        raise OSError("offline")

    monkeypatch.setattr(main, "fetch_latest", offline)
    main.update_data()                                   # no exception, no download
    assert archive["downloads"] == 1


def test_failed_download_leaves_no_archive_and_no_latest(archive, monkeypatch):
    main.update_data()
    archive["remote"] = dict(archive["remote"], name="dump-2.zip")

    def broken(url, dest, digest=""):
        dest.write_bytes(b"not a zip")

    monkeypatch.setattr(main, "download", broken)
    with pytest.raises(zipfile.BadZipFile):
        main.update_data()
    assert not (main.DATA_DIR / "dump-2.zip").exists()
    assert not main.LATEST_FILE.exists()                 # so the next run downloads again


def test_download_checks_sha256(tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"hello")
    ok = "sha256:" + hashlib.sha256(b"hello").hexdigest()
    main.download(src.as_uri(), tmp_path / "ok.bin", ok)
    assert (tmp_path / "ok.bin").read_bytes() == b"hello"
    with pytest.raises(ValueError):
        main.download(src.as_uri(), tmp_path / "bad.bin", "sha256:" + "0" * 64)


def test_guest_links_do_not_choose_the_series(tmp_path):
    tag = [{"name": "JRPG", "count": 1}]
    (tmp_path / "subject.jsonlines").write_text(jl(
        {"id": 1, "type": 4, "name": "Old game", "date": "2010-01-01", "tags": tag},
        {"id": 2, "type": 4, "name": "New game", "date": "2020-01-01", "tags": tag},
        {"id": 3, "type": 4, "name": "Newer game", "date": "2022-01-01", "tags": tag},
    ), encoding="utf-8")
    (tmp_path / "links.jsonlines").write_text(jl(
        {"character_id": 1, "subject_id": 1, "type": 3}, {"character_id": 1, "subject_id": 2, "type": 1},   # guest in the older game
        {"character_id": 2, "subject_id": 2, "type": 2}, {"character_id": 2, "subject_id": 3, "type": 1},   # both real: the earlier
        {"character_id": 3, "subject_id": 2, "type": 3}, {"character_id": 3, "subject_id": 3, "type": 3},   # guest everywhere: earliest
        {"character_id": 4, "subject_id": 1, "type": 3}, {"character_id": 4, "subject_id": 3},              # no type: not a guest
    ), encoding="utf-8")
    subjects = main.select_subjects(tmp_path / "subject.jsonlines")
    assert main.first_subject_per_character(tmp_path / "links.jsonlines", subjects) == {1: 2, 2: 2, 3: 2, 4: 3}


@pytest.mark.parametrize("text, want", [
    ("9月28日", (9, 28)), ("２月２９日", (2, 29)), ("2000年9月28日（天秤座）", (9, 28)), ("12月5日", (12, 5)),
    ("9/28", (9, 28)), ("28/9", (9, 28)), ("4/1", (4, 1)), ("2000-09-28", (9, 28)), ("2000/9/28", (9, 28)),
    ("September 28", (9, 28)), ("Sept. 28th", (9, 28)), ("28th of September", (9, 28)), ("1 Jan", (1, 1)),
    ("3月3日（ひな祭り）", (3, 3)),
    ("", (0, 0)), ("不明", (0, 0)), ("6月", (0, 0)), ("1994年", (0, 0)), ("2月30日", (0, 0)),
    ("13月1日", (0, 0)), ("may", (0, 0)), ("身高 170", (0, 0)), ("100/200", (0, 0)),
])
def test_parse_birthday(text, want):
    assert main.parse_birthday(text) == want


def test_birthday_is_appended_to_the_character_when_known(data):
    idx = main.build_index(data, t2s_like)
    rin = next(c for c in idx["chars"] if c[2] == 5000)
    assert rin[3:] == [2, 3]
    others = [c for c in idx["chars"] if c[2] != 5000]
    assert others and all(len(c) == 3 for c in others)     # no birthday: nothing appended
    assert main.character_birthday({"infobox": "{{Infobox Crt\n|生日= 不明\n}}"}) == (0, 0)
    assert main.character_birthday({"infobox": "not a wiki"}) == (0, 0)


# --- VTuber birthdays from Amatsukaze ---------------------------------------

def _vt(i, name, birthday="2004-12-17T00:00:00Z"):
    return {"id": i, "name": name, "birthday": birthday, "image": "x", "debut_date": "2026-01-01T00:00:00Z"}


def _fake_api(monkeypatch, vtubers, limit=2):
    """Serve `vtubers` (newest first) in pages of `limit`; returns the list of requested pages."""
    monkeypatch.setattr(main, "AMATSUKAZE_LIMIT", limit)
    monkeypatch.setattr(main, "AMATSUKAZE_DELAY", 0)
    pages = []

    def fetch(url):
        q = dict(p.split("=") for p in url.split("?")[1].split("&"))
        pages.append(int(q["page"]))
        n = int(q["page"])
        return {"status": 200, "message": "ok", "data": vtubers[(n - 1) * limit:n * limit]}
    monkeypatch.setattr(main, "fetch_json", fetch)
    return pages


def test_amatsukaze_url_has_only_the_wanted_parameters():
    url = main.amatsukaze_page_url(3)
    assert url == ("https://amatsukaze.rl404.com/api/vtubers?name=&birthday_day=&start_birthday_month="
                   "&end_birthday_month=&page=3&limit=50&sort=-debut_date")


def test_amatsukaze_first_run_fetches_everything_and_later_runs_stop_at_the_first_saved(tmp_path, monkeypatch):
    path = tmp_path / "data" / "amatsukaze_vtubers.json"
    api = [_vt(5, "E"), _vt(4, "D", None), _vt(3, "C"), _vt(2, "B"), _vt(1, "A")]
    pages = _fake_api(monkeypatch, api)
    got = main.update_vtuber_birthdays(path)
    assert [v["id"] for v in got] == [5, 4, 3, 2, 1] and pages == [1, 2, 3]
    assert json.loads(path.read_text(encoding="utf-8")) == got
    assert set(got[0]) == {"id", "name", "birthday"}                  # only what is needed is saved

    api[:0] = [_vt(7, "G"), _vt(6, "F")]                              # two new VTubers
    pages = _fake_api(monkeypatch, api)
    got = main.update_vtuber_birthdays(path)
    assert [v["id"] for v in got] == [7, 6, 5, 4, 3, 2, 1]
    assert pages == [1, 2]                                            # 5 is on page 2: nothing older is fetched

    pages = _fake_api(monkeypatch, api)
    main.update_vtuber_birthdays(path)
    assert pages == [1]                                               # nothing new


def test_amatsukaze_failure_saves_nothing_and_keeps_the_saved_list(tmp_path, monkeypatch):
    path = tmp_path / "v.json"
    path.write_text(json.dumps([{"id": 1, "name": "A", "birthday": None}]), encoding="utf-8")

    def broken(url):
        if "page=2" in url:
            raise OSError("down")
        return {"data": [_vt(9, "I"), _vt(8, "H")]}
    monkeypatch.setattr(main, "fetch_json", broken)
    monkeypatch.setattr(main, "AMATSUKAZE_LIMIT", 2)
    monkeypatch.setattr(main, "AMATSUKAZE_DELAY", 0)
    assert main.update_vtuber_birthdays(path) == [{"id": 1, "name": "A", "birthday": None}]
    assert json.loads(path.read_text(encoding="utf-8")) == [{"id": 1, "name": "A", "birthday": None}]
    assert main.update_vtuber_birthdays(tmp_path / "none.json") == []      # no saved list: nothing, no crash


def test_vtuber_birthdays_by_name():
    b = main.vtuber_birthdays([
        _vt(1, "Ninomae Ina'nis", "1998-02-20T00:00:00Z"), _vt(2, "No Birthday", None),
        _vt(3, "Zero Time", "0001-01-01T00:00:00Z"), _vt(4, "Same Name", "2000-01-02T00:00:00Z"),
        _vt(5, "same name", "2000-03-04T00:00:00Z"), _vt(6, "Twin", "2000-05-06T00:00:00Z"),
        _vt(7, "Twin", "2001-05-06T00:00:00Z"), {"junk": 1}, "junk"])
    assert b == {norm("Ninomae Inanis"): (2, 20), norm("Twin"): (5, 6)}   # clashing names are left out


def test_vtuber_birthday_is_appended_when_the_english_name_matches(data):
    births = main.vtuber_birthdays([_vt(1, "Ninomae Inanis", "1998-02-20T00:00:00Z"), _vt(2, "晴朗蓝", "2000-01-01T00:00:00Z")])
    idx = main.build_index(data, t2s_like, vtubers=VTUBERS, birthdays=births)
    added = {(c[0][0] or c[0][2]): c for c in idx["chars"][-4:]}
    assert added["Ninomae Ina'nis"][2:] == [0, 2, 20]                  # punctuation does not matter
    assert added["晴朗蓝"][2:] == [0]                                  # no English name: no lookup
    assert all(len(c) == 3 for k, c in added.items() if k != "Ninomae Ina'nis")
    no_births = main.build_index(data, t2s_like, vtubers=VTUBERS)
    assert all(len(c) == 3 for c in no_births["chars"][-4:])
