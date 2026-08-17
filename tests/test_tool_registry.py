from __future__ import annotations

import pytest
from pydantic import BaseModel

from koko_pi_agent.tools import (
    ContributionOwner,
    ToolConflictError,
    ToolRegistry,
    ToolView,
)
from koko_pi_agent.tools.base import Tool, ToolResult


class _Params(BaseModel):
    pass


class _NamedTool(Tool):
    description = "registry test tool"
    params_model = _Params

    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, params: _Params) -> ToolResult:
        return ToolResult(output=self.name)


def test_duplicate_registration_is_rejected_and_keeps_original_tool() -> None:
    registry = ToolRegistry()
    original = _NamedTool("Echo")
    attempted = _NamedTool("Echo")
    registry.register(original)

    with pytest.raises(ToolConflictError, match="Echo"):
        registry.register(attempted)

    assert registry.get("Echo") is original


def test_registration_handle_closes_only_its_contribution_and_cleans_state() -> None:
    registry = ToolRegistry()
    original = _NamedTool("Echo")
    original_handle = registry.register(original)
    registry.disable("Echo")
    registry.mark_discovered("Echo")

    original_handle.close()

    assert original_handle.closed is True
    assert registry.get("Echo") is None
    replacement = _NamedTool("Echo")
    replacement_handle = registry.register(replacement)
    assert registry.is_enabled("Echo") is True
    assert registry.is_discovered("Echo") is False

    original_handle.close()

    assert registry.get("Echo") is replacement
    replacement_handle.close()
    assert registry.get("Echo") is None


def test_contribution_provenance_is_visible_and_reported_on_conflict() -> None:
    registry = ToolRegistry()
    existing_owner = ContributionOwner(
        extension_id="mewcode.builtin.toolset",
        source="builtin://toolset",
        runtime_id="runtime-a",
        generation=1,
    )
    attempted_owner = ContributionOwner(
        extension_id="mcp.context7",
        source="mcp:context7",
        runtime_id="runtime-a",
        generation=1,
    )
    original = _NamedTool("Echo")
    registry.register(original, owner=existing_owner)

    contributions = registry.list_contributions()

    assert len(contributions) == 1
    assert contributions[0].name == "Echo"
    assert contributions[0].tool is original
    assert contributions[0].owner == existing_owner
    assert contributions[0].sequence == 1

    with pytest.raises(ToolConflictError) as captured:
        registry.register(_NamedTool("Echo"), owner=attempted_owner)

    assert captured.value.existing == contributions[0]
    assert captured.value.attempted_owner == attempted_owner
    assert "builtin://toolset" in str(captured.value)
    assert "mcp:context7" in str(captured.value)


def test_borrowed_tool_view_is_read_only_and_never_closes_parent_contributions() -> (
    None
):
    parent = ToolRegistry()
    parent_owner = ContributionOwner(
        extension_id="mewcode.builtin-tools",
        source="builtin",
        runtime_id="parent-runtime",
        generation=3,
    )
    visible = _NamedTool("Visible")
    hidden = _NamedTool("Hidden")
    parent.register(visible, owner=parent_owner)
    parent.register(hidden, owner=parent_owner)

    view = ToolView.borrow(parent, names=("Visible",))

    assert view.get("Visible") is visible
    assert view.get("Hidden") is None
    assert view.list_contributions()[0].owner.borrowed_from == "parent-runtime"
    with pytest.raises(RuntimeError, match="read-only"):
        view.register(_NamedTool("Local"))

    view.close()
    view.close()

    assert view.list_contributions() == ()
    assert parent.get("Visible") is visible
    assert parent.get("Hidden") is hidden
