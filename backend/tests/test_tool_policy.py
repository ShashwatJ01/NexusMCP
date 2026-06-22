from core.mcp_client import _infer_access
from core.schemas import ToolAccess


def test_annotations_override_name_heuristic_for_read_only_tool() -> None:
    assert _infer_access("get_report", {"readOnlyHint": True}) is ToolAccess.READ


def test_destructive_and_mutating_names_are_classified() -> None:
    assert _infer_access("delete_customer", {}) is ToolAccess.DELETE
    assert _infer_access("update_customer", {}) is ToolAccess.WRITE
    assert _infer_access("search", {}) is ToolAccess.UNKNOWN

