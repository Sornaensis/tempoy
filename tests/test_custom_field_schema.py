from __future__ import annotations

import json
import os
import tempfile
import unittest

from tempoy_app import config as config_module
from tempoy_app.config import CustomFieldsConfig, _normalize_custom_fields
from tempoy_app.services.custom_field_schema import CustomFieldDef, CustomFieldSchemaService


class NormalizeCustomFieldsTests(unittest.TestCase):
    def test_valid_string_field(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Release", "field_id": "customfield_10200", "type": "string", "max_length": 100},
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Release")
        self.assertEqual(result[0]["max_length"], 100)

    def test_valid_number_field(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Story Points", "field_id": "customfield_10016", "type": "number", "min": 0, "max": 100},
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["min"], 0.0)
        self.assertEqual(result[0]["max"], 100.0)

    def test_valid_option_field_with_allowed_values(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Team", "field_id": "customfield_10100", "type": "option", "allowed_values": ["A", "B"]},
        ])
        self.assertEqual(result[0]["allowed_values"], ["A", "B"])

    def test_option_field_without_allowed_values(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Team", "field_id": "customfield_10100", "type": "option"},
        ])
        self.assertEqual(len(result), 1)
        self.assertNotIn("allowed_values", result[0])

    def test_valid_duration_field(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Estimate", "field_id": "timetracking.originalEstimate", "type": "duration"},
        ])
        self.assertEqual(len(result), 1)

    def test_duration_field_wrong_field_id_dropped(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Bad", "field_id": "timetracking.remainingEstimate", "type": "duration"},
        ])
        self.assertEqual(len(result), 0)

    def test_valid_labels_field(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Tags", "field_id": "customfield_10300", "type": "labels"},
        ])
        self.assertEqual(len(result), 1)

    def test_missing_name_dropped(self) -> None:
        result = _normalize_custom_fields([
            {"field_id": "customfield_10016", "type": "number"},
        ])
        self.assertEqual(len(result), 0)

    def test_missing_field_id_dropped(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Points", "type": "number"},
        ])
        self.assertEqual(len(result), 0)

    def test_unknown_type_dropped(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Foo", "field_id": "customfield_10016", "type": "unknown"},
        ])
        self.assertEqual(len(result), 0)

    def test_non_dict_entries_dropped(self) -> None:
        result = _normalize_custom_fields(["not a dict", 42])
        self.assertEqual(len(result), 0)

    def test_non_list_input_returns_empty(self) -> None:
        self.assertEqual(_normalize_custom_fields("bad"), [])
        self.assertEqual(_normalize_custom_fields(None), [])
        self.assertEqual(_normalize_custom_fields(42), [])

    def test_empty_list(self) -> None:
        self.assertEqual(_normalize_custom_fields([]), [])

    def test_mixed_valid_and_invalid(self) -> None:
        result = _normalize_custom_fields([
            {"name": "Good", "field_id": "customfield_10016", "type": "number"},
            {"name": "", "field_id": "customfield_10017", "type": "number"},
            {"name": "Also Good", "field_id": "customfield_10018", "type": "string"},
        ])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Good")
        self.assertEqual(result[1]["name"], "Also Good")


class CustomFieldsConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_config_dir = config_module.CONFIG_DIR
        self.original_custom_fields_path = config_module.CUSTOM_FIELDS_PATH
        config_module.CONFIG_DIR = os.path.join(self.temp_dir.name, ".tempoy")
        config_module.CUSTOM_FIELDS_PATH = os.path.join(config_module.CONFIG_DIR, "custom_fields.json")

    def tearDown(self) -> None:
        config_module.CONFIG_DIR = self.original_config_dir
        config_module.CUSTOM_FIELDS_PATH = self.original_custom_fields_path
        self.temp_dir.cleanup()

    def test_load_returns_empty_when_file_missing(self) -> None:
        self.assertEqual(CustomFieldsConfig.load(), [])

    def test_save_and_load_roundtrip(self) -> None:
        fields = [
            {"name": "Points", "field_id": "customfield_10016", "type": "number", "min": 0, "max": 100},
            {"name": "Team", "field_id": "customfield_10100", "type": "option", "allowed_values": ["A", "B"]},
        ]
        CustomFieldsConfig.save(fields)
        loaded = CustomFieldsConfig.load()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["name"], "Points")
        self.assertEqual(loaded[1]["name"], "Team")

    def test_save_normalizes_fields(self) -> None:
        fields = [
            {"name": "Good", "field_id": "customfield_10016", "type": "number"},
            {"name": "", "field_id": "customfield_10017", "type": "number"},
        ]
        CustomFieldsConfig.save(fields)
        loaded = CustomFieldsConfig.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["name"], "Good")

    def test_load_handles_invalid_json(self) -> None:
        os.makedirs(config_module.CONFIG_DIR, exist_ok=True)
        with open(config_module.CUSTOM_FIELDS_PATH, "w") as fh:
            fh.write("not json")
        self.assertEqual(CustomFieldsConfig.load(), [])

    def test_load_handles_wrapped_format(self) -> None:
        os.makedirs(config_module.CONFIG_DIR, exist_ok=True)
        data = {"custom_fields": [
            {"name": "Points", "field_id": "customfield_10016", "type": "number"},
        ]}
        with open(config_module.CUSTOM_FIELDS_PATH, "w") as fh:
            json.dump(data, fh)
        loaded = CustomFieldsConfig.load()
        self.assertEqual(len(loaded), 1)


