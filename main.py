"""
main.py — Build agv_character_index.json (the character / series index KKAFIO uses) from
the Bangumi Archive (https://github.com/bangumi/Archive). Run it with no arguments:

    python main.py

1. Fetch the Archive's aux/latest.json. If it equals ./latest.json (and the extracted files
   are in data/) nothing is downloaded; otherwise the release zip it points to
   (`browser_download_url`) is downloaded, checked against its sha256 digest, only the files
   this script needs are extracted into data/, the zip is deleted and latest.json is saved
   in the project root.
2. Subjects (subject.jsonlines): keep animation (type 2) and games (type 4) that carry one
   of TAGS ("visual novel", "japan", "jrpg"; Chinese spellings too), in `tags` or `meta_tags`.
   Subjects that appear in series.json (SERIES_URL, fetched, not saved) are left out: those
   whose id is the `bangumi_id` of a game there.
3. Characters (subject-characters.jsonlines): keep the links to those subjects. A character
   linked to several of them keeps only the earliest released one (the subject's `date`; the
   lowest subject id on a tie or without a date): the original work, not a sequel or an
   adaptation. Links of `type` 3 (客串, a guest / collab appearance) do not count while the
   character has another link (all of them are used if every link is a guest one). The kept subjects are the series of the index.
4. Series titles and characters' names are read from the dump fields and the wiki infobox
   (parsed with the bgm-tv-wiki package, see common/wiki_template.yml for the keys) in English, Japanese,
   Simplified and Traditional Chinese, together with every alias.
5. English titles: a series with no English title (Bangumi often has none) gets the one of
   the bangumi-data entry that has its Bangumi subject id (`sites`), or else the entry whose
   original title equals its Japanese title (compared with norm()); bangumi-data lists anime
   only, so this is done for animation subjects, not games. If that finds none,
   the longest Latin-script alias of the subject is used. data/data.json is downloaded from BANGUMI_DATA_URL when the latest commit of the
   bangumi-data repo differs from the one in bangumi_data_last_commit.txt (project root) or
   the file is missing. The English title is also an alias of the series.
6. English character names: a character with no English name gets the one of the MAL
   dataset's row whose `alternate_name` (Japanese) equals its Japanese name (compared with
   norm(), both orders of a two-part name); names shared by differently named rows are not
   used. The Kaggle archive is downloaded into data/ only if data/mal_characters_detailed.csv
   is missing; only that csv is extracted and the archive is deleted.
7. VTubers: the `vtuber` entries of the VTuber database (VTUBERS_URL, fetched, not saved) are
   appended after all the other characters, all in one series, "VTubers", with score 0 (the
   database has no popularity). Their names come from `name` (cn / jp / en and the rest,
   `extra` included). The birthday of a VTuber with an English name is found on Amatsukaze by
   that name (norm(); the list is AMATSUKAZE_URL, saved in data/amatsukaze_vtubers.json and
   extended on the next run until the first saved VTuber).
8. Write agv_character_index.json (version 1):

  {
    "version": 1,
    "langs":   ["en_us", "ja_jp", "zh_cn", "zh_tw"],     # language of each position below
    "series":  [["Fate/stay night", "Fate/stay night", "命运/停留之夜", "命運/停留之夜"], ...],
    "aliases": {"<norm title>": <series idx>, ...},      # every title and alias -> series
    "chars":   [[["Tohsaka, Rin", "遠坂, 凛", "远坂, 凛", "遠坂, 凛"], [series idx], collects, 2, 3], ...],
    "names":   {"<norm name form>": [<chars idx>, ...]}  # every name and alias, both orders
  }

A character's birthday (the infobox `生日`, see parse_birthday) is the month and day appended to
its entry, as in the example ("遠坂, 凛" was born on 3 February); characters without one (or
with one that cannot be read) have just the three first items.

Names are "Last, First" where the order is known. Text missing in a language is "" and
KKAFIO falls back to another language. "zh_tw" comes from the Simplified text through OpenCC
(pip install OpenCC); without it the index just has no zh_tw. A character's score is its
`collects` (收藏数) in the Archive.
"""

from __future__ import annotations

import hashlib
import csv
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

