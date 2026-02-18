"""
Airtable tool: list, search, or query records with optional sort (e.g. "who paid the most" → sort by amount desc).
Never raises: always returns a string (Error: ... or result) so the LLM can self-correct.
"""

from typing import Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.config import AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAMES
from app.tools.utils import (
    get_link_fields_config,
    get_primary_field_name,
    get_table_field_names,
)


def _get_valid_table_names() -> list[str]:
    """Return list of allowed table names for validation and description."""
    return list(AIRTABLE_TABLE_NAMES) if AIRTABLE_TABLE_NAMES else []


def _normalize_table_name(value: str) -> str | None:
    """Return matching table name from config or None if invalid. Never raises."""
    valid = _get_valid_table_names()
    if not valid:
        return value or None
    if value in valid:
        return value
    v_lower = (value or "").strip().lower()
    for name in valid:
        if name.lower() == v_lower:
            return name
    return None


class SearchAirtableInput(BaseModel):
    """Input for search_airtable tool. Use the DATABASE SCHEMA to choose table_name and sort_by field names."""

    query: str = Field(
        description="Search term, or leave empty to list records (optionally sorted). For 'who paid the most' use empty query + sort_by=amount field (e.g. CTV) + sort_direction='desc'."
    )
    table_name: str = Field(
        description=f"Target table. Must be one of: {', '.join(_get_valid_table_names()) or 'none configured'}"
    )
    sort_by: Optional[str] = Field(
        default=None,
        description="Field name to sort by (must exist in the table schema, e.g. 'CTV', 'Nom', 'Date'). Use for max/min questions: 'who paid the most' → sort_by='CTV', sort_direction='desc'."
    )
    sort_direction: Optional[Literal["asc", "desc"]] = Field(
        default=None,
        description="'desc' for highest first (e.g. who paid the most), 'asc' for lowest first. Required when sort_by is set."
    )
    max_records: Optional[int] = Field(
        default=None,
        description="Max number of records to return. For 'the one who paid the most' use 1; for top 5 use 5. Default 100 when listing, 10 when searching."
    )


def _is_list_all_intent(query: str) -> bool:
    """True if the user wants to list all records (no search filter)."""
    q = (query or "").strip().lower()
    if not q:
        return True
    return q in ("*", "all", "tous", "toutes", "liste", "list")

def _build_sort_param(sort_by: Optional[str], sort_direction: Optional[str]) -> Optional[list]:
    """Build pyairtable sort list: ['Field'] for asc, ['-Field'] for desc."""
    if not sort_by or not sort_by.strip():
        return None
    direction = (sort_direction or "asc").strip().lower()
    prefix = "-" if direction == "desc" else ""
    return [f"{prefix}{sort_by.strip()}"]


def _is_airtable_record_id(val: object) -> bool:
    """True if value looks like an Airtable record ID (rec...)."""
    if not isinstance(val, str) or not val.strip():
        return False
    return val.strip().startswith("rec")