class CustomFieldDefTests(unittest.TestCase):
    def test_roundtrip_number(self) -> None:
        d = {"name": "Points", "field_id": "customfield_10016", "type": "number", "min": 0, "max": 100}
        definition = CustomFieldDef.from_dict(d)
        self.assertEqual(definition.name, "Points")
        result = definition.to_dict()
        self.assertEqual(result["min"], 0)
        self.assertEqual(result["max"], 100)

    def test_roundtrip_option(self) -> None:
        d = {"name": "Team", "field_id": "cf_100", "type": "option", "allowed_values": ["A", "B"]}
        definition = CustomFieldDef.from_dict(d)
        result = definition.to_dict()
        self.assertEqual(result["allowed_values"], ["A", "B"])

    def test_roundtrip_string(self) -> None:
        d = {"name": "Release", "field_id": "cf_200", "type": "string", "max_length": 50}
        definition = CustomFieldDef.from_dict(d)
        self.assertEqual(definition.to_dict()["max_length"], 50)

    def test_constraints_dict_number(self) -> None:
        d = CustomFieldDef(name="P", field_id="cf", type="number", min=1, max=10)
        self.assertEqual(d.constraints_dict(), {"min": 1, "max": 10})

    def test_constraints_dict_empty_for_labels(self) -> None:
        d = CustomFieldDef(name="Tags", field_id="cf", type="labels")
        self.assertEqual(d.constraints_dict(), {})


class ValidateValueTests(unittest.TestCase):
    def test_string_valid(self) -> None:
        d = CustomFieldDef(name="R", field_id="cf", type="string", max_length=10)
        self.assertEqual(CustomFieldSchemaService.validate_value(d, "hello"), "hello")

    def test_string_exceeds_max_length(self) -> None:
        d = CustomFieldDef(name="R", field_id="cf", type="string", max_length=3)
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, "toolong")

    def test_string_no_max_length(self) -> None:
        d = CustomFieldDef(name="R", field_id="cf", type="string")
        self.assertEqual(CustomFieldSchemaService.validate_value(d, "anything"), "anything")

    def test_number_valid(self) -> None:
        d = CustomFieldDef(name="P", field_id="cf", type="number", min=0, max=100)
        self.assertEqual(CustomFieldSchemaService.validate_value(d, 50), 50)

    def test_number_returns_int_when_whole(self) -> None:
        d = CustomFieldDef(name="P", field_id="cf", type="number")
        self.assertIsInstance(CustomFieldSchemaService.validate_value(d, 5.0), int)

    def test_number_returns_float_when_fractional(self) -> None:
        d = CustomFieldDef(name="P", field_id="cf", type="number")
        self.assertIsInstance(CustomFieldSchemaService.validate_value(d, 5.5), float)

    def test_number_below_min(self) -> None:
        d = CustomFieldDef(name="P", field_id="cf", type="number", min=0)
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, -1)

    def test_number_above_max(self) -> None:
        d = CustomFieldDef(name="P", field_id="cf", type="number", max=10)
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, 11)

    def test_number_invalid_type(self) -> None:
        d = CustomFieldDef(name="P", field_id="cf", type="number")
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, "not a number")

    def test_option_valid(self) -> None:
        d = CustomFieldDef(name="T", field_id="cf", type="option", allowed_values=["A", "B"])
        self.assertEqual(CustomFieldSchemaService.validate_value(d, "A"), "A")

    def test_option_case_insensitive(self) -> None:
        d = CustomFieldDef(name="T", field_id="cf", type="option", allowed_values=["Alpha"])
        self.assertEqual(CustomFieldSchemaService.validate_value(d, "alpha"), "alpha")

    def test_option_invalid_choice(self) -> None:
        d = CustomFieldDef(name="T", field_id="cf", type="option", allowed_values=["A", "B"])
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, "C")

    def test_option_no_allowed_values_skips_validation(self) -> None:
        d = CustomFieldDef(name="T", field_id="cf", type="option")
        self.assertEqual(CustomFieldSchemaService.validate_value(d, "anything"), "anything")

    def test_option_empty_value_rejected(self) -> None:
        d = CustomFieldDef(name="T", field_id="cf", type="option")
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, "")

    def test_multi_option_valid(self) -> None:
        d = CustomFieldDef(name="T", field_id="cf", type="multi_option", allowed_values=["A", "B"])
        self.assertEqual(CustomFieldSchemaService.validate_value(d, ["A", "B"]), ["A", "B"])

    def test_multi_option_not_list(self) -> None:
        d = CustomFieldDef(name="T", field_id="cf", type="multi_option")
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, "single")

    def test_multi_option_invalid_choice(self) -> None:
        d = CustomFieldDef(name="T", field_id="cf", type="multi_option", allowed_values=["A"])
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, ["A", "C"])

    def test_duration_valid(self) -> None:
        d = CustomFieldDef(name="E", field_id="timetracking.originalEstimate", type="duration")
        self.assertEqual(CustomFieldSchemaService.validate_value(d, "2d 4h"), "2d 4h")

    def test_duration_single_unit(self) -> None:
        d = CustomFieldDef(name="E", field_id="timetracking.originalEstimate", type="duration")
        self.assertEqual(CustomFieldSchemaService.validate_value(d, "30m"), "30m")

    def test_duration_invalid_format(self) -> None:
        d = CustomFieldDef(name="E", field_id="timetracking.originalEstimate", type="duration")
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, "two days")

    def test_duration_empty_rejected(self) -> None:
        d = CustomFieldDef(name="E", field_id="timetracking.originalEstimate", type="duration")
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, "")

    def test_labels_valid(self) -> None:
        d = CustomFieldDef(name="Tags", field_id="cf", type="labels")
        self.assertEqual(CustomFieldSchemaService.validate_value(d, ["x", "y"]), ["x", "y"])

    def test_labels_not_list(self) -> None:
        d = CustomFieldDef(name="Tags", field_id="cf", type="labels")
        with self.assertRaises(ValueError):
            CustomFieldSchemaService.validate_value(d, "single")

    def test_labels_strips_empty(self) -> None:
        d = CustomFieldDef(name="Tags", field_id="cf", type="labels")
        self.assertEqual(CustomFieldSchemaService.validate_value(d, ["a", "", "b"]), ["a", "b"])