from agv_text import name_parts, norm
from bgm_tv_wiki import try_parse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"                      # the extracted .jsonlines files
LATEST_FILE = ROOT / "latest.json"           # the release the files in data/ come from
BANGUMI_COMMIT_FILE = ROOT / "bangumi_data_last_commit.txt"   # commit data/data.json comes from
OUTPUT = ROOT / "agv_character_index.json"

LATEST_URL = "https://raw.githubusercontent.com/bangumi/Archive/refs/heads/master/aux/latest.json"
# The gacha games the other scraper covers; the subjects with their `bangumi_id` are left out.
SERIES_URL = "https://raw.githubusercontent.com/RedDeadDepresso/gacha-character-scraper/refs/heads/main/config/series.json"
# The VTuber database (https://github.com/dd-center/vdb); its `vtuber` entries are added last.
VTUBERS_URL = "https://vdb.vtbs.moe/json/list.json"
VTUBER_SERIES = "VTubers"
VTUBER_TYPES = frozenset({"vtuber"})         # not "group" (agencies), "fan" or "misc"
# Amatsukaze (https://amatsukaze.rl404.com) has the VTubers' birthdays; the VTuber database has none.
# Its list is saved in data/ and only the VTubers newer than the first saved one are fetched.
AMATSUKAZE_URL = "https://amatsukaze.rl404.com/api/vtubers"
AMATSUKAZE_FILE = "amatsukaze_vtubers.json"
AMATSUKAZE_LIMIT = 50                         # VTubers per page
AMATSUKAZE_DELAY = 0.3                        # seconds between two pages
# bangumi-data (https://github.com/bangumi-data/bangumi-data): English titles for the series
# Bangumi has none for. data.json is downloaded again when the repo's latest commit changes.
BANGUMI_DATA_COMMITS_URL = "https://api.github.com/repos/bangumi-data/bangumi-data/commits?sha=master&per_page=1"
BANGUMI_DATA_URL = "https://raw.githubusercontent.com/bangumi-data/bangumi-data/refs/heads/master/dist/data.json"
BANGUMI_DATA_NAME = "data.json"              # in DATA_DIR
# The Kaggle MyAnimeList characters dataset (https://www.kaggle.com/datasets/syahrulapriansyah2/anime-characters):
# English names for the characters Bangumi has none for. `alternate_name` is the Japanese
# name, `name` the English one ("Last, First"). Downloaded once; kept in DATA_DIR.
MAL_URL = "https://www.kaggle.com/api/v1/datasets/download/syahrulapriansyah2/anime-characters"
MAL_ARCHIVE = "anime-characters.zip"
MAL_CSV = "mal_characters_detailed.csv"

# The only files of the archive that are needed (the rest is skipped).
SUBJECTS = "subject.jsonlines"
LINKS = "subject-characters.jsonlines"
CHARACTERS = "character.jsonlines"
NEEDED = (SUBJECTS, LINKS, CHARACTERS)

# Subject types (common/subject_platforms.yml): 2 anime, 4 game.
SUBJECT_TYPES = frozenset({2, 4})
ANIME = 2                                     # bangumi-data only lists anime
# A subject is kept if one of its tags / meta_tags is one of these (case-insensitive).
TAGS = frozenset({"visual novel", "视觉小说", "japan", "日本", "jrpg"})

_CJK = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _open(url: str):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "agv-character-scraper"}), timeout=60)


def fetch_json(url: str):
    with _open(url) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_latest() -> dict:
    """The Archive's aux/latest.json (the release asset of the newest dump)."""
    return fetch_json(LATEST_URL)


def fetch_series() -> list:
    """The gacha-character-scraper's config/series.json (not saved)."""
    return fetch_json(SERIES_URL)


def fetch_vtubers() -> list[dict]:
    """The `vtbs` array of the VTuber database's list.json (not saved)."""
    data = fetch_json(VTUBERS_URL)
    return data["vtbs"] if isinstance(data, dict) else data


def amatsukaze_page_url(page: int) -> str:
    """One page of the list, newest debut first. Only the name, birthday, page, limit and sort
    parameters are sent (the filters are empty: every VTuber is listed)."""
    return AMATSUKAZE_URL + "?" + urllib.parse.urlencode([
        ("name", ""), ("birthday_day", ""), ("start_birthday_month", ""), ("end_birthday_month", ""),
        ("page", page), ("limit", AMATSUKAZE_LIMIT), ("sort", "-debut_date")])


