# agv-character-scraper

Builds the compact character / series index that [KKAFIO](../KKAFIO-refactor) uses to give
the LLM name and series hints in **Group Characters** and **Rename Characters**.
The index is built from the Kaggle MyAnimeList datasets (plus optional Japanese and Bangumi
data for ja_jp / zh_cn / zh_tw) by `main.py`.

## Published file

`agv_character_index.json` is published on GitHub Pages:

    https://reddeaddepresso.github.io/agv-character-scraper/agv_character_index.json

KKAFIO checks `https://api.github.com/repos/RedDeadDepresso/agv-character-scraper/commits`
and downloads the file again only when the latest commit changed, so **commit a new
`agv_character_index.json` to the branch served by Pages every time you rebuild it**.
KKAFIO caches it as `agv_character_index.json` in its per-user folder (`%APPDATA%/KKAFIO`).

## Rebuilding

```
python main.py --characters chars.csv --anime anime.csv --favorites fav.csv --show-columns
python main.py --characters chars.csv --anime anime.csv --favorites fav.csv \
       [--japanese-titles japanese.csv] [--bangumi-characters character.jsonlines]
```

The output (`agv_character_index.json`, `"version": 1`) is written next to the script; see
the docstring at the top of `main.py` for the format and the input columns.

## Keep in sync with KKAFIO

- `"version"` — KKAFIO only accepts `"version": 1` (`INDEX_VERSION` in `kkafio/cards/agv_index.py`).
  Bump both sides together if the format changes.
- `agv_text.py` — `norm()` / `name_parts()` produce the lookup keys and must stay identical
  to `kkafio/cards/agv_text.py`.
- `DOMINANCE` — same value as `kkafio.cards.agv_index.DOMINANCE`.

## Tests

```
pip install pytest
pytest
```
