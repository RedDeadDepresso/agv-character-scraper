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
     "infobox": "{{Infobox Crt\n|简体中文名= 远坂凛\n|别名={\n[第二中文名|远坂 凛]\n[英文名|Rin Tohsaka]\n"
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


def test_character_keeps_lowest_subject_id(data):
    subjects = main.select_subjects(data / "subject.jsonlines")
    assert main.first_subject_per_character(data / "subject-characters.jsonlines", subjects) == {
        100: 1, 103: 10, 104: 40}


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
    {"game": "Final Fantasy X", "title": {"en_us": "Final Fantasy X", "ja_jp": "ファイナルファンタジーX"},
     "aliases": ["FFX"]},
    {"game": "Fate", "title": {"en_us": "Fate", "zh_cn": "命运/停留之夜"}, "aliases": []},
    "junk entry",
]


def test_excluded_titles():
    ex = main.excluded_titles(SERIES)
    assert {norm("Final Fantasy X"), norm("FFX"), norm("ファイナルファンタジーX"), norm("Fate"),
            norm("命运/停留之夜")} <= ex
    assert "" not in ex


def test_subjects_in_series_json_are_excluded_by_any_title_or_alias(data):
    ex = main.excluded_titles(SERIES)
    # 40 matches by name, 1 by its Chinese title; 10 ("Fate/hollow ataraxia") only shares the word "Fate".
    assert sorted(main.select_subjects(data / "subject.jsonlines", ex)) == [10]


def test_excluded_subject_does_not_claim_its_characters(data):
    ex = main.excluded_titles([{"game": "Fate/stay night", "title": {}, "aliases": []}])
    idx = main.build_index(data, t2s_like, ex)
    assert len(idx["series"]) == 2                           # subjects 10 and 40
    rin = next(c for c in idx["chars"] if c[2] == 5000)
    assert idx["series"][rin[1][0]][1] == "Fate/hollow ataraxia"   # 100: 1 is gone -> next lowest, 10


def test_character_only_in_excluded_subjects_is_dropped(data):
    ex = main.excluded_titles([{"game": "ファイナルファンタジーX", "title": {}, "aliases": []}])
    idx = main.build_index(data, t2s_like, ex)
    assert 777 not in {c[2] for c in idx["chars"]}           # Tidus was only in subject 40


def test_no_exclusion_by_default(data):
    assert sorted(main.select_subjects(data / "subject.jsonlines")) == [1, 10, 40]


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
