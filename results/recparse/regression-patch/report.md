# Patch validation report — recparse

Run `20261118T125455Z` · config `recparse.yaml`

## Verdict

**FUNC_REGRESSION** (exit code 20)

> at least one input that behaved correctly on the base build violates the independent oracle on the patched build

| axis | status |
|---|---|
| security | `CLEAN` |
| functional | `REGRESSION` |
| analysis completeness | `COMPLETE` |

### Why

- the fault reproduced on the base build is not observed on the patched build, and no other memory error was confirmed
- FUNCTIONAL_REGRESSION: behaviour required by the specification was correct on base and is violated on the patched build: termination: expected exit code 0, observed exit code 2; stdout: expected 'records: 1\nTEXT[24]: payload of 24 bytes.....\n', observed 'records: 1\n'; stderr: expected no output, observed 'error: text record too long (24 bytes)\n'
- FUNCTIONAL_REGRESSION: behaviour required by the specification was correct on base and is violated on the patched build: termination: expected exit code 0, observed exit code 2; stdout: expected 'records: 1\nTEXT[31]: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n', observed 'records: 1\n'; stderr: expected no output, observed 'error: text record too long (31 bytes)\n'

## What was compared

| | revision | commit | subject |
|---|---|---|---|
| base | `base` | `9d8c9fe9666b` | recparse: initial RECV1 record parser |
| patched | `regression-patch` | `9fab745d700a` | parser: bound payload copy and tighten the text limit |

The patch touches 1 file(s) in 2 hunk(s).
- `src/record.c`: `copy_payload()`, `handle_text()`

## Builds

| version | mode | compiler | flags | sha256 |
|---|---|---|---|---|
| base | release | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-O2 -g -fno-omit-frame-pointer` | `fb9dfcf54b9a` |
| base | sanitized | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined` | `23c087b73ea8` |
| patched | release | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-O2 -g -fno-omit-frame-pointer` | `b9c26e9dfce9` |
| patched | sanitized | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined` | `8972a1c0557e` |

## Security findings

### `FIXED` — boundary_text32 (sanitized)

STACK_BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:22 (exit code 1)
- patched: no fault; exit code 2
- correlation with the diff: `CONFIRMED` (confidence `high`)
  - affected: `src/record.c` in `handle_text()`
  - the relationship is indirect, through a caller
  - frame #1: src/record.c:30 is a line this patch changed (@@ -27,6 +28,12 @@ static int handle_text(const uint8_t *payload, size_t len))
  - the relationship is indirect: the fault surfaced in copy_payload at src/record.c:22, which is reached from the changed code
  - frame #0: the fault is inside copy_payload() (lines 11-24), which the patch modified, but not on a changed line
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/boundary_text32/base.sanitized/stderr.bin`, `exec/boundary_text32/base.sanitized/stdout.bin`, `exec/boundary_text32/patched.sanitized/stderr.bin`, `exec/boundary_text32/patched.sanitized/stdout.bin`

### `FIXED` — boundary_raw32 (sanitized)

STACK_BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:22 (exit code 1)
- patched: no fault; exit code 2
- correlation with the diff: `LIKELY` (confidence `medium`)
  - affected: `src/record.c` in `copy_payload()`
  - frame #0: the fault is inside copy_payload() (lines 11-24), which the patch modified, but not on a changed line
  - frame #1: src/record.c was modified by the patch, but the fault is outside every changed function
  - frame #2: src/record.c was modified by the patch, but the fault is outside every changed function
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/boundary_raw32/base.sanitized/stderr.bin`, `exec/boundary_raw32/base.sanitized/stdout.bin`, `exec/boundary_raw32/patched.sanitized/stderr.bin`, `exec/boundary_raw32/patched.sanitized/stdout.bin`

### `FIXED` — vuln_text_long (release)

BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: BUFFER_OVERFLOW detected by fortify_source (terminated by SIGABRT, inferred)
- patched: no fault; exit code 2
- correlation with the diff: `UNKNOWN` (confidence `none`)
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/vuln_text_long/base.release/stderr.bin`, `exec/vuln_text_long/base.release/stdout.bin`, `exec/vuln_text_long/patched.release/stderr.bin`, `exec/vuln_text_long/patched.release/stdout.bin`

### `FIXED` — vuln_text_long (sanitized)

STACK_BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:21 (exit code 1)
- patched: no fault; exit code 2
- correlation with the diff: `CONFIRMED` (confidence `high`)
  - affected: `src/record.c` in `handle_text()`
  - the relationship is indirect, through a caller
  - frame #3: src/record.c:30 is a line this patch changed (@@ -27,6 +28,12 @@ static int handle_text(const uint8_t *payload, size_t len))
  - the relationship is indirect: the fault surfaced in copy_payload at src/record.c:21, which is reached from the changed code
  - frame #2: the fault is inside copy_payload() (lines 11-24), which the patch modified, but not on a changed line
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/vuln_text_long/base.sanitized/stderr.bin`, `exec/vuln_text_long/base.sanitized/stdout.bin`, `exec/vuln_text_long/patched.sanitized/stderr.bin`, `exec/vuln_text_long/patched.sanitized/stdout.bin`

### `FIXED` — vuln_raw_long (release)

BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: BUFFER_OVERFLOW detected by fortify_source (terminated by SIGABRT, inferred)
- patched: no fault; exit code 2
- correlation with the diff: `UNKNOWN` (confidence `none`)
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/vuln_raw_long/base.release/stderr.bin`, `exec/vuln_raw_long/base.release/stdout.bin`, `exec/vuln_raw_long/patched.release/stderr.bin`, `exec/vuln_raw_long/patched.release/stdout.bin`

### `FIXED` — vuln_raw_long (sanitized)

STACK_BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:21 (exit code 1)
- patched: no fault; exit code 2
- correlation with the diff: `LIKELY` (confidence `medium`)
  - affected: `src/record.c` in `copy_payload()`
  - frame #2: the fault is inside copy_payload() (lines 11-24), which the patch modified, but not on a changed line
  - frame #3: src/record.c was modified by the patch, but the fault is outside every changed function
  - frame #4: src/record.c was modified by the patch, but the fault is outside every changed function
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/vuln_raw_long/base.sanitized/stderr.bin`, `exec/vuln_raw_long/base.sanitized/stdout.bin`, `exec/vuln_raw_long/patched.sanitized/stderr.bin`, `exec/vuln_raw_long/patched.sanitized/stdout.bin`

## Functional findings

| kind | test | mode | authoritative | summary |
|---|---|---|---|---|
| `FUNCTIONAL_REGRESSION` | valid_text24 | release | yes | behaviour required by the specification was correct on base and is violated on the patched build: termination: expected exit code 0, observed exit code 2; stdout: expected 'records: 1\nTEXT[24]: payload of 24 bytes.....\n', observed 'records: 1\n'; stderr: expected no output, observed 'error: text record too long (24 bytes)\n' |
| `FUNCTIONAL_REGRESSION` | valid_text24 | sanitized | no | behaviour required by the specification was correct on base and is violated on the patched build: termination: expected exit code 0, observed exit code 2; stdout: expected 'records: 1\nTEXT[24]: payload of 24 bytes.....\n', observed 'records: 1\n'; stderr: expected no output, observed 'error: text record too long (24 bytes)\n' |
| `FUNCTIONAL_REGRESSION` | boundary_text31 | release | yes | behaviour required by the specification was correct on base and is violated on the patched build: termination: expected exit code 0, observed exit code 2; stdout: expected 'records: 1\nTEXT[31]: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n', observed 'records: 1\n'; stderr: expected no output, observed 'error: text record too long (31 bytes)\n' |
| `FUNCTIONAL_REGRESSION` | boundary_text31 | sanitized | no | behaviour required by the specification was correct on base and is violated on the patched build: termination: expected exit code 0, observed exit code 2; stdout: expected 'records: 1\nTEXT[31]: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n', observed 'records: 1\n'; stderr: expected no output, observed 'error: text record too long (31 bytes)\n' |
| `FUNCTIONAL_FIX` | boundary_text32 | release | yes | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | boundary_text32 | sanitized | no | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | boundary_raw32 | release | yes | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | boundary_raw32 | sanitized | no | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | vuln_text_long | release | yes | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | vuln_text_long | sanitized | no | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | vuln_raw_long | release | yes | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | vuln_raw_long | sanitized | no | the patched build now satisfies a specification requirement that the base build violated |

