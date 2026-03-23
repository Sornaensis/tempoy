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
        "Search Jira tickets through Tempoy's safe search surface. Supports filtering by assignee, labels, priority, date ranges, and parent issue.",
        _object_schema(
            properties={
                "query": {"type": "string", "description": "Free-text search across summary, description, and comments — or an exact issue key like ABC-123."},
                "project_key": {"type": "string", "description": "Optional Jira project key filter."},
                "issue_types": {"type": "array", "items": {"type": "string"}, "description": "Filter by issue type names, e.g. ['Task', 'Bug']."},
                "status_filters": {"type": "array", "items": {"type": "string"}, "description": "Filter by status names, e.g. ['In Progress', 'To Do']."},
                "assignee": {"type": "string", "description": "Filter by assignee: 'currentUser' for yourself, 'unassigned' for open tickets, or a Jira account ID."},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "Filter by labels. Default matches ALL labels (AND). Set labels_match to 'any' for OR logic."},
                "labels_match": {"type": "string", "enum": ["all", "any"], "description": "How to match labels: 'all' (default) requires every label, 'any' matches tickets with at least one."},
                "priority": {"type": "string", "description": "Filter by priority name, e.g. 'High', 'Critical', 'Blocker'."},
                "updated_after": {"type": "string", "description": "Only return tickets updated on or after this date. Use YYYY-MM-DD format."},
                "created_after": {"type": "string", "description": "Only return tickets created on or after this date. Use YYYY-MM-DD format."},
                "parent_key": {"type": "string", "description": "Filter to children of a specific parent issue, e.g. 'PROJ-100'."},
                "custom_fields": {"type": "object", "additionalProperties": True, "description": "Filter by configured custom fields. Keys are field names (from discover_custom_fields), values are the filter value. For option fields pass a string, for multi_option pass an array."},
                "order_by": {"type": "string", "enum": ["updated", "created", "priority"], "description": "Sort order. Default is 'updated' (newest first)."},
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
                "assignee_account_id": {"type": "string", "description": "Jira account ID of the assignee, or empty string to unassign"},
                "apply": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            required=["issue_key"],
        ),
    ),
    McpToolDefinition(
        "get_issue_transitions",
        "Get available status transitions for a Jira issue through Tempoy.",
        _object_schema(
            properties={"issue_key": {"type": "string", "description": "Jira issue key, such as ABC-123."}},
            required=["issue_key"],
        ),
    ),
    McpToolDefinition(
        "transition_issue",
        "Move a Jira issue to a new status through Tempoy's preview/apply guarded flow.",
        _object_schema(
            properties={
                "issue_key": {"type": "string", "description": "Jira issue key, such as ABC-123."},
                "transition_name": {"type": "string", "description": "Target status or transition name (case-insensitive match)."},
                "apply": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            required=["issue_key", "transition_name"],
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
    McpToolDefinition(
        "discover_custom_fields",
        "List the custom fields configured for update through the MCP API, "
        "including their types and validation constraints.",
        _object_schema(),
    ),
    McpToolDefinition(
        "update_custom_fields",
        "Update one or more configured custom fields on a Jira issue. "
        "Use discover_custom_fields first to learn available fields and their constraints.",
        _object_schema(
            properties={
                "issue_key": {"type": "string", "description": "Jira issue key, such as ABC-123."},
                "fields": {
                    "type": "object",
                    "description": "Map of custom field name to value. "
                                   "Field names must match configured names from discover_custom_fields.",
                    "additionalProperties": True,
                },
                "apply": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            required=["issue_key", "fields"],
        ),
    ),
    McpToolDefinition(
        "search_users",
        "Search for Jira users by name or email. Returns account IDs that can be used with the assignee filter in search_tickets or with update_issue_fields.",
        _object_schema(
            properties={
                "query": {"type": "string", "description": "Name or email to search for."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Maximum results to return (default 10)."},
            },
            required=["query"],
        ),
    ),
    McpToolDefinition(
        "get_recent_worklogs",
        "Get a summary of issues the current user has logged time against recently. "
        "Returns issue keys with total seconds and last logged date, sorted by most recent.",
        _object_schema(
            properties={
                "days_back": {"type": "integer", "minimum": 1, "maximum": 90, "description": "Number of days to look back (default 7)."},
            },
        ),
    ),
]


def get_tool_definitions() -> List[McpToolDefinition]:
    return list(TOOL_DEFINITIONS)


def get_tool_definition(tool_name: str) -> McpToolDefinition | None:
    normalized_tool_name = str(tool_name or "").strip()
    for definition in TOOL_DEFINITIONS:
        if definition.name == normalized_tool_name:
            return definition
    return None