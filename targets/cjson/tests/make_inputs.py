#!/usr/bin/env python3
"""Generate the cJSON test corpus.

Every input is produced from this script so the corpus is reproducible
byte-for-byte.  Expected behaviour for each one comes from RFC 8259 and from
cJSON's documented API, never from running a build — see SPECIFICATION.md.

    python3 targets/cjson/tests/make_inputs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "inputs"

CORPUS: dict[str, bytes] = {
    # --- valid: RFC 8259 documents -------------------------------------
    "valid_object": b'{"name":"cjson","version":1}',
    "valid_array": b"[1,2,3]",
    "valid_nested": b'{"a":{"b":[1,{"c":true}]}}',
    "valid_literals": b"[true,false,null]",
    "valid_string": b'"hello"',
    "valid_number_zero": b"0",
    "valid_negative": b"-42",
    # --- boundary -------------------------------------------------------
    "boundary_empty_object": b"{}",
    "boundary_empty_array": b"[]",
    # Well inside cJSON's documented nesting limit of 1000.
    "boundary_deep_nesting": b"[" * 100 + b"1" + b"]" * 100,
    "boundary_object_in_array": b'[{"k":[]}]',
    # --- security: malformed documents that truncate mid-structure ------
    # The object reproducer: a comma with nothing after it. The parser has
    # to look at the byte after the comma, and that byte is past the end of
    # the buffer.
    "security_object_truncated_after_comma": b'{"a":1,',
    "security_object_truncated_after_comma_alt": b'{"longer key":"value",',
    "security_nested_object_truncated": b'{"outer":{"inner":1,',
    # The same shape in an array. The array path was already correct, so
    # this is the control: a sibling input that does not reproduce the bug.
    "invalid_array_truncated_after_comma": b"[1,",
    # --- invalid: rejected by the grammar -------------------------------
    "invalid_empty": b"",
    "invalid_unclosed_string": b'"abc',
    "invalid_unclosed_array": b"[1,2",
    "invalid_unclosed_object": b'{"a":1',
    # cJSON_ParseWithLength parses a value from the start of the buffer and
    # does not require the buffer to be fully consumed; trailing bytes are
    # therefore not an error for this entry point. See SPECIFICATION.md.
    "boundary_trailing_bytes": b'{"a":1}x',
    "invalid_lone_comma": b",",
    "invalid_bare_word": b"notjson",
    "invalid_missing_value": b'{"a":}',
    "invalid_missing_colon": b'{"a" 1}',
}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(CORPUS.items()):
        path = OUT_DIR / f"{name}.json"
        path.write_bytes(data)
        print(f"{path.name}: {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
