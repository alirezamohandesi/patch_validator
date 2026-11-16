"""JSON Schema for the target configuration file.

Validating the configuration before anything runs is what turns a typo into a
clean exit code 30 instead of a confusing failure halfway through a build
(R-EXIT-04).
"""

from __future__ import annotations

from typing import Any

_COMMAND = {
    "oneOf": [
        {"type": "string", "minLength": 1},
        {"type": "array", "items": {"type": "string"}, "minItems": 1},
    ]
}

_MATCHER = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "match": {"enum": ["exact", "contains", "regex", "absent", "ignore"]},
        "value": {"type": "string"},
    },
    "required": ["match"],
}

CONFIG_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "patch-validator target configuration",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "target", "builds", "input", "tests"],
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1, "maximum": 1},
        "base_dir": {
            "type": "string",
            "description": "Root for relative paths; defaults to the config file directory.",
        },
        "target": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "repo_path", "base_revision", "patched_revision"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string"},
                "language": {"enum": ["c", "c++"]},
                "repo_path": {"type": "string"},
                "source_subdir": {"type": "string"},
                "base_revision": {"type": "string", "minLength": 1},
                "patched_revision": {"type": "string", "minLength": 1},
            },
        },
        "builds": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "commands", "binary_path"],
                "properties": {
                    "mode": {"enum": ["release", "sanitized"]},
                    "compiler": {"type": "string"},
                    "cflags": {"type": "string"},
                    "ldflags": {"type": "string"},
                    "commands": {"type": "array", "minItems": 1, "items": _COMMAND},
                    "binary_path": {"type": "string", "minLength": 1},
                    "env": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
            },
        },
        "input": {
            "type": "object",
            "additionalProperties": False,
            "required": ["method"],
            "properties": {
                "method": {"enum": ["stdin", "file", "argv"]},
                "argv": {"type": "array", "items": {"type": "string"}},
                "filename": {"type": "string", "minLength": 1},
            },
        },
        "limits": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "timeout_s": {"type": "number", "exclusiveMinimum": 0},
                "memory_mb": {"type": "integer", "minimum": 16},
                "cpu_s": {"type": "integer", "minimum": 1},
                "max_processes": {"type": "integer", "minimum": 1},
                "max_output_bytes": {"type": "integer", "minimum": 1024},
                "max_file_size_mb": {"type": "integer", "minimum": 1},
            },
        },
        "sandbox": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "backend": {"enum": ["bubblewrap", "subprocess"]},
                "network": {"type": "boolean"},
                "unsafe_ack": {"type": "boolean"},
                "extra_ro_binds": {"type": "array", "items": {"type": "string"}},
            },
        },
        "minimization": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "enabled": {"type": "boolean"},
                "max_iterations": {"type": "integer", "minimum": 1},
                "budget_seconds": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        "reproduction": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                # The specification mandates at least three replays.
                "replays": {"type": "integer", "minimum": 3},
            },
        },
        "tests": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "category", "input"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]+$"},
                    "category": {"enum": ["valid", "boundary", "invalid", "security"]},
                    "note": {"type": "string"},
                    "timeout_s": {"type": "number", "exclusiveMinimum": 0},
                    "input": {
                        "type": "object",
                        "additionalProperties": False,
                        "minProperties": 1,
                        "maxProperties": 1,
                        "properties": {
                            "path": {"type": "string"},
                            "text": {"type": "string"},
                            "base64": {"type": "string"},
                        },
                    },
                    "oracle": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["source", "input_validity"],
                        "properties": {
                            "source": {
                                "enum": [
                                    "specification",
                                    "upstream_docs",
                                    "reference_test_suite",
                                    "instructor_approved",
                                ]
                            },
                            "input_validity": {"enum": ["valid", "boundary", "invalid"]},
                            "instructor_approved": {"enum": ["yes", "no", "pending"]},
                            "exit_code": {"type": ["integer", "null"]},
                            "stdout": _MATCHER,
                            "stderr": _MATCHER,
                            "semantics": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}