def update_vtuber_birthdays(path: Path) -> list[dict]:
    """The Amatsukaze VTubers (newest debut first) as [{"id", "name", "birthday"}], saved in `path`.
    A saved list is only extended: pages are fetched until the first VTuber that is already saved.
    Nothing is saved unless that point was reached, so the file never has a gap; when the fetch
    fails the saved list (or none) is returned, the birthdays are optional."""
    known: list[dict] = []
    if path.exists():
        try:
            known = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            print(f"{path.name} is not valid JSON, fetching everything again")
    first = known[0].get("id") if known else None
    fresh: list[dict] = []
    try:
        page, reached = 1, False
        while not reached:
            data = fetch_json(amatsukaze_page_url(page))
            items = [v for v in (data.get("data") if isinstance(data, dict) else None) or [] if isinstance(v, dict)]
            for v in items:
                if first is not None and v.get("id") == first:
                    reached = True
                    break
                fresh.append({"id": v.get("id"), "name": v.get("name"), "birthday": v.get("birthday")})
            if len(items) < AMATSUKAZE_LIMIT:                       # the last page
                reached = True
            page += 1
            if not reached:
                time.sleep(AMATSUKAZE_DELAY)
    except Exception as e:
        print(f"Could not fetch the VTuber birthdays ({e}): using the {len(known)} saved VTubers")
        return known
    if fresh or not path.exists():
        known = fresh + known
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Amatsukaze VTubers: {len(fresh)} new, {len(known)} saved")
    return known


def vtuber_birthdays(records: list[dict]) -> dict[str, tuple[int, int]]:
    """norm(name) -> (month, day) of the Amatsukaze VTubers that have a birthday. A name that
    several VTubers share with different birthdays is left out (it cannot be told apart)."""
    out: dict[str, tuple[int, int]] = {}
    clash: set[str] = set()
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get("name"), str):
            continue
        day = str(rec.get("birthday") or "")[:10]
        if not day[:4].isdigit() or int(day[:4]) < 1000:            # null or the zero time 0001-01-01
            continue
        birthday = parse_birthday(day)
        key = norm(rec["name"])
        if birthday == (0, 0) or not key:
            continue
        if out.setdefault(key, birthday) != birthday:
            clash.add(key)
    return {k: v for k, v in out.items() if k not in clash}


def download(url: str, dest: Path, digest: str = "") -> None:
    """Stream `url` to `dest`; `digest` is "sha256:<hex>" (checked when given)."""
    sha = hashlib.sha256()
    done, last = 0, -1
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _open(url) as r, dest.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        while chunk := r.read(1 << 20):
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if total and done * 20 // total != last:
                last = done * 20 // total
                print(f"  downloaded {done / 1e6:.0f} / {total / 1e6:.0f} MB", flush=True)
    algo, _, expected = digest.partition(":")
    if algo == "sha256" and sha.hexdigest() != expected.lower():
        raise ValueError(f"sha256 mismatch for {dest.name}: expected {expected}, got {sha.hexdigest()}")


def extract_needed(archive: Path, data_dir: Path, names: tuple[str, ...] = NEEDED) -> None:
    """Extract only `names` from the zip (by file name, wherever it sits in the archive)."""
    with zipfile.ZipFile(archive) as z:
        members = {Path(n).name: n for n in z.namelist() if not n.endswith("/")}
        missing = [n for n in names if n not in members]
        if missing:
            raise ValueError(f"{archive.name} does not contain {', '.join(missing)}")
        for name in names:
            part = data_dir / (name + ".part")        # never leave a truncated file under its real name
            try:
                with z.open(members[name]) as src, part.open("wb") as dst:
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)
                os.replace(part, data_dir / name)
            finally:
                part.unlink(missing_ok=True)


def update_mal_dataset() -> Path:
    """Make data/mal_characters_detailed.csv exist: download the Kaggle archive, extract only
    the csv, delete the archive. Nothing is downloaded if the csv is already there."""
    path = DATA_DIR / MAL_CSV
    if path.exists():
        print(f"{MAL_CSV} already exists — skipping the download.")
        return path
    archive = DATA_DIR / MAL_ARCHIVE
    print(f"Downloading the MyAnimeList characters dataset ({MAL_URL})...")
    try:
        download(MAL_URL, archive)
        extract_needed(archive, DATA_DIR, (MAL_CSV,))
    except Exception as e:
        sys.exit(f"Could not get {MAL_CSV} from {MAL_URL}: {e}")
    finally:
        archive.unlink(missing_ok=True)
    return path