## Release build versus sanitized build

2 case(s) produced a fault only under the sanitized build. The release build gave no indication of a problem for these inputs:

| test | version | release | sanitized |
|---|---|---|---|
| boundary_text32 | base | clean (exit 0) | STACK_BUFFER_OVERFLOW |
| boundary_raw32 | base | clean (exit 0) | STACK_BUFFER_OVERFLOW |

## Reproduction

| finding | replays | matched | stability | bundle |
|---|---|---|---|---|
| `sec/boundary_text32/sanitized` | 3 | 3 | `stable` | `bundles/sec__boundary_text32__sanitized` |
| `sec/boundary_raw32/sanitized` | 3 | 3 | `stable` | `bundles/sec__boundary_raw32__sanitized` |
| `sec/vuln_text_long/release` | 3 | 3 | `stable` | `bundles/sec__vuln_text_long__release` |

## Minimization

| finding | original | minimized | reduction | probes | stopped because |
|---|---|---|---|---|---|
| `sec/boundary_text32/sanitized` | 40 B | 40 B | 0.0% | 24 | no further reduction possible |
| `sec/boundary_raw32/sanitized` | 40 B | 40 B | 0.0% | 78 | no further reduction possible |
| `sec/vuln_text_long/release` | 208 B | 73 B | 64.9% | 65 | no further reduction possible |

## Generated regression tests

- `regression_boundary_text32_81a3c2ba` (40 B) from finding `sec/boundary_text32/sanitized` → `regression/regression_boundary_text32_81a3c2ba/testcase.yaml`
- `regression_boundary_raw32_83e50dc6` (40 B) from finding `sec/boundary_raw32/sanitized` → `regression/regression_boundary_raw32_83e50dc6/testcase.yaml`
- `regression_vuln_text_long_901649ba` (73 B) from finding `sec/vuln_text_long/release` → `regression/regression_vuln_text_long_901649ba/testcase.yaml`

## Binary hardening

| protection | base | patched | change |
|---|---|---|---|
| nx | `enabled` | `enabled` | `unchanged` |
| pie | `enabled` | `enabled` | `unchanged` |
| relro | `full` | `full` | `unchanged` |
| stack_canary | `enabled` | `enabled` | `unchanged` |
| fortify | `enabled` | `enabled` | `unchanged` |

Limitations of this analysis:

- a position-independent executable does not establish that ASLR is active at run time; that is a property of the kernel and the execution environment, not of the binary
- evidence of a stack canary shows the protection is in use somewhere, not that every function is protected; the compiler decides per function
- the absence of a mitigation here is a property of this build only, and says nothing about how the project is built elsewhere

## Mandatory checks

| check | result | detail |
|---|---|---|
| builds_succeeded | pass | every configured build produced a binary |
| full_matrix_executed | pass | 72/72 executions completed |
| base_fault_reproduced | pass | a fault was observed on the base build |
| findings_reproducible | pass | every confirmed finding replayed consistently |
| correlation_attempted | pass | every security finding was correlated against the diff |
| hardening_analyzed | pass | binary protections compared between both release builds |
| functional_oracle_available | pass | 18 test case(s) carry an oracle |
| executions_isolated | pass | all executions ran under the 'bubblewrap' sandbox |

## Environment

- sandbox backend: `bubblewrap`
- isolated: yes
- platform: Linux-7.0.0-34-generic-x86_64-with-glibc2.39
- kernel: 7.0.0-34-generic
- python: 3.12.3
- container image: `local`

---

Every claim above is backed by an artifact under this run directory. Paths in the `evidence` fields are relative to it.
