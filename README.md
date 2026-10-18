# agv-character-scraper

Builds the character / series index that KKAFIO uses to give the LLM name and series hints in
**Group Characters** and **Rename Characters**. The data comes from the
[Bangumi Archive](https://github.com/bangumi/Archive).

```
python main.py
```

No arguments. Install the dependencies first with `pip install -r requirements.txt`
(`bgm-tv-wiki` for the infoboxes; `OpenCC` is optional, for Traditional Chinese). The script

1. fetches the Archive's [`aux/latest.json`](https://raw.githubusercontent.com/bangumi/Archive/refs/heads/master/aux/latest.json).
   If it is the same as `latest.json` in the project root the download is skipped; otherwise it
   downloads the release zip, verifies its sha256, extracts only `subject.jsonlines`,
   `subject-characters.jsonlines` and `character.jsonlines` into `data/`, deletes the zip and
   saves `latest.json` in the project root;
2. keeps the animation and games tagged `visual novel`, `japan` or `jrpg` (`TAGS` in `main.py`),
   except the ones that appear in the gacha-character-scraper's
   [`config/series.json`](https://raw.githubusercontent.com/RedDeadDepresso/gacha-character-scraper/refs/heads/main/config/series.json)
   (fetched every run, not saved): a subject is left out when one of its names, titles or
   aliases equals a game, title or alias there;
3. gives each of their characters the subject with the lowest id as its series;
4. reads the Japanese, Chinese and English names and aliases of the series and the characters
   (wiki infoboxes are parsed with [`bgm-tv-wiki`](https://pypi.org/project/bgm-tv-wiki/));
5. appends the VTubers: the `vtuber` entries of the
   [VTuber database](https://vdb.vtbs.moe/json/list.json) (fetched every run, not saved; `group`,
   `fan` and `misc` entries are skipped) come after all the other characters, all in one series,
   `VTubers`, with score 0 because the database has no popularity;
6. writes `agv_character_index.json`.

The format is described at the top of `main.py`.

## Published file

`agv_character_index.json` is served by GitHub Pages:

    https://reddeaddepresso.github.io/agv-character-scraper/agv_character_index.json

KKAFIO checks `https://api.github.com/repos/RedDeadDepresso/agv-character-scraper/commits` and
downloads the file again only when the latest commit changed, so **commit the new
`agv_character_index.json` after every run**.

## Keep in sync with KKAFIO

* `"version"`: KKAFIO only accepts `"version": 1` (`INDEX_VERSION` in `kkafio/cards/agv_index.py`).
* `agv_text.py`: `norm()` / `name_parts()` produce the lookup keys and must stay identical to
  `kkafio/cards/agv_text.py`.

## Tests

```
pip install pytest
pytest
```

The `bangumi/common` constants (subject types, infobox keys) are referenced in `main.py` comments.
