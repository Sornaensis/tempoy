from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from tempoy_app.services.issue_catalog import IssueCatalog


class JiraAnalysisService:
    def __init__(self, *, jira_base_url: str):
        self._jira_base_url = str(jira_base_url or "").rstrip("/")
        self._issue_catalog = IssueCatalog()

    def normalize_issue(self, issue: Dict) -> Dict[str, object]:
        key = str(issue.get("key") or "")
        issue_id = str(issue.get("id") or "")
        fields = issue.get("fields") or {}
        parent_text, parent_lookup_key = self._issue_catalog.extract_parent_info(fields)
        parent_key, parent_summary = self._issue_catalog.split_parent_text(parent_text, parent_lookup_key)
        return {
            "key": key,
            "id": issue_id,
            "summary": str(fields.get("summary") or ""),
            "description_text": self._extract_description_text(fields.get("description")),
            "issue_type": self._extract_named_field(fields.get("issuetype")),
            "status": self._extract_named_field(fields.get("status")),
            "priority": self._extract_named_field(fields.get("priority")),
            "project_key": self._extract_project_key(fields.get("project")),
            "labels": self._normalize_labels(fields.get("labels")),
            "parent": {
                "key": parent_key,
                "summary": parent_summary,
            },
            "children": [],
            "linked_issues": self._normalize_linked_issues(fields.get("issuelinks")),
            "hierarchy_level": self._infer_hierarchy_level(fields.get("issuetype")),
            "assignee": self._extract_assignee(fields.get("assignee")),
            "raw_url": f"{self._jira_base_url}/browse/{key}" if self._jira_base_url and key else "",
        }

    def normalize_issues(self, issues: Iterable[Dict]) -> List[Dict[str, object]]:
        return [self.normalize_issue(issue) for issue in issues if isinstance(issue, dict)]

    def build_hierarchy_payload(
        self,
        root_issues: Iterable[Dict],
        *,
        related_issues_by_key: Optional[Dict[str, Dict]] = None,
        include_parents: bool = True,
        include_linked_issues: bool = True,
        depth: int = 1,
        include_children: bool = False,
        children_by_parent_key: Optional[Dict[str, List[Dict]]] = None,
    ) -> Dict[str, object]:
        normalized_roots = self.normalize_issues(root_issues)
        related_lookup = related_issues_by_key or {}
        parents: list[Dict[str, object]] = []
        linked: list[Dict[str, object]] = []
        children_all: list[Dict[str, object]] = []
        related_epic: Dict[str, object] | None = None
        related_initiative: Dict[str, object] | None = None
        missing_links: list[str] = []
        warnings: list[str] = []

        if depth > 1:
            warnings.append("Depth greater than 1 is not implemented yet")

        seen_parent_keys: set[str] = set()
        seen_linked_keys: set[str] = set()
        for root_issue in normalized_roots:
            parent = root_issue.get("parent") if isinstance(root_issue, dict) else {}
            if include_parents and isinstance(parent, dict):
                parent_key = str(parent.get("key") or "").strip()
                if parent_key and parent_key not in seen_parent_keys:
                    seen_parent_keys.add(parent_key)
                    parent_issue = related_lookup.get(parent_key)
                    if parent_issue is None:
                        missing_links.append(parent_key)
                    else:
                        normalized_parent = self.normalize_issue(parent_issue)
                        parents.append(normalized_parent)
                        if normalized_parent.get("hierarchy_level") == "epic" and related_epic is None:
                            related_epic = normalized_parent
                        if normalized_parent.get("hierarchy_level") == "initiative" and related_initiative is None:
                            related_initiative = normalized_parent

            if include_linked_issues:
                for linked_issue in root_issue.get("linked_issues", []) if isinstance(root_issue, dict) else []:
                    linked_key = str((linked_issue or {}).get("key") or "").strip()
                    if not linked_key or linked_key in seen_linked_keys:
                        continue
                    seen_linked_keys.add(linked_key)
                    related_issue = related_lookup.get(linked_key)
                    if related_issue is None:
                        missing_links.append(linked_key)
                        continue
                    linked.append(self.normalize_issue(related_issue))

            if include_children and isinstance(root_issue, dict):
                root_key = str(root_issue.get("key") or "")
                raw_children = (children_by_parent_key or {}).get(root_key, [])
                normalized_children = self.normalize_issues(raw_children)
                root_issue["children"] = normalized_children
                children_all.extend(normalized_children)

        payload: Dict[str, object] = {
            "root_issue": normalized_roots[0] if len(normalized_roots) == 1 else None,
            "root_issues": normalized_roots,
            "parents": parents if include_parents else [],
            "children": children_all,
            "descendants": [],
            "linked_issues": linked if include_linked_issues else [],
            "related_epic": related_epic,
            "related_initiative": related_initiative,
            "missing_links": sorted(set(missing_links)),
            "warnings": warnings,
        }
        return payload

    @staticmethod
    def _extract_named_field(value: object) -> str:
        if isinstance(value, dict):
            return str(value.get("name") or "")
        return str(value or "")

    @staticmethod
    def _extract_project_key(value: object) -> str:
        if isinstance(value, dict):
            return str(value.get("key") or "")
        return ""

    @staticmethod
    def _extract_assignee(value: object) -> Optional[Dict[str, str]]:
        if not isinstance(value, dict):
            return None
        account_id = str(value.get("accountId") or "").strip()
        display_name = str(value.get("displayName") or "").strip()
        email = str(value.get("emailAddress") or "").strip()
        if not account_id and not display_name:
            return None
        return {"account_id": account_id, "display_name": display_name, "email": email}

    @staticmethod
    def _normalize_labels(value: object) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item or "").strip()]

    def _normalize_linked_issues(self, value: object) -> List[Dict[str, str]]:
        if not isinstance(value, list):
            return []
        linked: List[Dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            link_type = item.get("type") or {}
            outward_issue = item.get("outwardIssue") or {}
            inward_issue = item.get("inwardIssue") or {}
            if outward_issue:
                linked.append(
                    {
                        "direction": "outward",
                        "relationship": str((link_type or {}).get("outward") or ""),
                        "key": str(outward_issue.get("key") or ""),
                        "summary": str(((outward_issue.get("fields") or {}).get("summary")) or ""),
                    }
                )
            if inward_issue:
                linked.append(
                    {
                        "direction": "inward",
                        "relationship": str((link_type or {}).get("inward") or ""),
                        "key": str(inward_issue.get("key") or ""),
                        "summary": str(((inward_issue.get("fields") or {}).get("summary")) or ""),
                    }
                )
        return linked

    @staticmethod
    def _infer_hierarchy_level(issue_type_value: object) -> str:
        return JiraAnalysisService.infer_hierarchy_level(name=JiraAnalysisService._extract_named_field(issue_type_value))

    @staticmethod
    def infer_hierarchy_level(*, name: str, subtask: bool = False) -> str:
        issue_type_name = str(name or "").strip().casefold()
        if not issue_type_name:
            return "subtask" if subtask else "unknown"
        if issue_type_name == "initiative":
            return "initiative"
        if issue_type_name == "epic":
            return "epic"
        if subtask or issue_type_name in {"sub-task", "subtask", "sub task"}:
            return "subtask"
        return "standard"

    def _extract_description_text(self, description: object) -> str:
        if description is None:
            return ""
        if isinstance(description, str):
            return description.strip()
        fragments: List[str] = []
        self._collect_text_fragments(description, fragments)
        return "\n".join(fragment for fragment in fragments if fragment).strip()

    def _collect_text_fragments(self, node: object, fragments: List[str]) -> None:
        if isinstance(node, str):
            text = node.strip()
            if text:
                fragments.append(text)
            return
        if isinstance(node, list):
            for item in node:
                self._collect_text_fragments(item, fragments)
            return
        if not isinstance(node, dict):
            return

        node_type = node.get("type")

        # --- ADF table → markdown table ---
        if node_type == "table":
            table_md = self._adf_table_to_markdown(node)
            if table_md:
                fragments.append(table_md)
            return

        text = str(node.get("text") or "").strip()
        if text:
            marks = node.get("marks") or []
            text = self._apply_marks(text, marks)
            fragments.append(text)
        self._collect_text_fragments(node.get("content"), fragments)

    @staticmethod
    def _apply_marks(text: str, marks: List[Dict]) -> str:
        for mark in marks:
            mark_type = mark.get("type")
            if mark_type == "strong":
                text = f"**{text}**"
            elif mark_type == "em":
                text = f"*{text}*"
            elif mark_type == "code":
                text = f"`{text}`"
            elif mark_type == "link":
                href = (mark.get("attrs") or {}).get("href", "")
                text = f"[{text}]({href})"
        return text

    def _adf_table_to_markdown(self, table_node: Dict) -> str:
        rows = table_node.get("content") or []
        if not rows:
            return ""
        md_rows: List[str] = []
        header_done = False
        for row in rows:
            if row.get("type") != "tableRow":
                continue
            cells = row.get("content") or []
            is_header = any(c.get("type") == "tableHeader" for c in cells)
            cell_texts: List[str] = []
            for cell in cells:
                cell_fragments: List[str] = []
                self._collect_text_fragments(cell.get("content"), cell_fragments)
                cell_texts.append(" ".join(cell_fragments))
            md_rows.append("| " + " | ".join(cell_texts) + " |")
            if is_header and not header_done:
                md_rows.append("| " + " | ".join("---" for _ in cell_texts) + " |")
                header_done = True
        return "\n".join(md_rows)