class BuildJiraFieldPayloadTests(unittest.TestCase):
    def test_string(self) -> None:
        d = CustomFieldDef(name="R", field_id="customfield_200", type="string")
        self.assertEqual(
            CustomFieldSchemaService.build_jira_field_payload(d, "hello"),
            {"customfield_200": "hello"},
        )

    def test_number(self) -> None:
        d = CustomFieldDef(name="P", field_id="customfield_100", type="number")
        self.assertEqual(
            CustomFieldSchemaService.build_jira_field_payload(d, 5),
            {"customfield_100": 5},
        )

    def test_option(self) -> None:
        d = CustomFieldDef(name="T", field_id="customfield_101", type="option")
        self.assertEqual(
            CustomFieldSchemaService.build_jira_field_payload(d, "Alpha"),
            {"customfield_101": {"value": "Alpha"}},
        )

    def test_multi_option(self) -> None:
        d = CustomFieldDef(name="T", field_id="customfield_102", type="multi_option")
        self.assertEqual(
            CustomFieldSchemaService.build_jira_field_payload(d, ["A", "B"]),
            {"customfield_102": [{"value": "A"}, {"value": "B"}]},
        )

    def test_duration(self) -> None:
        d = CustomFieldDef(name="E", field_id="timetracking.originalEstimate", type="duration")
        self.assertEqual(
            CustomFieldSchemaService.build_jira_field_payload(d, "2d 4h"),
            {"timetracking": {"originalEstimate": "2d 4h"}},
        )

    def test_labels(self) -> None:
        d = CustomFieldDef(name="Tags", field_id="customfield_300", type="labels")
        self.assertEqual(
            CustomFieldSchemaService.build_jira_field_payload(d, ["x", "y"]),
            {"customfield_300": ["x", "y"]},
        )


class LoadDefinitionsTests(unittest.TestCase):
    def test_load_valid_entries(self) -> None:
        raw = [
            {"name": "Points", "field_id": "cf_100", "type": "number", "min": 0, "max": 100},
            {"name": "Team", "field_id": "cf_200", "type": "option", "allowed_values": ["A"]},
        ]
        defs = CustomFieldSchemaService.load_definitions(raw)
        self.assertEqual(len(defs), 2)
        self.assertEqual(defs[0].name, "Points")
        self.assertEqual(defs[1].name, "Team")

    def test_load_skips_non_dict(self) -> None:
        raw = [{"name": "Points", "field_id": "cf_100", "type": "number"}, "bad", 42]
        defs = CustomFieldSchemaService.load_definitions(raw)
        self.assertEqual(len(defs), 1)

    def test_load_empty(self) -> None:
        self.assertEqual(CustomFieldSchemaService.load_definitions([]), [])


if __name__ == "__main__":
    unittest.main()
