from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from tempoy_app.config import CustomFieldsConfig
from tempoy_app.services.copilot_audit_service import CopilotAuditService
from tempoy_app.services.copilot_allocation_service import CopilotAllocationService
from tempoy_app.services.copilot_policy_service import CopilotPolicyError, CopilotPolicyService
from tempoy_app.services.custom_field_schema import CustomFieldSchemaService
from tempoy_app.services.jira_analysis_service import JiraAnalysisService
from tempoy_app.services.jira_schema_service import JiraSchemaService

if TYPE_CHECKING:
    from tempoy_app.api.jira import JiraClient


class CopilotRoutes:
    def __init__(
        self,
        *,
        policy_service: CopilotPolicyService,
        audit_service: CopilotAuditService,
        jira_client_factory: Callable[[], JiraClient],
        allocation_service: CopilotAllocationService,
        tempo_client_factory: Optional[Callable] = None,
    ):
        self._policy_service = policy_service
        self._audit_service = audit_service
        self._jira_client_factory = jira_client_factory
        self._allocation_service = allocation_service
        self._tempo_client_factory = tempo_client_factory

    def get_allocation_draft(self, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        payload = self._allocation_service.get_allocation_draft()
        self._audit_service.log_event(
            operation="allocation.draft.get",
            success=True,
            category="read",
            detail={"row_count": len(payload.get("rows", []))},
        )
        return payload

    def get_issue_detail(self, issue_key: str, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        jira_client = self._jira_client_factory()
        issue = jira_client.get_issue(normalized_issue_key)
        project_key = str(((issue.get("fields") or {}).get("project") or {}).get("key") or "").upper()
        if not self._policy_service.is_project_allowed(project_key):
            raise CopilotPolicyError("Project is not allowed")
        payload = JiraAnalysisService(jira_base_url=jira_client.base_url).normalize_issue(issue)
        self._audit_service.log_event(
            operation="issues.get",
            success=True,
            category="read",
            detail={"issue_key": normalized_issue_key, "project_key": project_key},
        )
        return payload

    def search_issues(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        query = str(body.get("query") or "").strip()
        project_key = str(body.get("project_key") or "").strip().upper() or None
        issue_types = self._normalize_string_list(body.get("issue_types"))
        status_filters = self._normalize_string_list(body.get("status_filters"))
        assignee = str(body.get("assignee") or "").strip() or None
        labels = self._normalize_string_list(body.get("labels"))
        labels_match = str(body.get("labels_match") or "").strip().lower() or None
        priority = str(body.get("priority") or "").strip() or None
        updated_after = str(body.get("updated_after") or "").strip() or None
        created_after = str(body.get("created_after") or "").strip() or None
        parent_key = str(body.get("parent_key") or "").strip().upper() or None
        order_by = str(body.get("order_by") or "").strip().lower() or None
        raw_custom_field_filters = body.get("custom_fields") or {}
        max_results = self._coerce_page_size(body.get("page_size"))
        if project_key and not self._policy_service.is_project_allowed(project_key):
            raise CopilotPolicyError("Project is not allowed")

        custom_field_filters: list[dict] = []
        if isinstance(raw_custom_field_filters, dict) and raw_custom_field_filters:
            configured_fields = CustomFieldsConfig.load()
            field_lookup = {f["name"].casefold(): f for f in configured_fields}
            for name, value in raw_custom_field_filters.items():
                defn = field_lookup.get(str(name).strip().casefold())
                if defn is None:
                    raise ValueError(f"Unknown custom field: {name}")
                custom_field_filters.append({
                    "field_id": defn["field_id"],
                    "type": defn["type"],
                    "value": value,
                })

        jira_client = self._jira_client_factory()
        issues = jira_client.search_issues(
            query=query,
            project_key=project_key,
            issue_types=issue_types,
            status_filters=status_filters,
            assignee=assignee,
            labels=labels or None,
            labels_match=labels_match,
            priority=priority,
            updated_after=updated_after,
            created_after=created_after,
            parent_key=parent_key,
            order_by=order_by,
            custom_field_filters=custom_field_filters or None,
            max_results=max_results,
        )
        normalized = JiraAnalysisService(jira_base_url=jira_client.base_url).normalize_issues(
            issue
            for issue in issues
            if self._policy_service.is_project_allowed(str(((issue.get("fields") or {}).get("project") or {}).get("key") or ""))
            and (not project_key or str(((issue.get("fields") or {}).get("project") or {}).get("key") or "").upper() == project_key)
        )
        self._audit_service.log_event(
            operation="issues.search",
            success=True,
            category="read",
            detail={
                "query": query,
                "project_key": project_key or "",
                "result_count": len(normalized),
            },
        )
        return {
            "query": query,
            "project_key": project_key,
            "issue_types": issue_types,
            "status_filters": status_filters,
            "assignee": assignee,
            "labels": labels,
            "priority": priority,
            "updated_after": updated_after,
            "created_after": created_after,
            "parent_key": parent_key,
            "order_by": order_by,
            "results": normalized,
        }

    def get_issue_hierarchy(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        issue_keys = self._extract_issue_keys(body)
        include_parents = self._coerce_bool(body.get("include_parents"), default=True)
        include_linked_issues = self._coerce_bool(body.get("include_linked_issues"), default=True)
        include_children = self._coerce_bool(body.get("include_children"), default=False)
        depth = self._coerce_depth(body.get("depth"))

        jira_client = self._jira_client_factory()
        root_issues = jira_client.get_issues_by_keys(issue_keys)
        allowed_root_issues = [
            issue
            for issue in root_issues
            if self._policy_service.is_project_allowed(str(((issue.get("fields") or {}).get("project") or {}).get("key") or ""))
        ]
        related_keys: list[str] = []
        if include_parents or include_linked_issues:
            for issue in allowed_root_issues:
                normalized_issue = JiraAnalysisService(jira_base_url=jira_client.base_url).normalize_issue(issue)
                if include_parents:
                    parent = normalized_issue.get("parent") or {}
                    parent_key = str((parent or {}).get("key") or "").strip()
                    if parent_key:
                        related_keys.append(parent_key)
                if include_linked_issues:
                    for linked_issue in normalized_issue.get("linked_issues", []):
                        linked_key = str((linked_issue or {}).get("key") or "").strip()
                        if linked_key:
                            related_keys.append(linked_key)
        unique_related_keys = []
        seen = set()
        for related_key in related_keys:
            if related_key and related_key not in seen:
                seen.add(related_key)
                unique_related_keys.append(related_key)

        related_issues = jira_client.get_issues_by_keys(unique_related_keys) if unique_related_keys else []
        related_lookup = {
            str(issue.get("key") or ""): issue
            for issue in related_issues
            if self._policy_service.is_project_allowed(str(((issue.get("fields") or {}).get("project") or {}).get("key") or ""))
        }

        children_by_parent: dict[str, list[dict]] = {}
        if include_children:
            root_keys = [str(issue.get("key") or "") for issue in allowed_root_issues if issue.get("key")]
            if root_keys:
                raw_children = jira_client.search_children(root_keys)
                for child in raw_children:
                    child_project = str(((child.get("fields") or {}).get("project") or {}).get("key") or "")
                    if not self._policy_service.is_project_allowed(child_project):
                        continue
                    parent_info = (child.get("fields") or {}).get("parent") or {}
                    parent_key = str(parent_info.get("key") or "")
                    if parent_key:
                        children_by_parent.setdefault(parent_key, []).append(child)

        analysis_service = JiraAnalysisService(jira_base_url=jira_client.base_url)
        payload = analysis_service.build_hierarchy_payload(
            allowed_root_issues,
            related_issues_by_key=related_lookup,
            include_parents=include_parents,
            include_linked_issues=include_linked_issues,
            depth=depth,
            include_children=include_children,
            children_by_parent_key=children_by_parent,
        )
        self._audit_service.log_event(
            operation="issues.hierarchy",
            success=True,
            category="read",
            detail={"root_count": len(payload.get("root_issues", [])), "depth": depth},
        )
        return payload

    def get_projects(self, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        jira_client = self._jira_client_factory()
        projects = jira_client.get_projects()
        allowed_projects = [
            project for project in projects if self._policy_service.is_project_allowed(str(project.get("key") or ""))
        ]
        normalized = JiraSchemaService(jira_base_url=jira_client.base_url).normalize_projects(allowed_projects)
        self._audit_service.log_event(
            operation="projects.list",
            success=True,
            category="read",
            detail={"result_count": len(normalized)},
        )
        return {"projects": normalized}

    def get_project_issue_types(self, project_key: str, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        normalized_project_key = str(project_key or "").strip().upper()
        if not normalized_project_key:
            raise ValueError("Project key is required")
        if not self._policy_service.is_project_allowed(normalized_project_key):
            raise CopilotPolicyError("Project is not allowed")
        jira_client = self._jira_client_factory()
        issue_types = jira_client.get_project_issue_types(normalized_project_key)
        normalized = JiraSchemaService(jira_base_url=jira_client.base_url).normalize_issue_types(normalized_project_key, issue_types)
        self._audit_service.log_event(
            operation="projects.issue-types.get",
            success=True,
            category="read",
            detail={"project_key": normalized_project_key, "result_count": len(normalized)},
        )
        return {"project_key": normalized_project_key, "issue_types": normalized}

    def get_project_create_schema(self, project_key: str, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        normalized_project_key = str(project_key or "").strip().upper()
        if not normalized_project_key:
            raise ValueError("Project key is required")
        if not self._policy_service.is_project_allowed(normalized_project_key):
            raise CopilotPolicyError("Project is not allowed")
        jira_client = self._jira_client_factory()
        create_schema = jira_client.get_create_schema(normalized_project_key)
        normalized = JiraSchemaService(jira_base_url=jira_client.base_url).normalize_create_schema(
            normalized_project_key,
            create_schema,
            issue_type_write_allowlist=self._policy_service.is_issue_type_allowed,
        )
        self._audit_service.log_event(
            operation="projects.create-schema.get",
            success=True,
            category="read",
            detail={"project_key": normalized_project_key, "result_count": len(normalized)},
        )
        return {"project_key": normalized_project_key, "issue_types": normalized}

    def add_allocation_issue(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_refine_access(token)
        issue_key = str(body.get("issue_key") or "").strip().upper()
        summary = str(body.get("summary") or "").strip() or None
        payload = self._allocation_service.add_issue(issue_key, summary=summary)
        self._audit_service.log_event(
            operation="allocation.add",
            success=True,
            category="write",
            detail={"issue_key": issue_key},
        )
        return payload

    def remove_allocation_issue(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_refine_access(token)
        issue_key = str(body.get("issue_key") or "").strip().upper()
        payload = self._allocation_service.remove_issue(issue_key)
        self._audit_service.log_event(
            operation="allocation.remove",
            success=True,
            category="write",
            detail={"issue_key": issue_key},
        )
        return payload

    def set_allocation_units(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_refine_access(token)
        issue_key = str(body.get("issue_key") or "").strip().upper()
        if "allocation_units" not in body:
            raise ValueError("Allocation units are required")
        try:
            allocation_units = int(body.get("allocation_units"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Allocation units must be an integer") from exc
        payload = self._allocation_service.set_row_units(issue_key, allocation_units)
        self._audit_service.log_event(
            operation="allocation.set-units",
            success=True,
            category="write",
            detail={"issue_key": issue_key, "allocation_units": allocation_units},
        )
        return payload

    def set_allocation_lock(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_refine_access(token)
        issue_key = str(body.get("issue_key") or "").strip().upper()
        if "locked" not in body:
            raise ValueError("Locked flag is required")
        payload = self._allocation_service.set_row_lock(issue_key, bool(body.get("locked")))
        self._audit_service.log_event(
            operation="allocation.set-lock",
            success=True,
            category="write",
            detail={"issue_key": issue_key, "locked": bool(body.get("locked"))},
        )
        return payload

    def equalize_allocation(self, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_refine_access(token)
        payload = self._allocation_service.equalize()
        self._audit_service.log_event(
            operation="allocation.equalize",
            success=True,
            category="write",
            detail={},
        )
        return payload

    def reset_allocation(self, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_refine_access(token)
        payload = self._allocation_service.reset()
        self._audit_service.log_event(
            operation="allocation.reset",
            success=True,
            category="write",
            detail={},
        )
        return payload

    def get_issue_transitions(self, issue_key: str, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        jira_client = self._jira_client_factory()
        issue = jira_client.get_issue(normalized_issue_key)
        project_key = str(((issue.get("fields") or {}).get("project") or {}).get("key") or "").upper()
        if not self._policy_service.is_project_allowed(project_key):
            raise CopilotPolicyError("Project is not allowed")
        raw_transitions = jira_client.get_transitions(normalized_issue_key)
        current_status = str(((issue.get("fields") or {}).get("status") or {}).get("name") or "")
        transitions = [
            {
                "id": str(t.get("id") or ""),
                "name": str(t.get("name") or ""),
                "to_status": str(((t.get("to") or {}).get("name") or "")),
            }
            for t in raw_transitions
            if isinstance(t, dict) and t.get("id")
        ]
        self._audit_service.log_event(
            operation="issues.transitions.get",
            success=True,
            category="read",
            detail={"issue_key": normalized_issue_key, "transition_count": len(transitions)},
        )
        return {
            "issue_key": normalized_issue_key,
            "current_status": current_status,
            "transitions": transitions,
        }

    def get_issue_dev_info(self, issue_key: str, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        jira_client = self._jira_client_factory()
        issue = jira_client.get_issue(normalized_issue_key)
        project_key = str(((issue.get("fields") or {}).get("project") or {}).get("key") or "").upper()
        if not self._policy_service.is_project_allowed(project_key):
            raise CopilotPolicyError("Project is not allowed")
        issue_id = str(issue.get("id") or "")
        if not issue_id:
            raise RuntimeError("Could not determine issue ID")
        raw = jira_client.get_dev_info(issue_id)
        branches = [
            {"name": str(b.get("name") or ""), "url": str(b.get("url") or "")}
            for b in raw.get("branches", []) if b.get("name")
        ]
        commits = [
            {
                "id": str(c.get("id") or ""),
                "message": str(c.get("message") or ""),
                "author": str((c.get("author") or {}).get("name") or ""),
                "url": str(c.get("url") or ""),
            }
            for c in raw.get("commits", []) if c.get("id")
        ]
        pull_requests = [
            {
                "id": str(pr.get("id") or ""),
                "name": str(pr.get("name") or ""),
                "status": str(pr.get("status") or ""),
                "url": str(pr.get("url") or ""),
                "author": str((pr.get("author") or {}).get("name") or ""),
            }
            for pr in raw.get("pullRequests", []) if pr.get("id")
        ]
        self._audit_service.log_event(
            operation="issues.dev-info.get",
            success=True,
            category="read",
            detail={
                "issue_key": normalized_issue_key,
                "branches": len(branches),
                "commits": len(commits),
                "pull_requests": len(pull_requests),
            },
        )
        return {
            "issue_key": normalized_issue_key,
            "branches": branches,
            "commits": commits,
            "pull_requests": pull_requests,
        }

    def transition_issue(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        normalized_issue_key = str(body.get("issue_key") or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        transition_name = str(body.get("transition_name") or "").strip()
        if not transition_name:
            raise ValueError("Transition name is required")
        apply = self._coerce_bool(body.get("apply"), default=False)
        confirm = self._coerce_bool(body.get("confirm"), default=False)

        jira_client = self._jira_client_factory()
        issue = jira_client.get_issue(normalized_issue_key)
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        project_key = str((fields.get("project") or {}).get("key") or "").strip().upper()
        if not self._policy_service.is_project_allowed(project_key):
            raise CopilotPolicyError("Project is not allowed")
        issue_type = str((fields.get("issuetype") or {}).get("name") or "").strip()
        config = self._policy_service.require_refine_access(token, issue_type_name=issue_type or None)

        current_status = str((fields.get("status") or {}).get("name") or "")
        raw_transitions = jira_client.get_transitions(normalized_issue_key)
        matched_transition = None
        for t in raw_transitions:
            if not isinstance(t, dict):
                continue
            t_name = str(t.get("name") or "")
            to_status = str(((t.get("to") or {}).get("name") or ""))
            if t_name.casefold() == transition_name.casefold() or to_status.casefold() == transition_name.casefold():
                matched_transition = t
                break
        if matched_transition is None:
            available = [str(t.get("name") or "") for t in raw_transitions if isinstance(t, dict)]
            raise ValueError(
                f"No transition matching '{transition_name}' is available. "
                f"Available transitions: {', '.join(available) if available else 'none'}"
            )

        to_status = str(((matched_transition.get("to") or {}).get("name") or ""))
        preview = {
            "operation": "transition_issue",
            "issue_key": normalized_issue_key,
            "project_key": project_key,
            "issue_type": issue_type,
            "current_status": current_status,
            "transition_name": str(matched_transition.get("name") or ""),
            "transition_id": str(matched_transition.get("id") or ""),
            "to_status": to_status,
            "requires_confirmation": bool(config.copilot_require_write_confirmation),
        }
        if not apply or (config.copilot_require_write_confirmation and not confirm):
            self._audit_service.log_event(
                operation="issues.transition.preview",
                success=True,
                category="write-preview",
                detail={"issue_key": normalized_issue_key, "to_status": to_status},
            )
            return {"applied": False, "preview": preview}

        jira_client.transition_issue(normalized_issue_key, str(matched_transition.get("id") or ""))
        updated_issue = JiraAnalysisService(jira_base_url=jira_client.base_url).normalize_issue(jira_client.get_issue(normalized_issue_key))
        self._audit_service.log_event(
            operation="issues.transition.apply",
            success=True,
            category="write",
            detail={"issue_key": normalized_issue_key, "from_status": current_status, "to_status": to_status},
        )
        return {"applied": True, "preview": preview, "issue": updated_issue}

    def create_issue(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        issue_type = str(body.get("issue_type") or "Task").strip() or "Task"
        if issue_type.casefold() != "task":
            raise ValueError("Only Task creation is supported")
        config = self._policy_service.require_create_access(token, issue_type_name="Task")
        project_key = str(body.get("project_key") or "").strip().upper()
        if not project_key:
            raise ValueError("Project key is required")
        if not self._policy_service.is_project_allowed(project_key):
            raise CopilotPolicyError("Project is not allowed")
        summary = str(body.get("summary") or "").strip()
        if not summary:
            raise ValueError("Summary is required")
        description_text = str(body.get("description_text") or "").strip()
        labels = self._normalize_string_list(body.get("labels"))
        priority = str(body.get("priority") or "").strip()
        apply = self._coerce_bool(body.get("apply"), default=False)
        confirm = self._coerce_bool(body.get("confirm"), default=False)

        jira_client = self._jira_client_factory()
        create_schemas = jira_client.get_create_schema(project_key)
        task_schema = JiraSchemaService.find_issue_type_schema(create_schemas, "Task")
        if task_schema is None:
            raise ValueError("Task creation is not available for this project")
        validated_fields, warnings = self._build_task_create_fields(
            project_key=project_key,
            schema=task_schema,
            summary=summary,
            description_text=description_text,
            labels=labels,
            priority=priority,
        )
        preview = {
            "operation": "create_issue",
            "project_key": project_key,
            "issue_type": "Task",
            "validated_fields": validated_fields,
            "warnings": warnings,
            "requires_confirmation": bool(config.copilot_require_write_confirmation),
        }
        if not apply or (config.copilot_require_write_confirmation and not confirm):
            self._audit_service.log_event(
                operation="issues.create.preview",
                success=True,
                category="write-preview",
                detail={"project_key": project_key, "issue_type": "Task"},
            )
            return {"applied": False, "preview": preview}

        created = jira_client.create_issue(validated_fields)
        created_key = str(created.get("key") or "").strip()
        created_issue: Dict[str, object]
        if created_key:
            try:
                created_issue = JiraAnalysisService(jira_base_url=jira_client.base_url).normalize_issue(jira_client.get_issue(created_key))
            except Exception:
                created_issue = {"key": created_key, "id": str(created.get("id") or "")}
        else:
            created_issue = {"key": "", "id": str(created.get("id") or "")}
        self._audit_service.log_event(
            operation="issues.create.apply",
            success=True,
            category="write",
            detail={"project_key": project_key, "issue_type": "Task", "issue_key": created_issue.get("key", "")},
        )
        return {"applied": True, "preview": preview, "issue": created_issue}

    def update_issue(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        normalized_issue_key = str(body.get("issue_key") or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        apply = self._coerce_bool(body.get("apply"), default=False)
        confirm = self._coerce_bool(body.get("confirm"), default=False)

        jira_client = self._jira_client_factory()
        issue = jira_client.get_issue(normalized_issue_key)
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        project_key = str((fields.get("project") or {}).get("key") or "").strip().upper()
        if not self._policy_service.is_project_allowed(project_key):
            raise CopilotPolicyError("Project is not allowed")
        issue_type = str((fields.get("issuetype") or {}).get("name") or "").strip()
        config = self._policy_service.require_refine_access(token, issue_type_name=issue_type or None)
        edit_schema = jira_client.get_edit_schema(normalized_issue_key)
        validated_fields, warnings, changes = self._build_issue_update_fields(body=body, issue=issue, edit_schema=edit_schema)
        preview = {
            "operation": "update_issue",
            "issue_key": normalized_issue_key,
            "project_key": project_key,
            "issue_type": issue_type,
            "validated_fields": validated_fields,
            "changes": changes,
            "warnings": warnings,
            "requires_confirmation": bool(config.copilot_require_write_confirmation),
        }
        if not apply or (config.copilot_require_write_confirmation and not confirm):
            self._audit_service.log_event(
                operation="issues.update.preview",
                success=True,
                category="write-preview",
                detail={"issue_key": normalized_issue_key, "project_key": project_key, "field_count": len(validated_fields)},
            )
            return {"applied": False, "preview": preview}

        jira_client.update_issue(normalized_issue_key, validated_fields)
        updated_issue = JiraAnalysisService(jira_base_url=jira_client.base_url).normalize_issue(jira_client.get_issue(normalized_issue_key))
        self._audit_service.log_event(
            operation="issues.update.apply",
            success=True,
            category="write",
            detail={"issue_key": normalized_issue_key, "project_key": project_key, "field_count": len(validated_fields)},
        )
        return {"applied": True, "preview": preview, "issue": updated_issue}

    @staticmethod
    def _normalize_string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item or "").strip() for item in value if str(item or "").strip()]

    @staticmethod
    def _coerce_page_size(value: object) -> int:
        try:
            return max(1, min(100, int(value)))
        except (TypeError, ValueError):
            return 25

    @staticmethod
    def _extract_issue_keys(body: Dict[str, Any]) -> list[str]:
        raw_issue_key = str(body.get("issue_key") or "").strip().upper()
        raw_issue_keys = body.get("issue_keys")
        issue_keys: list[str] = []
        if raw_issue_key:
            issue_keys.append(raw_issue_key)
        if isinstance(raw_issue_keys, list):
            for item in raw_issue_keys:
                normalized = str(item or "").strip().upper()
                if normalized and normalized not in issue_keys:
                    issue_keys.append(normalized)
        if not issue_keys:
            raise ValueError("At least one issue key is required")
        return issue_keys

    @staticmethod
    def _coerce_bool(value: object, *, default: bool) -> bool:
        if value is None:
            return default
        return bool(value)

    @staticmethod
    def _coerce_depth(value: object) -> int:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _build_task_create_fields(
        *,
        project_key: str,
        schema: Dict[str, Any],
        summary: str,
        description_text: str,
        labels: list[str],
        priority: str,
    ) -> tuple[Dict[str, object], list[str]]:
        fields_schema = schema.get("fields") if isinstance(schema.get("fields"), dict) else {}
        issue_type_id = str(schema.get("issueTypeId") or schema.get("id") or "").strip()
        unsupported_required_fields = []
        for field_id, field_value in fields_schema.items():
            if not isinstance(field_value, dict):
                continue
            if not field_value.get("required"):
                continue
            if field_id in {"summary", "description", "labels", "priority", "project", "issuetype"}:
                continue
            unsupported_required_fields.append(str(field_value.get("name") or field_id))
        if unsupported_required_fields:
            raise ValueError(
                "Task creation for this project requires unsupported fields: " + ", ".join(sorted(unsupported_required_fields))
            )

        fields: Dict[str, object] = {
            "project": {"key": project_key},
            "issuetype": {"id": issue_type_id} if issue_type_id else {"name": "Task"},
            "summary": summary,
        }
        warnings: list[str] = []
        if description_text:
            if "description" in fields_schema or not fields_schema:
                fields["description"] = CopilotRoutes._to_adf_document(description_text)
            else:
                warnings.append("Description is not available in this project's Task create schema")
        if labels:
            if "labels" in fields_schema:
                fields["labels"] = labels
            else:
                warnings.append("Labels are not available in this project's Task create schema")
        if priority:
            if "priority" not in fields_schema:
                warnings.append("Priority is not available in this project's Task create schema")
            else:
                priority_field = fields_schema.get("priority") or {}
                allowed_values = priority_field.get("allowedValues") if isinstance(priority_field.get("allowedValues"), list) else []
                allowed_names = {
                    str(item.get("name") or item.get("value") or "").strip().casefold()
                    for item in allowed_values
                    if isinstance(item, dict)
                }
                if allowed_names and priority.casefold() not in allowed_names:
                    raise ValueError("Priority is not valid for this project's Task create schema")
                fields["priority"] = {"name": priority}
        return fields, warnings

    @staticmethod
    def _build_issue_update_fields(
        *,
        body: Dict[str, Any],
        issue: Dict[str, Any],
        edit_schema: Dict[str, Any],
    ) -> tuple[Dict[str, object], list[str], Dict[str, Dict[str, object]]]:
        allowed_input_keys = {
            "issue_key",
            "summary",
            "description_text",
            "labels",
            "priority",
            "parent_key",
            "acceptance_criteria_text",
            "assignee_account_id",
            "apply",
            "confirm",
        }
        unexpected_keys = sorted(key for key in body.keys() if key not in allowed_input_keys)
        if unexpected_keys:
            raise ValueError("Unsupported update fields requested: " + ", ".join(unexpected_keys))

        editable_fields = edit_schema.get("fields") if isinstance(edit_schema.get("fields"), dict) else {}
        current_fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        normalized_issue = JiraAnalysisService(jira_base_url="").normalize_issue(issue)
        changes: Dict[str, Dict[str, object]] = {}
        fields: Dict[str, object] = {}
        warnings: list[str] = []
        requested_change = False

        if "summary" in body:
            requested_change = True
            summary = str(body.get("summary") or "").strip()
            if not summary:
                raise ValueError("Summary cannot be empty")
            if "summary" in editable_fields or not editable_fields:
                fields["summary"] = summary
                changes["summary"] = {"from": str(current_fields.get("summary") or ""), "to": summary}
            else:
                warnings.append("Summary is not editable for this issue")

        if "description_text" in body:
            requested_change = True
            description_text = str(body.get("description_text") or "")
            if "description" in editable_fields or not editable_fields:
                fields["description"] = CopilotRoutes._to_adf_document(description_text)
                changes["description_text"] = {"from": str(normalized_issue.get("description_text") or ""), "to": description_text.strip()}
            else:
                warnings.append("Description is not editable for this issue")

        if "labels" in body:
            requested_change = True
            raw_labels = body.get("labels")
            if not isinstance(raw_labels, list):
                raise ValueError("Labels must be provided as a list")
            labels = CopilotRoutes._normalize_string_list(raw_labels)
            if "labels" in editable_fields or not editable_fields:
                fields["labels"] = labels
                changes["labels"] = {"from": list(current_fields.get("labels") or []), "to": labels}
            else:
                warnings.append("Labels are not editable for this issue")

        if "priority" in body:
            requested_change = True
            priority = str(body.get("priority") or "").strip()
            if not priority:
                raise ValueError("Priority cannot be empty")
            if "priority" not in editable_fields and editable_fields:
                warnings.append("Priority is not editable for this issue")
            else:
                priority_field = editable_fields.get("priority") if isinstance(editable_fields.get("priority"), dict) else {}
                allowed_values = priority_field.get("allowedValues") if isinstance(priority_field.get("allowedValues"), list) else []
                allowed_names = {
                    str(item.get("name") or item.get("value") or "").strip().casefold()
                    for item in allowed_values
                    if isinstance(item, dict)
                }
                if allowed_names and priority.casefold() not in allowed_names:
                    raise ValueError("Priority is not valid for this issue")
                fields["priority"] = {"name": priority}
                changes["priority"] = {
                    "from": str(((current_fields.get("priority") or {}).get("name") or "")),
                    "to": priority,
                }

        if "parent_key" in body:
            requested_change = True
            parent_key = str(body.get("parent_key") or "").strip().upper()
            if "parent" in editable_fields or not editable_fields:
                fields["parent"] = None if not parent_key else {"key": parent_key}
                changes["parent_key"] = {
                    "from": str(((normalized_issue.get("parent") or {}).get("key") or "")),
                    "to": parent_key,
                }
            else:
                warnings.append("Parent is not editable for this issue")

        if "acceptance_criteria_text" in body:
            requested_change = True
            acceptance_text = str(body.get("acceptance_criteria_text") or "")
            acceptance_field_id = CopilotRoutes._find_named_field_id(editable_fields, ["Acceptance Criteria"])
            if acceptance_field_id is None:
                warnings.append("Acceptance criteria is not editable for this issue")
            else:
                acceptance_schema = editable_fields.get(acceptance_field_id) if isinstance(editable_fields.get(acceptance_field_id), dict) else {}
                schema_type = str(((acceptance_schema.get("schema") or {}).get("type") or "")).strip().casefold()
                if schema_type not in {"", "string"}:
                    warnings.append("Acceptance criteria field type is not supported yet")
                else:
                    fields[acceptance_field_id] = acceptance_text.strip()
                    changes["acceptance_criteria_text"] = {
                        "from": str(current_fields.get(acceptance_field_id) or ""),
                        "to": acceptance_text.strip(),
                    }

        if "assignee_account_id" in body:
            requested_change = True
            assignee_account_id = str(body.get("assignee_account_id") or "").strip()
            if "assignee" in editable_fields or not editable_fields:
                fields["assignee"] = None if not assignee_account_id else {"accountId": assignee_account_id}
                current_assignee = current_fields.get("assignee") or {}
                changes["assignee_account_id"] = {
                    "from": str((current_assignee.get("accountId") or "") if isinstance(current_assignee, dict) else ""),
                    "to": assignee_account_id,
                }
            else:
                warnings.append("Assignee is not editable for this issue")

        if not requested_change:
            raise ValueError("At least one editable field change is required")
        if not fields:
            raise ValueError("None of the requested fields are editable for this issue")
        return fields, warnings, changes

    @staticmethod
    def _find_named_field_id(fields: Dict[str, Any], candidate_names: list[str]) -> Optional[str]:
        wanted_names = {str(name or "").strip().casefold() for name in candidate_names if str(name or "").strip()}
        for field_id, metadata in fields.items():
            if not isinstance(metadata, dict):
                continue
            field_name = str(metadata.get("name") or field_id or "").strip().casefold()
            if field_name in wanted_names:
                return str(field_id)
        return None

    @staticmethod
    def _to_adf_document(text: str) -> Dict[str, object]:
        paragraphs = [line.strip() for line in str(text or "").splitlines()]
        content = []
        for paragraph in paragraphs:
            if not paragraph:
                continue
            content.append({"type": "paragraph", "content": [{"type": "text", "text": paragraph}]})
        if not content:
            content = [{"type": "paragraph", "content": []}]
        return {"type": "doc", "version": 1, "content": content}

    def discover_custom_fields(self, *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        raw_fields = CustomFieldsConfig.load()
        definitions = CustomFieldSchemaService.load_definitions(raw_fields)
        payload: List[Dict[str, object]] = [
            {
                "name": d.name,
                "field_id": d.field_id,
                "type": d.type,
                "constraints": d.constraints_dict(),
            }
            for d in definitions
        ]
        self._audit_service.log_event(
            operation="custom-fields.discover",
            success=True,
            category="read",
            detail={"field_count": len(payload)},
        )
        return {"custom_fields": payload}

    def update_custom_fields(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        normalized_issue_key = str(body.get("issue_key") or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        fields_input = body.get("fields")
        if not isinstance(fields_input, dict) or not fields_input:
            raise ValueError("Fields object is required and must be non-empty")
        apply = self._coerce_bool(body.get("apply"), default=False)
        confirm = self._coerce_bool(body.get("confirm"), default=False)

        jira_client = self._jira_client_factory()
        issue = jira_client.get_issue(normalized_issue_key)
        current_fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        project_key = str((current_fields.get("project") or {}).get("key") or "").strip().upper()
        if not self._policy_service.is_project_allowed(project_key):
            raise CopilotPolicyError("Project is not allowed")
        issue_type = str((current_fields.get("issuetype") or {}).get("name") or "").strip()
        config = self._policy_service.require_refine_access(token, issue_type_name=issue_type or None)

        raw_custom_fields = CustomFieldsConfig.load()
        definitions = CustomFieldSchemaService.load_definitions(raw_custom_fields)
        defs_by_name = {d.name.casefold(): d for d in definitions}

        jira_fields: Dict[str, Any] = {}
        changes: Dict[str, Dict[str, object]] = {}
        for field_name, field_value in fields_input.items():
            name_key = str(field_name).strip().casefold()
            definition = defs_by_name.get(name_key)
            if definition is None:
                raise ValueError(
                    f"Unknown custom field '{field_name}'. "
                    f"Configured fields: {', '.join(d.name for d in definitions) or 'none'}"
                )
            validated = CustomFieldSchemaService.validate_value(definition, field_value)
            payload = CustomFieldSchemaService.build_jira_field_payload(definition, validated)
            jira_fields.update(payload)

            current_value = current_fields.get(definition.field_id)
            if definition.type == "duration":
                tt = current_fields.get("timetracking") or {}
                current_value = tt.get("originalEstimate") if isinstance(tt, dict) else None
            elif definition.type == "option":
                current_value = (current_value or {}).get("value") if isinstance(current_value, dict) else current_value
            elif definition.type == "multi_option":
                if isinstance(current_value, list):
                    current_value = [item.get("value") if isinstance(item, dict) else item for item in current_value]
            changes[definition.name] = {"from": current_value, "to": validated}

        preview: Dict[str, object] = {
            "operation": "update_custom_fields",
            "issue_key": normalized_issue_key,
            "project_key": project_key,
            "issue_type": issue_type,
            "fields": changes,
            "requires_confirmation": bool(config.copilot_require_write_confirmation),
        }
        if not apply or (config.copilot_require_write_confirmation and not confirm):
            self._audit_service.log_event(
                operation="custom-fields.update.preview",
                success=True,
                category="write-preview",
                detail={"issue_key": normalized_issue_key, "field_count": len(jira_fields)},
            )
            return {"applied": False, "preview": preview}

        jira_client.update_issue(normalized_issue_key, jira_fields)
        updated_issue = JiraAnalysisService(jira_base_url=jira_client.base_url).normalize_issue(
            jira_client.get_issue(normalized_issue_key)
        )
        self._audit_service.log_event(
            operation="custom-fields.update.apply",
            success=True,
            category="write",
            detail={"issue_key": normalized_issue_key, "project_key": project_key, "field_count": len(jira_fields)},
        )
        return {"applied": True, "preview": preview, "issue": updated_issue}

    def search_users(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        query = str(body.get("query") or "").strip()
        if not query:
            raise ValueError("Query is required")
        max_results = int(body.get("max_results", 10))
        jira_client = self._jira_client_factory()
        users = jira_client.search_users(query, max_results=max_results)
        self._audit_service.log_event(
            operation="users.search",
            success=True,
            category="read",
            detail={"query": query, "result_count": len(users)},
        )
        return {"query": query, "results": users}

    def get_recent_worklogs(self, body: Dict[str, Any], *, token: Optional[str]) -> Dict[str, object]:
        self._policy_service.require_session_token(token)
        days_back = max(1, min(int(body.get("days_back", 14)), 90))
        if self._tempo_client_factory is None:
            raise RuntimeError("Tempo is not configured")
        jira_client = self._jira_client_factory()
        myself = jira_client.get_myself()
        account_id = myself.get("accountId") or ""
        if not account_id:
            raise RuntimeError("Could not determine current user account ID")
        tempo_client = self._tempo_client_factory()
        raw_worklogs = tempo_client.get_recent_worked_issues(account_id=account_id, days_back=days_back)
        by_issue: Dict[str, Dict[str, object]] = {}
        for entry in raw_worklogs:
            issue = entry.get("issue") or {}
            key = str(issue.get("key") or "").strip()
            if not key:
                continue
            bucket = by_issue.setdefault(key, {"issue_key": key, "total_seconds": 0, "worklog_count": 0, "last_logged_date": ""})
            bucket["total_seconds"] = int(bucket["total_seconds"]) + int(entry.get("timeSpentSeconds", 0))
            bucket["worklog_count"] = int(bucket["worklog_count"]) + 1
            start_date = str(entry.get("startDate") or "")
            if start_date > str(bucket["last_logged_date"]):
                bucket["last_logged_date"] = start_date
        results = sorted(by_issue.values(), key=lambda r: str(r.get("last_logged_date", "")), reverse=True)
        self._audit_service.log_event(
            operation="worklogs.recent",
            success=True,
            category="read",
            detail={"days_back": days_back, "issue_count": len(results)},
        )
        return {"days_back": days_back, "issues": results}