def update_bangumi_data() -> Path:
    """Make data/data.json the one of bangumi-data's latest commit and return its path.

    The commit the file was downloaded at is kept in BANGUMI_COMMIT_FILE; the file is
    downloaded again when the latest commit differs or the file is missing. If the commit
    can't be checked or the download fails, an existing file is used."""
    path = DATA_DIR / BANGUMI_DATA_NAME
    try:
        latest = fetch_json(BANGUMI_DATA_COMMITS_URL)[0]["sha"].strip()
        try:
            saved = BANGUMI_COMMIT_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            saved = ""
        if saved == latest and path.exists():
            print(f"bangumi-data is up to date ({latest[:7]}) — skipping the download.")
            return path
        print(f"Downloading bangumi-data data.json ({latest[:7]})...")
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        try:
            download(BANGUMI_DATA_URL, part)
            json.loads(part.read_text(encoding="utf-8"))          # reject a truncated / non-JSON file
            os.replace(part, path)
        finally:
            part.unlink(missing_ok=True)
        BANGUMI_COMMIT_FILE.write_text(latest, encoding="utf-8")
    except Exception as e:
        if not path.exists():
            sys.exit(f"Could not get bangumi-data ({BANGUMI_DATA_COMMITS_URL}): {e}")
        print(f"Could not update bangumi-data ({e}) — using the data.json already in {DATA_DIR}.")
    return path


def data_complete() -> bool:
    return LATEST_FILE.exists() and all((DATA_DIR / n).exists() for n in NEEDED)


