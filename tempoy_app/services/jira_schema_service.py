from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from tempoy_app.services.jira_analysis_service import JiraAnalysisService


class JiraSchemaService:
    def __init__(self, *, jira_base_url: str):
        self._jira_base_url = str(jira_base_url or "").rstrip("/")

    def normalize_projects(self, projects: Iterable[Dict]) -> List[Dict[str, object]]:
        normalized: List[Dict[str, object]] = []
        for project in projects:
            if not isinstance(project, dict):
                continue
            key = str(project.get("key") or "").strip().upper()
            if not key:
                continue
            normalized.append(
                {
                    "id": str(project.get("id") or ""),
                    "key": key,
                    "name": str(project.get("name") or ""),
                    "project_type": str(project.get("projectTypeKey") or ""),
                    "simplified": bool(project.get("simplified", False)),
                    "style": str(project.get("style") or ""),
                    "raw_url": f"{self._jira_base_url}/jira/software/projects/{key}/summary" if self._jira_base_url else "",
                }
            )
        return sorted(normalized, key=lambda item: (str(item.get("name") or "").casefold(), str(item.get("key") or "")))

    def normalize_issue_types(self, project_key: str, issue_types: Iterable[Dict]) -> List[Dict[str, object]]:
        normalized: List[Dict[str, object]] = []
        normalized_project_key = str(project_key or "").strip().upper()
        for issue_type in issue_types:
            if not isinstance(issue_type, dict):
                continue
            name = str(issue_type.get("name") or "").strip()
            if not name:
                continue
            normalized.append(
                {
                    "id": str(issue_type.get("id") or ""),
                    "name": name,
                    "description": str(issue_type.get("description") or ""),
                    "subtask": bool(issue_type.get("subtask", False)),
                    "hierarchy_level": JiraAnalysisService.infer_hierarchy_level(name=name, subtask=bool(issue_type.get("subtask", False))),
                    "project_key": normalized_project_key,
                }
            )
        return sorted(normalized, key=lambda item: str(item.get("name") or "").casefold())

    def normalize_create_schema(
        self,
        project_key: str,
        create_schemas: Iterable[Dict],
        *,
        issue_type_write_allowlist: Optional[callable] = None,
    ) -> List[Dict[str, object]]:
        normalized_project_key = str(project_key or "").strip().upper()
        normalized: List[Dict[str, object]] = []
        for schema in create_schemas:
            if not isinstance(schema, dict):
                continue
            issue_type_id = str(schema.get("issueTypeId") or schema.get("id") or "").strip()
            issue_type_name = str(schema.get("name") or "").strip()
            fields = schema.get("fields") if isinstance(schema.get("fields"), dict) else {}
            if not issue_type_name:
                continue
            normalized.append(
                {
                    "project_key": normalized_project_key,
                    "issue_type_id": issue_type_id,
                    "issue_type": issue_type_name,
                    "hierarchy_level": JiraAnalysisService.infer_hierarchy_level(name=issue_type_name),
                    "write_allowed": True if issue_type_write_allowlist is None else bool(issue_type_write_allowlist(issue_type_name)),
                    "fields": self._normalize_fields(fields),
                }
            )
        return sorted(normalized, key=lambda item: str(item.get("issue_type") or "").casefold())

    @staticmethod
    def find_issue_type_schema(create_schemas: Iterable[Dict], issue_type_name: str) -> Optional[Dict]:
        normalized_name = str(issue_type_name or "").strip().casefold()
        for schema in create_schemas:
            if not isinstance(schema, dict):
                continue
            if str(schema.get("name") or "").strip().casefold() == normalized_name:
                return schema
        return None

    def _normalize_fields(self, fields: Dict[str, Dict]) -> List[Dict[str, object]]:
        normalized: List[Dict[str, object]] = []
        for field_id, field_value in fields.items():
            if not isinstance(field_value, dict):
                continue
            name = str(field_value.get("name") or field_id or "").strip()
            schema_info = field_value.get("schema") if isinstance(field_value.get("schema"), dict) else {}
            normalized.append(
                {
                    "field_id": str(field_id),
                    "name": name,
                    "required": bool(field_value.get("required", False)),
                    "schema_type": str(schema_info.get("type") or ""),
                    "schema_items": str(schema_info.get("items") or ""),
                    "custom": str(schema_info.get("custom") or ""),
                    "has_default_value": field_value.get("hasDefaultValue") is True,
                    "allowed_values": self._normalize_allowed_values(field_value.get("allowedValues")),
                    "operations": self._normalize_operations(field_value.get("operations")),
                }
            )
        return sorted(normalized, key=lambda item: (not bool(item.get("required")), str(item.get("name") or "").casefold()))

    @staticmethod
    def _normalize_allowed_values(value: object) -> List[Dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: List[Dict[str, str]] = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(
                    {
                        "id": str(item.get("id") or ""),
                        "value": str(item.get("value") or item.get("name") or item.get("key") or ""),
                    }
                )
            else:
                text = str(item or "").strip()
                if text:
                    normalized.append({"id": "", "value": text})
        return normalized

    @staticmethod
    def _normalize_operations(value: object) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item or "").strip()]