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
   with a name, title or alias equal to a game / title / alias there (compared with norm()).
3. Characters (subject-characters.jsonlines): keep the links to those subjects. A character
   linked to several of them keeps only the one with the lowest subject id (the original
   work, not a sequel). The kept subjects are the series of the index.
4. Series titles and characters' names are read from the dump fields and the wiki infobox
   (parsed with the bgm-tv-wiki package, see common/wiki_template.yml for the keys) in English, Japanese,
   Simplified and Traditional Chinese, together with every alias.
5. VTubers: the `vtuber` entries of the VTuber database (VTUBERS_URL, fetched, not saved) are
   appended after all the other characters, all in one series, "VTubers", with score 0 (the
   database has no popularity). Their names come from `name` (cn / jp / en and the rest,
   `extra` included).
6. Write assets/agv_character_index.json (version 1):

  {
    "version": 1,
    "langs":   ["en_us", "ja_jp", "zh_cn", "zh_tw"],     # language of each position below
    "series":  [["Fate/stay night", "Fate/stay night", "命运/停留之夜", "命運/停留之夜"], ...],
    "aliases": {"<norm title>": <series idx>, ...},      # every title and alias -> series
    "chars":   [[["Tohsaka, Rin", "遠坂, 凛", "远坂, 凛", "遠坂, 凛"], [series idx], collects], ...],
    "names":   {"<norm name form>": [<chars idx>, ...]}  # every name and alias, both orders
  }

Names are "Last, First" where the order is known. Text missing in a language is "" and
KKAFIO falls back to another language. "zh_tw" comes from the Simplified text through OpenCC
(pip install OpenCC); without it the index just has no zh_tw. A character's score is its
`collects` (收藏数) in the Archive.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

from agv_text import name_parts, norm
from bgm_tv_wiki import try_parse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"                      # the extracted .jsonlines files
LATEST_FILE = ROOT / "latest.json"           # the release the files in data/ come from
OUTPUT = ROOT / "assets" / "agv_character_index.json"

LATEST_URL = "https://raw.githubusercontent.com/bangumi/Archive/refs/heads/master/aux/latest.json"
# The gacha games the other scraper covers; subjects with one of these titles are left out.
SERIES_URL = "https://raw.githubusercontent.com/RedDeadDepresso/gacha-character-scraper/refs/heads/main/config/series.json"
# The VTuber database (https://github.com/dd-center/vdb); its `vtuber` entries are added last.
VTUBERS_URL = "https://vdb.vtbs.moe/json/list.json"
VTUBER_SERIES = "VTubers"
VTUBER_TYPES = frozenset({"vtuber"})         # not "group" (agencies), "fan" or "misc"

# The only files of the archive that are needed (the rest is skipped).
SUBJECTS = "subject.jsonlines"
LINKS = "subject-characters.jsonlines"
CHARACTERS = "character.jsonlines"
NEEDED = (SUBJECTS, LINKS, CHARACTERS)

# Subject types (common/subject_platforms.yml): 2 anime, 4 game.
SUBJECT_TYPES = frozenset({2, 4})
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


def extract_needed(archive: Path, data_dir: Path) -> None:
    """Extract only NEEDED from the zip (by file name, wherever it sits in the archive)."""
    with zipfile.ZipFile(archive) as z:
        members = {Path(n).name: n for n in z.namelist() if not n.endswith("/")}
        missing = [n for n in NEEDED if n not in members]
        if missing:
            raise ValueError(f"{archive.name} does not contain {', '.join(missing)}")
        for name in NEEDED:
            with z.open(members[name]) as src, (data_dir / name).open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)


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


def excluded_titles(series: list) -> frozenset[str]:
    """norm() of every game name, title (any language) and alias in series.json."""
    out: set[str] = set()
    for entry in series:
        if not isinstance(entry, dict):
            continue
        texts = [entry.get("game"), *(entry.get("title") or {}).values(), *(entry.get("aliases") or [])]
        out.update(norm(t) for t in texts if isinstance(t, str))
    out.discard("")
    return frozenset(out)


def select_subjects(path: Path, exclude: frozenset[str] = frozenset()) -> dict[int, dict]:
    """id -> subject record for the animation / games that carry one of TAGS, minus the
    subjects having a title or alias that is in `exclude` (norm() forms, compared whole)."""
    out: dict[int, dict] = {}
    skipped: list[str] = []
    for rec in read_jsonl(path):
        if _int(rec.get("type")) not in SUBJECT_TYPES or TAGS.isdisjoint(tag_names(rec)):
            continue
        if exclude and not exclude.isdisjoint(norm(t) for t in subject_titles(rec, None)[1]):
            skipped.append(rec.get("name") or str(rec.get("id")))
            continue
        out[_int(rec.get("id"))] = rec
    if exclude:
        print(f"excluded {len(skipped)} subjects that are in series.json"
              + (f": {', '.join(skipped[:10])}{' ...' if len(skipped) > 10 else ''}" if skipped else ""))
    return out


def first_subject_per_character(path: Path, subjects: dict[int, dict]) -> dict[int, int]:
    """character id -> lowest id among the kept subjects it appears in."""
    best: dict[int, int] = {}
    for rec in read_jsonl(path):
        sid, cid = _int(rec.get("subject_id")), _int(rec.get("character_id"))
        if sid in subjects and cid and (cid not in best or sid < best[cid]):
            best[cid] = sid
    return best


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def _scalar(wiki, key: str) -> str:
    v = wiki.get(key)
    return v.strip() if isinstance(v, str) else ""


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


def opencc_s2t() -> Callable[[str], str] | None:
    """Simplified -> Traditional through OpenCC, or None when it is not installed."""
    try:
        from opencc import OpenCC
    except ImportError:
        return None
    try:
        return OpenCC("s2t").convert
    except Exception:
        return OpenCC("s2t.json").convert


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
                exclude: frozenset[str] = frozenset(), vtubers: list[dict] = ()) -> dict:
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
    for sid, i in series_idx.items():                # ascending id: the oldest work keeps a clash
        titles, every = subject_titles(subjects[sid], s2t)
        series[i] = per_lang(titles)
        for t in every:
            if key := norm(t):
                aliases.setdefault(key, i)

    chars: list[list] = []
    names: dict[str, list[int]] = {}
    wanted = set(char_subject)
    for rec in sorted((r for r in read_jsonl(data_dir / CHARACTERS) if _int(r.get("id")) in wanted),
                      key=lambda r: _int(r.get("id"))):
        per, every = character_names(rec, s2t)
        if not any(per):
            continue
        ci = len(chars)
        chars.append([per_lang(per), [series_idx[char_subject[_int(rec["id"])]]], _int(rec.get("collects"))])
        for text in every:
            for f in name_forms(text):
                if not names.get(f) or names[f][-1] != ci:
                    names.setdefault(f, []).append(ci)

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
            chars.append([per_lang(per), [vi], 0])   # the database has no popularity: score 0
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
        exclude = excluded_titles(fetch_series())
    except Exception as e:
        sys.exit(f"Could not fetch {SERIES_URL}: {e}")
    try:
        vtubers = fetch_vtubers()
    except Exception as e:
        sys.exit(f"Could not fetch {VTUBERS_URL}: {e}")
    update_data()
    s2t = opencc_s2t()
    if s2t is None:
        print("OpenCC is not installed: the index will have no Traditional Chinese (pip install OpenCC).")
    index = build_index(DATA_DIR, s2t, exclude, vtubers)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
