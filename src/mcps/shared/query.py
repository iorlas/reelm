import re
from typing import overload

from anyascii import anyascii
from cel import evaluate
from pydantic import BaseModel

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _normalize(text: str) -> str:
    return _NON_ALNUM.sub("", anyascii(text).lower())


def _fuzzy_match(d: dict, needle: str) -> bool:
    """Normalized search across all string values in a dict."""
    needle_norm = _normalize(needle)
    for v in d.values():
        if isinstance(v, str) and needle_norm in _normalize(v):
            return True
    return False


def apply_query[T: BaseModel](
    items: list[T],
    filter_expr: str | None = None,
    search: str | None = None,
    sort_by: str | None = None,
    limit: int | None = None,
) -> list[T]:
    """Apply CEL filter, fuzzy search, sorting, and limit. Returns original models."""
    if not items:
        return items

    data = [item.model_dump() for item in items]
    key_field = next((k for k in ("index", "id", "name", "path") if data and k in data[0]), None)
    if key_field:
        key_to_item = {getattr(item, key_field): item for item in items}
    else:
        key_to_item = dict(enumerate(items))
        for i, d in enumerate(data):
            d["_idx"] = i
        key_field = "_idx"

    if search:
        data = [d for d in data if _fuzzy_match(d, search)]

    if filter_expr:
        try:
            data = [d for d in data if evaluate(filter_expr, d)]
        except Exception as e:
            msg = f"Invalid filter expression: {filter_expr!r}. Use CEL syntax, e.g. status == 'downloading', progress > 50. Error: {e}"
            raise ValueError(msg) from e

    if sort_by:
        desc = sort_by.startswith("-")
        key = sort_by.lstrip("-")
        data = sorted(data, key=lambda x: x.get(key, 0), reverse=desc)

    if limit and limit > 0:
        data = data[:limit]

    return [key_to_item[d[key_field]] for d in data]


@overload
def project[T: BaseModel](items: list[T], fields: None = None) -> list[T]: ...
@overload
def project[T: BaseModel](items: list[T], fields: list[str]) -> list[dict]: ...


def project[T: BaseModel](
    items: list[T],
    fields: list[str] | None = None,
) -> list[T] | list[dict]:
    if not fields:
        return items

    if not items:
        return []

    sample = items[0].model_dump()
    key_field = next((k for k in ("index", "id") if k in sample), None)
    include = set(fields) | ({key_field} if key_field else set())
    return [item.model_dump(include=include) for item in items]


def _tsv_from_rows(keys: list[str], rows: list[dict]) -> str:
    lines = ["\t".join(keys)]
    lines.extend("\t".join(str(row[k]) for k in keys) for row in rows)
    return "\n".join(lines)


def to_tsv(items: list) -> str:  # accepts list[BaseModel] or list[dict]
    if not items:
        return ""
    first = items[0]
    if isinstance(first, BaseModel):
        keys = list(first.model_fields.keys())
        return _tsv_from_rows(keys, [item.model_dump() for item in items])
    keys = list(first.keys())
    return _tsv_from_rows(keys, items)