def update_data() -> None:
    """Make data/ hold the newest dump; download nothing if latest.json is unchanged."""
    try:
        remote = fetch_latest()
    except Exception as e:
        if data_complete():
            print(f"Could not fetch latest.json ({e}) — using the data already in {DATA_DIR}.")
            return
        sys.exit(f"Could not fetch {LATEST_URL}: {e}")

    try:
        local = json.loads(LATEST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        local = None
    if local == remote and data_complete():
        print(f"Archive is up to date ({remote.get('name')}) — skipping the download.")
        return

    print(f"Downloading {remote['name']} ({remote.get('size', 0) / 1e6:.0f} MB)...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_FILE.unlink(missing_ok=True)            # data/ is inconsistent until we finish
    archive = DATA_DIR / remote["name"]
    try:
        download(remote["browser_download_url"], archive, remote.get("digest", ""))
        print("Extracting " + ", ".join(NEEDED) + "...")
        extract_needed(archive, DATA_DIR)
    finally:
        archive.unlink(missing_ok=True)
    LATEST_FILE.write_text(json.dumps(remote, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Reading the dump
# ---------------------------------------------------------------------------

def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def tag_names(rec: dict) -> Iterator[str]:
    """Names in `tags` ([{"name", "count"}, ...]) and `meta_tags` (["...", ...])."""
    for field in ("tags", "meta_tags"):
        for t in rec.get(field) or ():
            name = t.get("name") if isinstance(t, dict) else t
            if isinstance(name, str):
                yield name.strip().casefold()


def excluded_ids(series: list) -> frozenset[int]:
    """The Bangumi subject id (`bangumi_id`) of every game in series.json; entries without
    one (missing, 0 or not a number) are ignored."""
    out = {_int(entry.get("bangumi_id")) for entry in series if isinstance(entry, dict)}
    out.discard(0)
    return frozenset(out)


def select_subjects(path: Path, exclude: frozenset[int] = frozenset()) -> dict[int, dict]:
    """id -> subject record for the animation / games that carry one of TAGS, minus the
    subjects whose id is in `exclude`."""
    out: dict[int, dict] = {}
    skipped: list[str] = []
    for rec in read_jsonl(path):
        if _int(rec.get("type")) not in SUBJECT_TYPES or TAGS.isdisjoint(tag_names(rec)):
            continue
        sid = _int(rec.get("id"))
        if sid in exclude:
            skipped.append(rec.get("name") or str(sid))
            continue
        out[sid] = rec
    if exclude:
        print(f"excluded {len(skipped)} subjects that are in series.json"
              + (f": {', '.join(skipped[:10])}{' ...' if len(skipped) > 10 else ''}" if skipped else ""))
    return out


def release_key(rec: dict, sid: int) -> tuple[str, int]:
    """Sort key for "the original work": the earlier release date first (the `date` of the
    dump, "YYYY-MM-DD"; a subject without one sorts after the dated ones), then the lower id."""
    date = str(rec.get("date") or "").strip()
    return (date if re.match(r"\d{4}", date) else "9999", sid)


GUEST_TYPE = 3   # `type` of a subject-characters link: 1 main, 2 supporting, 3 guest (collab)


def first_subject_per_character(path: Path, subjects: dict[int, dict]) -> dict[int, int]:
    """character id -> the earliest released of the kept subjects it appears in (lowest id
    on a tie), i.e. the game rather than its anime adaptation. Subjects where the character
    is only a guest (`type` 3, a collab character) are passed over, unless every kept
    subject it appears in is such a one."""
    keys = {sid: release_key(rec, sid) for sid, rec in subjects.items()}
    best: dict[int, tuple[bool, tuple[str, int], int]] = {}   # cid -> (guest, release key, sid)
    lowest: dict[int, int] = {}
    for rec in read_jsonl(path):
        sid, cid = _int(rec.get("subject_id")), _int(rec.get("character_id"))
        if sid in subjects and cid:
            cand = (_int(rec.get("type")) == GUEST_TYPE, keys[sid], sid)
            if cid not in best or cand < best[cid]:
                best[cid] = cand
            if cid not in lowest or sid < lowest[cid]:
                lowest[cid] = sid
    out = {cid: c[2] for cid, c in best.items()}
    moved = sum(1 for cid, sid in out.items() if sid != lowest[cid])
    print(f"characters whose subject is not the lowest id but the earliest release / a non-guest one: {moved}")
    return out


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def _scalar(wiki, key: str) -> str:
    v = wiki.get(key)
    return v.strip() if isinstance(v, str) else ""


_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_DAYS_IN = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]      # February: leap day allowed
_BIRTH_CJK = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})")                           # 9月28日, 2000年9月28日
_BIRTH_YMD = re.compile(r"\d{4}\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})")      # 2000-09-28
_BIRTH_MD = re.compile(r"(?:^|\D)(\d{1,2})\s*[-/.]\s*(\d{1,2})(?:\D|$)")        # 9/28, 28/9
_BIRTH_MONTH_DAY = re.compile(r"\b([a-z]+)\.?\s*(\d{1,2})(?:st|nd|rd|th)?\b")     # September 28
_BIRTH_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?([a-z]+)\b\.?")   # 28 September


def parse_birthday(text: str) -> tuple[int, int]:
    """(month, day) out of the free text of a Bangumi `生日` field: "9月28日",
    "2000年9月28日（天秤座）", "9/28", "28/9" (a first number above 12 is the day), "2000-09-28",
    "September 28" or "28th of September". A year is ignored. (0, 0) when there is no valid
    month and day (a month alone, "不明", an impossible date such as 2月30日)."""
    t = unicodedata.normalize("NFKC", text or "").lower()

    def ok(m: int, d: int) -> bool:
        return 1 <= m <= 12 and 1 <= d <= _DAYS_IN[m]

    for pattern in (_BIRTH_CJK, _BIRTH_YMD):
        if m := pattern.search(t):
            if ok(int(m[1]), int(m[2])):
                return int(m[1]), int(m[2])
    if m := _BIRTH_MD.search(t):
        a, b = int(m[1]), int(m[2])
        if a > 12 >= b:
            a, b = b, a
        if ok(a, b):
            return a, b
    for m in _BIRTH_MONTH_DAY.finditer(t):
        if m[1] in _MONTHS and ok(_MONTHS[m[1]], int(m[2])):
            return _MONTHS[m[1]], int(m[2])
    for m in _BIRTH_DAY_MONTH.finditer(t):
        if m[2] in _MONTHS and ok(_MONTHS[m[2]], int(m[1])):
            return _MONTHS[m[2]], int(m[1])
    return 0, 0


def character_birthday(rec: dict) -> tuple[int, int]:
    """(month, day) of a character's infobox `生日`, (0, 0) when it has none."""
    wiki = try_parse(rec.get("infobox") or "")
    return parse_birthday(" ".join(i.value for i in wiki.get_as_items("生日") if i.value))


def _aliases(wiki) -> list[tuple[str, str]]:
    """The 别名 array as (key, value) pairs; scalar / empty values are handled."""
    return [(i.key, i.value.strip()) for i in wiki.get_as_items("别名") if i.value and i.value.strip()]


def _alias(items: list[tuple[str, str]], *keys: str) -> str:
    return next((v for k, v in items if k in keys), "")


def japanese_name(raw: str) -> str:
    """Family name first, two parts ("遠坂 凛") -> "遠坂, 凛"; anything else as it is."""
    parts = (raw or "").split()                     # also splits on U+3000
    return f"{parts[0]}, {parts[1]}" if len(parts) == 2 else " ".join(parts)


def chinese_name(raw: str) -> str:
    """A transliterated foreign name is written Given·Family ("鲁路修·兰佩路基"), so it
    becomes "兰佩路基, 鲁路修"; a name without "·" stays whole."""
    parts = [p.strip() for p in re.split(r"[·・]", raw or "") if p.strip()]
    if len(parts) < 2:
        return parts[0] if parts else ""
    return f"{'·'.join(parts[1:])}, {parts[0]}"


def name_forms(raw: str) -> set[str]:
    """Every normalised spelling `raw` is looked up by: whole, and both orders of two parts."""
    forms = {norm(raw)}
    for cand in (japanese_name(raw), chinese_name(raw)):
        last, first = name_parts(cand)
        forms |= {norm(last + first), norm(first + last)}
    forms.discard("")
    return forms


def english_titles(items: list[dict]) -> tuple[dict[int, str], dict[str, str]]:
    """English titles from bangumi-data's `items` ({"title": original title,
    "titleTranslate": {"en": [...]}, "sites": [{"site": "bangumi", "id": "123"}, ...]}):
    -> (Bangumi subject id -> title, norm(original title) -> title). The first English
    title of an entry and the first entry for an id / title win."""
    by_id: dict[int, str] = {}
    by_title: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        en = next((t.strip() for t in (item.get("titleTranslate") or {}).get("en") or ()
                   if isinstance(t, str) and t.strip()), "")
        if not en:
            continue
        for site in item.get("sites") or ():
            if isinstance(site, dict) and site.get("site") == "bangumi" and (sid := _int(site.get("id"))):
                by_id.setdefault(sid, en)
        if isinstance(item.get("title"), str) and (key := norm(item["title"])):
            by_title.setdefault(key, en)
    return by_id, by_title


def read_english_names(path: Path) -> dict[str, str]:
    """norm(Japanese name) -> English name, from the Kaggle csv (`alternate_name`, `name`).
    A Japanese name shared by characters with different English names is left out: without
    more than the name there is no telling which one is meant."""
    seen: dict[str, set[str]] = {}
    csv.field_size_limit(2**31 - 1)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            en = (row.get("name") or "").strip()
            if en and (key := norm(row.get("alternate_name") or "")):
                seen.setdefault(key, set()).add(en)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def english_name(raw: str, table: dict[str, str]) -> str:
    """English name for the Japanese `raw` ("" if none): its own spelling first, then the
    other ways it is looked up (both orders of a two-part name)."""
    first = norm(raw)
    for key in [first, *sorted(name_forms(raw) - {first})]:
        if key in table:
            return table[key]
    return ""


OPENCC_CONFIG = "s2tw"   # Simplified -> Traditional with the Taiwan standard glyphs, no phrase changes


def opencc_s2t() -> Callable[[str], str] | None:
    """Simplified -> Traditional (Taiwan standard) through OpenCC, or None when it is not installed."""
    try:
        from opencc import OpenCC
    except ImportError:
        return None
    try:
        return OpenCC(OPENCC_CONFIG).convert
    except Exception:
        return OpenCC(OPENCC_CONFIG + ".json").convert


def _latin_title(text: str) -> bool:
    """Text with no CJK that has at least 3 letters (so not an initialism like "CB")."""
    return bool(text) and not _CJK.search(text) and sum(c.isalpha() for c in text) >= 3


def subject_titles(rec: dict, s2t: Callable[[str], str] | None) -> tuple[list[str], list[str]]:
    """-> (title per language [en, ja, zh_cn, zh_tw], every title / alias of the subject)."""
    wiki = try_parse(rec.get("infobox") or "")
    items = _aliases(wiki)
    name = (rec.get("name") or "").strip()
    zh = (rec.get("name_cn") or "").strip() or _scalar(wiki, "中文名") or _alias(items, "简体中文名")
    ja = name if _CJK.search(name) else (_alias(items, "日文名") or name)
    en = _alias(items, "英文名") or ("" if _CJK.search(name) else name)
    tw = _alias(items, "繁体中文名") or (s2t(zh) if s2t and zh else "")
    return [en, ja, zh, tw], [name, zh, en, ja, tw, *(v for _, v in items)]


def character_names(rec: dict, s2t: Callable[[str], str] | None) -> tuple[list[str], list[str]]:
    """-> (name per language [en, ja, zh_cn, zh_tw], every name / alias of the character)."""
    wiki = try_parse(rec.get("infobox") or "")
    items = _aliases(wiki)
    name = (rec.get("name") or "").strip()
    romaji = _alias(items, "罗马字")
    if _CJK.search(name):
        ja = japanese_name(name)
    else:
        ja = japanese_name(_alias(items, "日文名")) or name
    en = japanese_name(romaji) if romaji else (_alias(items, "英文名") or ("" if _CJK.search(name) else name))
    zh_raw = _scalar(wiki, "简体中文名")
    zh = chinese_name(zh_raw)
    tw = s2t(zh) if s2t and zh else ""
    extra = [s2t(v) for k, v in items if s2t and k == "第二中文名"]
    return [en, ja, zh, tw], [name, zh_raw, tw, *(v for _, v in items), *extra]


def vtuber_names(rec: dict, s2t: Callable[[str], str] | None) -> tuple[list[str], list[str]]:
    """-> (name per language [en, ja, zh_cn, zh_tw], every name / alias of the VTuber).

    `name` is {"cn": ..., "jp": ..., "en": ..., "extra": [...], "default": "cn"} but the keys
    are inconsistent ("CN", "zh-cn", "ID", ...): the known ones fill the languages, all of
    them (and `extra`) are lookup names. "default" only names a key and is not a name."""
    name = rec.get("name") if isinstance(rec.get("name"), dict) else {}
    by_key: dict[str, str] = {}
    every: list[str] = []
    for key, value in name.items():
        if key == "default":
            continue
        for v in value if isinstance(value, list) else [value]:
            if isinstance(v, str) and v.strip():
                every.append(v.strip())
                if isinstance(value, str):
                    by_key.setdefault(key.casefold(), v.strip())
    zh = next((by_key[k] for k in ("cn", "zh-cn", "zh", "ch", "cn+") if k in by_key), "")
    tw = s2t(zh) if s2t and zh else ""
    per = [by_key.get("en", ""), by_key.get("jp", ""), zh, tw]
    if not any(per) and every:
        per[0] = every[0]
    return per, every + ([tw] if tw else [])


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def build_index(data_dir: Path, s2t: Callable[[str], str] | None = None,
                exclude: frozenset[int] = frozenset(), vtubers: list[dict] = (),
                english: tuple[dict[int, str], dict[str, str]] | None = None,
                english_names: dict[str, str] | None = None,
                birthdays: dict[str, tuple[int, int]] | None = None) -> dict:
    subjects = select_subjects(data_dir / SUBJECTS, exclude)
    print(f"subjects (anime / games with a matching tag): {len(subjects)}")
    char_subject = first_subject_per_character(data_dir / LINKS, subjects)
    print(f"characters linked to them: {len(char_subject)}")

    langs = ["en_us", "ja_jp", "zh_cn"] + (["zh_tw"] if s2t else [])
    n = len(langs)

    def per_lang(values: list[str]) -> list[str]:
        return values[:n]

    series_idx = {sid: i for i, sid in enumerate(sorted(set(char_subject.values())))}
    series: list[list[str]] = [[]] * len(series_idx)
    aliases: dict[str, int] = {}
    english_by = [0, 0, 0]                           # English titles found by id / by title / from an alias
    for sid, i in series_idx.items():                # ascending id: the oldest work keeps a clash
        titles, every = subject_titles(subjects[sid], s2t)
        if english and not titles[0] and _int(subjects[sid].get("type")) == ANIME:
            # Bangumi has no English title: ask bangumi-data. Anime only: a game must not take the
            # title of its anime adaptation, which often has the same Japanese title.
            by_id, by_title = english
            en = by_id.get(sid, "")
            if en:
                english_by[0] += 1
            else:                                    # no entry with this subject id: Japanese title
                en = next((by_title[k] for t in (titles[1], subjects[sid].get("name") or "")
                           if (k := norm(t)) in by_title), "")
                english_by[1] += bool(en)
            if en:
                titles[0] = en
                every.append(en)
        if not titles[0]:                            # still none: a Latin-script alias (the longest, so a
            titles[0] = max((t for t in every if _latin_title(t)), key=len, default="")   # full title beats "SAO")
            english_by[2] += bool(titles[0])
        series[i] = per_lang(titles)
        for t in every:
            if key := norm(t):
                aliases.setdefault(key, i)

    chars: list[list] = []
    names: dict[str, list[int]] = {}
    english_chars = 0
    wanted = set(char_subject)
    for rec in sorted((r for r in read_jsonl(data_dir / CHARACTERS) if _int(r.get("id")) in wanted),
                      key=lambda r: _int(r.get("id"))):
        per, every = character_names(rec, s2t)
        if english_names and not per[0] and (en := english_name(rec.get("name") or "", english_names)):
            per[0] = en                              # Bangumi has no English name: ask the MAL dataset
            every.append(en)
            english_chars += 1
        if not any(per):
            continue
        ci = len(chars)
        entry = [per_lang(per), [series_idx[char_subject[_int(rec["id"])]]], _int(rec.get("collects"))]
        if (birthday := character_birthday(rec)) != (0, 0):
            entry += birthday                        # month, day: only when known
        chars.append(entry)
        for text in every:
            for f in name_forms(text):
                if not names.get(f) or names[f][-1] != ci:
                    names.setdefault(f, []).append(ci)

    if english is not None:
        print(f"English series titles from bangumi-data: {english_by[0]} by subject id, "
              f"{english_by[1]} by Japanese title, {english_by[2]} from a Latin alias, "
              f"{sum(1 for t in series if not t[0])} series still without one")
    if english_names is not None:
        print(f"English character names from the MAL dataset: {english_chars} added, "
              f"{sum(1 for c in chars if not c[0][0])} characters still without one")
    if vtubers:                                      # last: after every anime / game character
        vi = len(series)
        series.append([VTUBER_SERIES] * n)
        for title in (VTUBER_SERIES, "VTuber"):
            aliases.setdefault(norm(title), vi)
        count = 0
        for rec in vtubers:
            if not isinstance(rec, dict) or rec.get("type") not in VTUBER_TYPES:
                continue
            per, every = vtuber_names(rec, s2t)
            if not any(per):
                continue
            ci = len(chars)
            entry = [per_lang(per), [vi], 0]         # the database has no popularity: score 0
            if birthdays and per[0] and (birthday := birthdays.get(norm(per[0]))):
                entry += birthday                    # the English name found on Amatsukaze
            chars.append(entry)
            count += 1
            for text in every:
                for f in name_forms(text):
                    if not names.get(f) or names[f][-1] != ci:
                        names.setdefault(f, []).append(ci)
        print(f"VTubers: {count}")

    print(f"series: {len(series)}  aliases: {len(aliases)}  characters: {len(chars)}  name keys: {len(names)}")
    return {"version": 1, "langs": langs, "series": series, "aliases": aliases,
            "chars": chars, "names": names}


def main() -> None:
    try:
        exclude = excluded_ids(fetch_series())
    except Exception as e:
        sys.exit(f"Could not fetch {SERIES_URL}: {e}")
    try:
        vtubers = fetch_vtubers()
    except Exception as e:
        sys.exit(f"Could not fetch {VTUBERS_URL}: {e}")
    birthdays = vtuber_birthdays(update_vtuber_birthdays(DATA_DIR / AMATSUKAZE_FILE))
    update_data()
    s2t = opencc_s2t()
    if s2t is None:
        print("OpenCC is not installed: the index will have no Traditional Chinese (pip install OpenCC).")
    english = english_titles(json.loads(update_bangumi_data().read_text(encoding="utf-8")).get("items", []))
    english_names = read_english_names(update_mal_dataset())
    index = build_index(DATA_DIR, s2t, exclude, vtubers, english, english_names, birthdays)
    OUTPUT.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