def _normalize_link_value(value: object) -> list[str]:
    """Return a list of record IDs from a link field value (list or single ID)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if _is_airtable_record_id(v)]
    if _is_airtable_record_id(value):
        return [str(value).strip()]
    return []


def _resolve_link_fields(
    api: object,
    base_id: str,
    table_name: str,
    records: list[dict],
) -> None:
    """
    Resolve linked record IDs to display values in each record's fields (in-place).
    Uses get_link_fields_config and fetches linked records; replaces ID(s) with
    the display field value (e.g. client name / entreprise).
    """
    link_config = get_link_fields_config(table_name)
    if not link_config:
        return
    cache: dict[tuple[str, str], str] = {}

    for record in records:
        fields = record.get("fields")
        if not isinstance(fields, dict):
            continue
        for cfg in link_config:
            field_name = cfg.get("field_name")
            linked_table_name = cfg.get("linked_table_name")
            display_field = cfg.get("display_field")
            if not field_name or not linked_table_name or not display_field:
                continue
            value = fields.get(field_name)
            ids = _normalize_link_value(value)
            if not ids:
                continue
            try:
                linked_table = api.table(base_id, linked_table_name)
            except Exception:
                continue
            display_values: list[str] = []
            for rec_id in ids:
                cache_key = (linked_table_name, rec_id)
                if cache_key in cache:
                    display_values.append(cache[cache_key])
                    continue
                try:
                    linked_record = linked_table.get(rec_id)
                    linked_fields = linked_record.get("fields") or {}
                    disp = linked_fields.get(display_field)
                    if disp is None:
                        disp = "(inconnu)"
                    else:
                        disp = str(disp).strip() if disp else "(inconnu)"
                    cache[cache_key] = disp
                    display_values.append(disp)
                except Exception:
                    cache[cache_key] = "(inconnu)"
                    display_values.append("(inconnu)")
            fields[field_name] = ", ".join(display_values) if display_values else ""
    return None


def _records_to_markdown_table(rows: list[dict], max_columns: int = 8) -> str:
    """
    Convert a list of row dicts (e.g. Airtable fields) into a Markdown table string.
    Column order from first row; limited to max_columns for readability.
    """
    if not rows:
        return ""
    all_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for k in row.keys():
            if k and k not in seen:
                seen.add(k)
                all_keys.append(k)
    columns = all_keys[:max_columns]
    if not columns:
        return ""

    def cell_text(val: object) -> str:
        if val is None:
            return ""
        s = str(val).strip()
        s = s.replace("|", "\\|").replace("\n", " ").replace("\r", "")
        return s[:80] + ("…" if len(s) > 80 else "")

    lines = []
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(":---" for _ in columns) + " |"
    lines.append(header)
    lines.append(sep)
    for row in rows:
        if not isinstance(row, dict):
            continue
        cells = [cell_text(row.get(c)) for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _search_airtable_impl(
    query: str,
    table_name: str,
    sort_by: Optional[str] = None,
    sort_direction: Optional[Literal["asc", "desc"]] = None,
    max_records: Optional[int] = None,
) -> str:
    """
    Inner implementation: never raises, always returns a string (Error: ... or result).
    """
    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        msg = "Error: Airtable is not configured (missing AIRTABLE_API_KEY or AIRTABLE_BASE_ID)."
        print(f"[AIRTABLE] Error: {msg}")
        return msg

    resolved_table = _normalize_table_name(table_name)
    valid_tables = _get_valid_table_names()
    if resolved_table is None and valid_tables:
        msg = f"Error: table_name must be one of: {', '.join(valid_tables)}."
        print(f"[AIRTABLE] Error: {msg}")
        return msg
    table_name = resolved_table or table_name

    try:
        from pyairtable import Api

        api = Api(AIRTABLE_API_KEY)
        table = api.table(AIRTABLE_BASE_ID, table_name)
    except Exception as e:
        msg = f"Error connecting to Airtable: {e}"
        print(f"[AIRTABLE] Error: {msg}")
        return msg

    sort_param = _build_sort_param(sort_by, sort_direction or "asc")
    limit = max_records if max_records is not None and max_records > 0 else None

    # List (with optional sort): empty query → get records, optionally sorted
    if _is_list_all_intent(query):
        formula_desc = f"list (sort={sort_param})" if sort_param else "list all"
        print(f"[AIRTABLE] Querying table '{table_name}': {formula_desc}")
        try:
            kwargs = {"max_records": limit or 100}
            if sort_param:
                kwargs["sort"] = sort_param
            records = table.all(**kwargs)
            if not records:
                out = f"No records in table '{table_name}' (base is empty for this table)."
                print(f"[AIRTABLE] Success: 0 records found.")
                return out
            _resolve_link_fields(api, AIRTABLE_BASE_ID, table_name, records)
            out = _records_to_markdown_table([r.get("fields", {}) for r in records])
            print(f"[AIRTABLE] Success: {len(records)} records found.")
            return out
        except Exception as e:
            fields_hint = get_table_field_names(table_name)
            hint = f" Available fields for table '{table_name}': {fields_hint}." if fields_hint else ""
            msg = f"Error listing table: {e}.{hint}"
            print(f"[AIRTABLE] Error: {msg}")
            return msg

    # Text search
    primary_field = get_primary_field_name(table_name)
    if not primary_field:
        print(f"[AIRTABLE] Querying table '{table_name}' (full scan):")
        print(f"[AIRTABLE]   query = {query!r}")
        try:
            kwargs = {"max_records": limit or 50}
            if sort_param:
                kwargs["sort"] = sort_param
            records = table.all(**kwargs)
            query_lower = query.strip().lower()
            matches = []
            for r in records:
                fields = r.get("fields") or {}
                for val in fields.values():
                    if val and isinstance(val, str) and query_lower in val.lower():
                        matches.append(fields)
                        break
            if not matches:
                out = f"No records matching '{query}' in table '{table_name}'."
                print(f"[AIRTABLE] Success: 0 records found.")
                return out
            records_for_links = [{"fields": m} for m in matches[: limit or 10]]
            _resolve_link_fields(api, AIRTABLE_BASE_ID, table_name, records_for_links)
            out = _records_to_markdown_table([r.get("fields", {}) for r in records_for_links])
            print(f"[AIRTABLE] Success: {len(matches)} records found.")
            return out
        except Exception as e:
            fields_hint = get_table_field_names(table_name)
            hint = f" Available fields: {fields_hint}." if fields_hint else ""
            msg = f"Error searching table: {e}.{hint}"
            print(f"[AIRTABLE] Error: {msg}")
            return msg

    safe_query = query.strip().replace("'", "\\'")
    formula = f"SEARCH(LOWER('{safe_query}'), LOWER({{{primary_field}}}))"
    print(f"[AIRTABLE] Querying table '{table_name}' with formula:")
    print(f"[AIRTABLE]   formula = {formula}")
    try:
        kwargs = {"formula": formula, "max_records": limit or 20}
        if sort_param:
            kwargs["sort"] = sort_param
        records = table.all(**kwargs)
    except Exception as e:
        fields_hint = get_table_field_names(table_name)
        hint = f" Available fields for table '{table_name}': {fields_hint}." if fields_hint else ""
        msg = f"Error running search: {e}.{hint}"
        print(f"[AIRTABLE] Error: {msg}")
        return msg

    if not records:
        out = f"No records matching '{query}' in table '{table_name}'."
        print(f"[AIRTABLE] Success: 0 records found.")
        return out
    records_subset = records[: limit or 10]
    _resolve_link_fields(api, AIRTABLE_BASE_ID, table_name, records_subset)
    out = _records_to_markdown_table([r.get("fields", {}) for r in records_subset])
    print(f"[AIRTABLE] Success: {len(records)} records found.")
    return out


@tool(args_schema=SearchAirtableInput)
def search_airtable(
    query: str,
    table_name: str,
    sort_by: Optional[str] = None,
    sort_direction: Optional[Literal["asc", "desc"]] = None,
    max_records: Optional[int] = None,
) -> str:
    """
    Query Airtable: list records, search by text, or get top/bottom by a field (sort).
    Use the DATABASE SCHEMA to pick the right table and field names.
    - List all: query='', table_name='Client'.
    - Who paid the most: query='', table_name='Client', sort_by='CTV', sort_direction='desc', max_records=1.
    - Search by name: query='Dupont', table_name='Client'.
    """
    try:
        return _search_airtable_impl(
            query=query,
            table_name=table_name,
            sort_by=sort_by,
            sort_direction=sort_direction,
            max_records=max_records,
        )
    except Exception as e:
        msg = f"Error: {e!s}"
        print(f"[AIRTABLE] Error: {msg}")
        return msg
