# regression_boundary_text32_81a3c2ba

Generated automatically from finding `sec/boundary_text32/sanitized`.

## What it guards against

    STACK_BUFFER_OVERFLOW detected by address_sanitizer
    at src/record.c:22

The input is the minimized reproducer: 40 bytes.

## What it asserts

1. The base build still faults on this input with the recorded location
   signature `9282e2706f43a1ff…`. If it stops faulting, the
   test no longer guards anything and the assertion catches that.
2. The patched build does not fault on this input.
3. The patched build matches the independent oracle for this input:

    source: specification
    input_validity: boundary
    instructor_approved: pending
    exit_code: 2
    stdout: {'match': 'exact', 'value': 'records: 1\n'}
    stderr: {'match': 'contains', 'value': 'too long'}
    semantics: Length 32 must be rejected, not truncated and not processed.

Assertion 3 is the one that matters most. Without it, a change that makes the
program exit before reaching the parser would satisfy assertions 1 and 2 while
breaking the program.

## Running it

    patch-validator regression --config <config.yaml> --suite <run>/regression/suite.json

The generated test case in `testcase.yaml` can also be merged into a target
configuration, after which it runs as part of the normal matrix.
