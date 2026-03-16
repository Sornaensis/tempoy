from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class McpToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]


def _object_schema(*, properties: Dict[str, Any] | None = None, required: List[str] | None = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


TOOL_DEFINITIONS: List[McpToolDefinition] = [
    McpToolDefinition("health", "Get Tempoy API health and current session status.", _object_schema()),
    McpToolDefinition("capabilities", "Get Tempoy API capabilities, modes, and enabled endpoints.", _object_schema()),
    McpToolDefinition("list_projects", "List Jira projects visible through Tempoy.", _object_schema()),
    McpToolDefinition(
        "list_project_issue_types",
        "List issue types for a Tempoy-visible Jira project.",
        _object_schema(
            properties={"project_key": {"type": "string", "description": "Jira project key, such as ABC."}},
            required=["project_key"],
        ),
    ),
    McpToolDefinition(
        "get_project_create_schema",
        "Get Tempoy-normalized create metadata for a Jira project.",
        _object_schema(
            properties={"project_key": {"type": "string", "description": "Jira project key, such as ABC."}},
            required=["project_key"],
        ),
    ),
    McpToolDefinition(
        "search_tickets",
        "Search Jira tickets through Tempoy's safe search surface.",
        _object_schema(
            properties={
                "query": {"type": "string", "description": "Search text or issue key."},
                "project_key": {"type": "string", "description": "Optional Jira project key filter."},
                "issue_types": {"type": "array", "items": {"type": "string"}},
                "status_filters": {"type": "array", "items": {"type": "string"}},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        ),
    ),
    McpToolDefinition(
        "get_issue_details",
        "Get normalized details for a Jira issue through Tempoy.",
        _object_schema(
            properties={"issue_key": {"type": "string", "description": "Jira issue key, such as ABC-123."}},
            required=["issue_key"],
        ),
    ),
    McpToolDefinition(
        "analyze_hierarchy",
        "Get Tempoy's normalized hierarchy and related-work view for one or more issues.",
        _object_schema(
            properties={
                "issue_key": {"type": "string"},
                "issue_keys": {"type": "array", "items": {"type": "string"}},
                "include_parents": {"type": "boolean"},
                "include_linked_issues": {"type": "boolean"},
                "include_children": {"type": "boolean"},
                "depth": {"type": "integer", "minimum": 1},
            },
        ),
    ),
    McpToolDefinition("get_allocation_draft", "Get the current Tempoy allocation draft and derived daily context.", _object_schema()),
    McpToolDefinition(
        "create_ticket",
        "Create a Task in Jira through Tempoy's preview/apply guarded flow.",
        _object_schema(
            properties={
                "project_key": {"type": "string"},
                "summary": {"type": "string"},
                "description_text": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "string"},
                "apply": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            required=["project_key", "summary"],
        ),
    ),
    McpToolDefinition(
        "update_issue_fields",
        "Refine an issue through Tempoy's constrained preview/apply update flow.",
        _object_schema(
            properties={
                "issue_key": {"type": "string"},
                "summary": {"type": "string"},
                "description_text": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "string"},
                "parent_key": {"type": "string"},
                "acceptance_criteria_text": {"type": "string"},
                "apply": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            required=["issue_key"],
        ),
    ),
    McpToolDefinition(
        "add_ticket_to_allocation",
        "Add an issue to the Tempoy allocation draft.",
        _object_schema(
            properties={"issue_key": {"type": "string"}, "summary": {"type": "string"}},
            required=["issue_key"],
        ),
    ),
    McpToolDefinition(
        "remove_ticket_from_allocation",
        "Remove an issue from the Tempoy allocation draft.",
        _object_schema(
            properties={"issue_key": {"type": "string"}},
            required=["issue_key"],
        ),
    ),
    McpToolDefinition(
        "set_allocation_units",
        "Set allocation units for a draft row and let Tempoy rebalance remaining rows.",
        _object_schema(
            properties={"issue_key": {"type": "string"}, "allocation_units": {"type": "integer", "minimum": 0}},
            required=["issue_key", "allocation_units"],
        ),
    ),
    McpToolDefinition(
        "set_allocation_lock",
        "Lock or unlock an allocation draft row.",
        _object_schema(
            properties={"issue_key": {"type": "string"}, "locked": {"type": "boolean"}},
            required=["issue_key", "locked"],
        ),
    ),
    McpToolDefinition("equalize_allocation", "Equalize unlocked rows in the Tempoy allocation draft.", _object_schema()),
    McpToolDefinition("reset_allocation", "Reset the Tempoy allocation draft using Tempoy's reset semantics.", _object_schema()),
]


def get_tool_definitions() -> List[McpToolDefinition]:
    return list(TOOL_DEFINITIONS)


def get_tool_definition(tool_name: str) -> McpToolDefinition | None:
    normalized_tool_name = str(tool_name or "").strip()
    for definition in TOOL_DEFINITIONS:
        if definition.name == normalized_tool_name:
            return definition
    return None