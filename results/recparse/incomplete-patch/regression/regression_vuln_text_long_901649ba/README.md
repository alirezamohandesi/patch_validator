# regression_vuln_text_long_901649ba

Generated automatically from finding `sec/vuln_text_long/release`.

## What it guards against

    BUFFER_OVERFLOW detected by fortify_source
    at an unknown location

The input is the minimized reproducer: 73 bytes.

## What it asserts

1. The base build still faults on this input with the recorded location
   signature `29a059abcc6d8213…`. If it stops faulting, the
   test no longer guards anything and the assertion catches that.
2. The patched build does not fault on this input.
3. The patched build matches the independent oracle for this input:

    source: specification
    input_validity: invalid
    instructor_approved: pending
    exit_code: 2
    stdout: {'match': 'exact', 'value': 'records: 1\n'}
    stderr: {'match': 'contains', 'value': 'too long'}
    semantics: An over-long TEXT record must be rejected without any out-of-bounds write.

Assertion 3 is the one that matters most. Without it, a change that makes the
program exit before reaching the parser would satisfy assertions 1 and 2 while
breaking the program.

## Running it

    patch-validator regression --config <config.yaml> --suite <run>/regression/suite.json

The generated test case in `testcase.yaml` can also be merged into a target
configuration, after which it runs as part of the normal matrix.
