# regression_security_object_truncated_after_comma_70b71985

Generated automatically from finding `sec/security_object_truncated_after_comma/sanitized`.

## What it guards against

    HEAP_BUFFER_OVERFLOW detected by address_sanitizer
    at cJSON.c:787

The input is the minimized reproducer: 6 bytes.

## What it asserts

1. The base build still faults on this input with the recorded location
   signature `9d99d0e333e7e23f…`. If it stops faulting, the
   test no longer guards anything and the assertion catches that.
2. The patched build does not fault on this input.
3. The patched build matches the independent oracle for this input:

    source: upstream_docs
    input_validity: invalid
    instructor_approved: pending
    exit_code: 1
    stderr: {'match': 'contains', 'value': 'invalid json'}
    semantics: An object that ends immediately after a member separator is incomplete and must be rejected without reading past the supplied length.

Assertion 3 is the one that matters most. Without it, a change that makes the
program exit before reaching the parser would satisfy assertions 1 and 2 while
breaking the program.

## Running it

    patch-validator regression --config <config.yaml> --suite <run>/regression/suite.json

The generated test case in `testcase.yaml` can also be merged into a target
configuration, after which it runs as part of the normal matrix.
