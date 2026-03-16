"""E2E read-only integration test for MCP runtime against a live Tempoy API."""
from __future__ import annotations

import json
import sys

from tempoy_app.mcp_runtime import TempoyMcpRuntime


def main() -> int:
    r = TempoyMcpRuntime.create()
    passed = 0
    failed = 0

    def check(name: str, fn):
        nonlocal passed, failed
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        try:
            result = fn()
            print(json.dumps(result, indent=2, default=str)[:2000])
            passed += 1
            print(f"  --> PASS")
        except Exception as exc:
            print(f"  --> FAIL: {exc}")
            failed += 1

    # 1. health (no session needed)
    check("health", lambda: r.call_tool("health"))

    # 2. capabilities (no session needed)
    check("capabilities", lambda: r.call_tool("capabilities"))

    # 3. list_projects (session auto-start)
    check("list_projects", lambda: r.call_tool("list_projects"))

    # 4. list_project_issue_types (needs a project key from step 3)
    projects_result = r.call_tool("list_projects")
    projects = projects_result.get("projects", [])
    if projects:
        first_key = projects[0].get("key", "")
        check(
            f"list_project_issue_types (project={first_key})",
            lambda: r.call_tool("list_project_issue_types", {"project_key": first_key}),
        )
    else:
        print("\n  SKIP list_project_issue_types — no projects found")

    # 5. search_tickets with a query
    check("search_tickets (query='test')", lambda: r.call_tool("search_tickets", {"query": "test"}))

    # 6. search_tickets empty — known to 500 when no query provided
    check("search_tickets (empty query)", lambda: r.call_tool("search_tickets", {}))

    # Find an issue key for detail/hierarchy tests
    try:
        search_result = r.call_tool("search_tickets", {"query": "test"})
        issues = search_result.get("issues", search_result.get("results", []))
        issue_key = issues[0].get("key") if issues else None
    except Exception:
        issue_key = None

    # 7. get_issue_details
    if issue_key:
        check(
            f"get_issue_details (issue={issue_key})",
            lambda: r.call_tool("get_issue_details", {"issue_key": issue_key}),
        )
    else:
        print("\n  SKIP get_issue_details — no issues found in search")

    # 8. analyze_hierarchy
    if issue_key:
        check(
            f"analyze_hierarchy (issue={issue_key})",
            lambda: r.call_tool("analyze_hierarchy", {"issue_key": issue_key}),
        )
    else:
        print("\n  SKIP analyze_hierarchy — no issues found in search")

    # 9. get_allocation_draft
    check("get_allocation_draft", lambda: r.call_tool("get_allocation_draft"))

    # Shutdown
    r.shutdown()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
