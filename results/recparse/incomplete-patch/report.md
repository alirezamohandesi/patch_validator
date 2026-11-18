# Patch validation report — recparse

Run `20261118T125445Z` · config `recparse.yaml`

## Verdict

**VULN_REMAINS_OR_NEW_ISSUE** (exit code 10)

> the original fault still occurs, or another memory error was confirmed with valid evidence on the patched build

| axis | status |
|---|---|
| security | `VULNERABLE` |
| functional | `PASS` |
| analysis completeness | `COMPLETE` |

### Why

- INCOMPLETE_FIX: STACK_BUFFER_OVERFLOW still reproduces on the patched build for this input
- INCOMPLETE_FIX: BUFFER_OVERFLOW still reproduces on the patched build for this input
- INCOMPLETE_FIX: STACK_BUFFER_OVERFLOW still reproduces on the patched build for this input

## What was compared

| | revision | commit | subject |
|---|---|---|---|
| base | `base` | `9d8c9fe9666b` | recparse: initial RECV1 record parser |
| patched | `incomplete-patch` | `0bf3795ca844` | parser: reject over-long text records |

The patch touches 1 file(s) in 1 hunk(s).
- `src/record.c`: `handle_text()`

## Builds

| version | mode | compiler | flags | sha256 |
|---|---|---|---|---|
| base | release | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-O2 -g -fno-omit-frame-pointer` | `1b6d99c79708` |
| base | sanitized | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined` | `f32574ec30a6` |
| patched | release | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-O2 -g -fno-omit-frame-pointer` | `a0543fe50bfc` |
| patched | sanitized | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined` | `d1c57ad3f280` |

## Security findings

### `FIXED` — boundary_text32 (sanitized)

STACK_BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:22 (exit code 1)
- patched: no fault; exit code 2
- correlation with the diff: `CONFIRMED` (confidence `high`)
  - affected: `src/record.c` in `handle_text()`
  - the relationship is indirect, through a caller
  - frame #1: src/record.c:30 is a line this patch changed (@@ -27,6 +27,12 @@ static int handle_text(const uint8_t *payload, size_t len))
  - the relationship is indirect: the fault surfaced in copy_payload at src/record.c:22, which is reached from the changed code
  - frame #0: src/record.c was modified by the patch, but the fault is outside every changed function
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/boundary_text32/base.sanitized/stderr.bin`, `exec/boundary_text32/base.sanitized/stdout.bin`, `exec/boundary_text32/patched.sanitized/stderr.bin`, `exec/boundary_text32/patched.sanitized/stdout.bin`

### `INCOMPLETE_FIX` — boundary_raw32 (sanitized)

STACK_BUFFER_OVERFLOW still reproduces on the patched build for this input

- confidence: `high`
- base: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:22 (exit code 1)
- patched: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:22 (exit code 1)
- correlation with the diff: `WEAK` (confidence `low`)
  - affected: `src/record.c` in `copy_payload()`
  - frame #0: src/record.c was modified by the patch, but the fault is outside every changed function
  - frame #1: src/record.c was modified by the patch, but the fault is outside every changed function
  - frame #2: src/record.c was modified by the patch, but the fault is outside every changed function
- note: the input that triggered the original fault still triggers a fault after the patch
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
  - frame #3: src/record.c:30 is a line this patch changed (@@ -27,6 +27,12 @@ static int handle_text(const uint8_t *payload, size_t len))
  - the relationship is indirect: the fault surfaced in copy_payload at src/record.c:21, which is reached from the changed code
  - frame #2: src/record.c was modified by the patch, but the fault is outside every changed function
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/vuln_text_long/base.sanitized/stderr.bin`, `exec/vuln_text_long/base.sanitized/stdout.bin`, `exec/vuln_text_long/patched.sanitized/stderr.bin`, `exec/vuln_text_long/patched.sanitized/stdout.bin`

### `INCOMPLETE_FIX` — vuln_raw_long (release)

BUFFER_OVERFLOW still reproduces on the patched build for this input

- confidence: `high`
- base: BUFFER_OVERFLOW detected by fortify_source (terminated by SIGABRT, inferred)
- patched: BUFFER_OVERFLOW detected by fortify_source (terminated by SIGABRT, inferred)
- correlation with the diff: `UNKNOWN` (confidence `none`)
- note: the input that triggered the original fault still triggers a fault after the patch
- evidence: `exec/vuln_raw_long/base.release/stderr.bin`, `exec/vuln_raw_long/base.release/stdout.bin`, `exec/vuln_raw_long/patched.release/stderr.bin`, `exec/vuln_raw_long/patched.release/stdout.bin`

### `INCOMPLETE_FIX` — vuln_raw_long (sanitized)

STACK_BUFFER_OVERFLOW still reproduces on the patched build for this input

- confidence: `high`
- base: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:21 (exit code 1)
- patched: STACK_BUFFER_OVERFLOW detected by address_sanitizer at src/record.c:21 (exit code 1)
- correlation with the diff: `WEAK` (confidence `low`)
  - affected: `src/record.c` in `copy_payload()`
  - frame #2: src/record.c was modified by the patch, but the fault is outside every changed function
  - frame #3: src/record.c was modified by the patch, but the fault is outside every changed function
  - frame #4: src/record.c was modified by the patch, but the fault is outside every changed function
- note: the input that triggered the original fault still triggers a fault after the patch
- evidence: `exec/vuln_raw_long/base.sanitized/stderr.bin`, `exec/vuln_raw_long/base.sanitized/stdout.bin`, `exec/vuln_raw_long/patched.sanitized/stderr.bin`, `exec/vuln_raw_long/patched.sanitized/stdout.bin`

## Functional findings

| kind | test | mode | authoritative | summary |
|---|---|---|---|---|
| `FUNCTIONAL_FIX` | boundary_text32 | release | yes | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | boundary_text32 | sanitized | no | the patched build now satisfies a specification requirement that the base build violated |
| `PRE_EXISTING_DEFECT` | boundary_raw32 | release | yes | both builds violate the specification for this input, identically |
| `PRE_EXISTING_DEFECT` | boundary_raw32 | sanitized | no | both builds violate the specification for this input, identically |
| `FUNCTIONAL_FIX` | vuln_text_long | release | yes | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | vuln_text_long | sanitized | no | the patched build now satisfies a specification requirement that the base build violated |
| `PRE_EXISTING_DEFECT` | vuln_raw_long | release | yes | both builds violate the specification for this input, identically |
| `PRE_EXISTING_DEFECT` | vuln_raw_long | sanitized | no | both builds violate the specification for this input, identically |

## Release build versus sanitized build

3 case(s) produced a fault only under the sanitized build. The release build gave no indication of a problem for these inputs:

| test | version | release | sanitized |
|---|---|---|---|
| boundary_text32 | base | clean (exit 0) | STACK_BUFFER_OVERFLOW |
| boundary_raw32 | base | clean (exit 0) | STACK_BUFFER_OVERFLOW |
| boundary_raw32 | patched | clean (exit 0) | STACK_BUFFER_OVERFLOW |

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
