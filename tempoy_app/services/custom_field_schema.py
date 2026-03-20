from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CustomFieldDef:
    name: str
    field_id: str
    type: str
    min: Optional[float] = None
    max: Optional[float] = None
    max_length: Optional[int] = None
    allowed_values: Optional[List[str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "field_id": self.field_id,
            "type": self.type,
        }
        if self.type == "number":
            if self.min is not None:
                result["min"] = self.min
            if self.max is not None:
                result["max"] = self.max
        elif self.type in ("option", "multi_option"):
            if self.allowed_values:
                result["allowed_values"] = list(self.allowed_values)
        elif self.type == "string":
            if self.max_length is not None:
                result["max_length"] = self.max_length
        return result

    def constraints_dict(self) -> Dict[str, Any]:
        constraints: Dict[str, Any] = {}
        if self.type == "number":
            if self.min is not None:
                constraints["min"] = self.min
            if self.max is not None:
                constraints["max"] = self.max
        elif self.type in ("option", "multi_option"):
            if self.allowed_values:
                constraints["allowed_values"] = list(self.allowed_values)
        elif self.type == "string":
            if self.max_length is not None:
                constraints["max_length"] = self.max_length
        return constraints

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> CustomFieldDef:
        return CustomFieldDef(
            name=str(data.get("name") or ""),
            field_id=str(data.get("field_id") or ""),
            type=str(data.get("type") or ""),
            min=data.get("min"),
            max=data.get("max"),
            max_length=data.get("max_length"),
            allowed_values=data.get("allowed_values") or [],
        )


_DURATION_PATTERN = re.compile(r"^(\d+[wdhm]\s*)+$", re.IGNORECASE)


class CustomFieldSchemaService:

    @staticmethod
    def load_definitions(raw_list: List[Dict]) -> List[CustomFieldDef]:
        return [CustomFieldDef.from_dict(entry) for entry in raw_list if isinstance(entry, dict)]

    @staticmethod
    def validate_value(definition: CustomFieldDef, value: Any) -> Any:
        field_type = definition.type

        if field_type == "string":
            coerced = str(value or "")
            if definition.max_length is not None and len(coerced) > definition.max_length:
                raise ValueError(
                    f"Value for '{definition.name}' exceeds max length "
                    f"({len(coerced)} > {definition.max_length})"
                )
            return coerced

        if field_type == "number":
            try:
                coerced = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Value for '{definition.name}' must be a number") from exc
            if coerced != coerced:  # NaN check
                raise ValueError(f"Value for '{definition.name}' must be a number")
            if definition.min is not None and coerced < definition.min:
                raise ValueError(
                    f"Value for '{definition.name}' is below minimum ({coerced} < {definition.min})"
                )
            if definition.max is not None and coerced > definition.max:
                raise ValueError(
                    f"Value for '{definition.name}' exceeds maximum ({coerced} > {definition.max})"
                )
            if coerced == int(coerced):
                return int(coerced)
            return coerced

        if field_type == "option":
            coerced = str(value or "").strip()
            if not coerced:
                raise ValueError(f"Value for '{definition.name}' cannot be empty")
            if definition.allowed_values:
                allowed_lower = {v.casefold() for v in definition.allowed_values}
                if coerced.casefold() not in allowed_lower:
                    raise ValueError(
                        f"Value '{coerced}' for '{definition.name}' is not in allowed values: "
                        f"{', '.join(definition.allowed_values)}"
                    )
            return coerced

        if field_type == "multi_option":
            if not isinstance(value, list):
                raise ValueError(f"Value for '{definition.name}' must be a list")
            coerced_list = [str(v or "").strip() for v in value]
            coerced_list = [v for v in coerced_list if v]
            if not coerced_list:
                raise ValueError(f"Value for '{definition.name}' must contain at least one item")
            if definition.allowed_values:
                allowed_lower = {v.casefold() for v in definition.allowed_values}
                for item in coerced_list:
                    if item.casefold() not in allowed_lower:
                        raise ValueError(
                            f"Value '{item}' for '{definition.name}' is not in allowed values: "
                            f"{', '.join(definition.allowed_values)}"
                        )
            return coerced_list

        if field_type == "duration":
            coerced = str(value or "").strip()
            if not coerced:
                raise ValueError(f"Value for '{definition.name}' cannot be empty")
            if not _DURATION_PATTERN.match(coerced):
                raise ValueError(
                    f"Value '{coerced}' for '{definition.name}' is not a valid duration "
                    f"(expected format like '2d 4h', '1w 3d', '30m')"
                )
            return coerced

        if field_type == "labels":
            if not isinstance(value, list):
                raise ValueError(f"Value for '{definition.name}' must be a list of strings")
            coerced_list = [str(v or "").strip() for v in value]
            coerced_list = [v for v in coerced_list if v]
            return coerced_list

        raise ValueError(f"Unknown custom field type '{field_type}' for '{definition.name}'")

    @staticmethod
    def build_jira_field_payload(definition: CustomFieldDef, value: Any) -> Dict[str, Any]:
        field_type = definition.type
        field_id = definition.field_id

        if field_type == "string":
            return {field_id: value}

        if field_type == "number":
            return {field_id: value}

        if field_type == "option":
            return {field_id: {"value": value}}

        if field_type == "multi_option":
            return {field_id: [{"value": v} for v in value]}

        if field_type == "duration":
            return {"timetracking": {"originalEstimate": value}}

        if field_type == "labels":
            return {field_id: value}

        raise ValueError(f"Unknown custom field type '{field_type}' for '{definition.name}'")
