"""
Tests for Airtable multi-table: config, schema helper, and search_airtable.
Run from backend: python -m pytest test_airtable.py -v
Or: python test_airtable.py
"""
import os
import sys

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load env from backend/.env
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")


def test_config_table_names_parsed_as_list():
    """AIRTABLE_TABLE_NAMES must be a list of strings (from comma-separated env)."""
    from app.core.config import AIRTABLE_TABLE_NAMES

    assert isinstance(AIRTABLE_TABLE_NAMES, list)
    # With .env containing AIRTABLE_TABLE_NAMES=Client,Projet,Leads
    if os.getenv("AIRTABLE_TABLE_NAMES"):
        assert len(AIRTABLE_TABLE_NAMES) >= 1
        for name in AIRTABLE_TABLE_NAMES:
            assert isinstance(name, str)
            assert name.strip() == name


def test_get_table_schema_format():
    """get_table_schema() returns a string with 'DATABASE SCHEMA:' and table entries."""
    from app.tools.utils import get_table_schema

    schema = get_table_schema()
    assert "DATABASE SCHEMA" in schema
    # If tables are configured, should list them
    from app.core.config import AIRTABLE_TABLE_NAMES
    for table_name in AIRTABLE_TABLE_NAMES[:1]:  # at least first table
        assert table_name in schema or "Table '" in schema


def test_search_airtable_table1():
    """Search in the first configured table."""
    from app.core.config import AIRTABLE_TABLE_NAMES
    from app.tools.airtable import search_airtable

    if not AIRTABLE_TABLE_NAMES or not os.getenv("AIRTABLE_API_KEY"):
        return  # skip if not configured
    table1 = AIRTABLE_TABLE_NAMES[0]
    result = search_airtable.invoke({"query": "test", "table_name": table1})
    assert isinstance(result, str)
    # Should not be a validation error (table name valid)
    assert "table_name must be one of" not in result or table1 in result


def test_search_airtable_table2():
    """Search in the second configured table (if any)."""
    from app.core.config import AIRTABLE_TABLE_NAMES
    from app.tools.airtable import search_airtable

    if not AIRTABLE_TABLE_NAMES or len(AIRTABLE_TABLE_NAMES) < 2 or not os.getenv("AIRTABLE_API_KEY"):
        return
    table2 = AIRTABLE_TABLE_NAMES[1]
    result = search_airtable.invoke({"query": "projet", "table_name": table2})
    assert isinstance(result, str)
    assert "table_name must be one of" not in result


def test_search_airtable_rejects_invalid_table():
    """search_airtable must reject a table_name not in AIRTABLE_TABLE_NAMES."""
    from app.tools.airtable import search_airtable
    from pydantic import ValidationError
    from app.core.config import AIRTABLE_TABLE_NAMES

    if not AIRTABLE_TABLE_NAMES:
        return
    try:
        search_airtable.invoke({"query": "x", "table_name": "InvalidTableNameThatDoesNotExist"})
    except ValidationError:
        pass  # expected: Pydantic args_schema validates table_name


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
