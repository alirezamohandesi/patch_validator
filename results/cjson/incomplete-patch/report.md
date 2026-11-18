# Patch validation report — cjson

Run `20261118T125511Z` · config `cjson.yaml`

## Verdict

**VULN_REMAINS_OR_NEW_ISSUE** (exit code 10)

> the original fault still occurs, or another memory error was confirmed with valid evidence on the patched build

| axis | status |
|---|---|
| security | `VULNERABLE` |
| functional | `PASS` |
| analysis completeness | `COMPLETE` |

### Why

- INCOMPLETE_FIX: HEAP_BUFFER_OVERFLOW still reproduces on the patched build for this input

## What was compared

| | revision | commit | subject |
|---|---|---|---|
| base | `pv-base` | `826cd6f842ae` | Add test for heap buffer overflow |
| patched | `pv-incomplete` | `647a78128ab0` | parse_object: reject a top-level object that ends after a comma |

The patch touches 1 file(s) in 1 hunk(s).
- `cJSON.c`: `parse_object()`

## Builds

| version | mode | compiler | flags | sha256 |
|---|---|---|---|---|
| base | release | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-std=c99 -O2 -g -fno-omit-frame-pointer` | `3253dab34888` |
| base | sanitized | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-std=c99 -O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined` | `350744e2525a` |
| patched | release | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-std=c99 -O2 -g -fno-omit-frame-pointer` | `5ff957ffc4d2` |
| patched | sanitized | gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | `-std=c99 -O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined` | `dd0717a7270c` |

## Security findings

### `FIXED` — security_object_truncated_after_comma (sanitized)

HEAP_BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: HEAP_BUFFER_OVERFLOW detected by address_sanitizer at cJSON.c:787 (exit code 1)
- patched: no fault; exit code 1
- correlation with the diff: `LIKELY` (confidence `medium`)
  - affected: `cJSON.c` in `parse_object()`
  - the relationship is indirect, through a caller
  - frame #1: the fault is inside parse_object() (lines 1607-1717), which the patch modified, but not on a changed line
  - the relationship is indirect: the fault surfaced in parse_string at cJSON.c:787, which is reached from the changed code
  - frame #0: cJSON.c was modified by the patch, but the fault is outside every changed function
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/security_object_truncated_after_comma/base.sanitized/stderr.bin`, `exec/security_object_truncated_after_comma/base.sanitized/stdout.bin`, `exec/security_object_truncated_after_comma/patched.sanitized/stderr.bin`, `exec/security_object_truncated_after_comma/patched.sanitized/stdout.bin`

### `FIXED` — security_object_truncated_after_comma_alt (sanitized)

HEAP_BUFFER_OVERFLOW observed on base is no longer observed on the patched build

- confidence: `high`
- base: HEAP_BUFFER_OVERFLOW detected by address_sanitizer at cJSON.c:787 (exit code 1)
- patched: no fault; exit code 1
- correlation with the diff: `LIKELY` (confidence `medium`)
  - affected: `cJSON.c` in `parse_object()`
  - the relationship is indirect, through a caller
  - frame #1: the fault is inside parse_object() (lines 1607-1717), which the patch modified, but not on a changed line
  - the relationship is indirect: the fault surfaced in parse_string at cJSON.c:787, which is reached from the changed code
  - frame #0: cJSON.c was modified by the patch, but the fault is outside every changed function
- note: absence of the fault for this input does not prove the defect class was eliminated everywhere
- evidence: `exec/security_object_truncated_after_comma_alt/base.sanitized/stderr.bin`, `exec/security_object_truncated_after_comma_alt/base.sanitized/stdout.bin`, `exec/security_object_truncated_after_comma_alt/patched.sanitized/stderr.bin`, `exec/security_object_truncated_after_comma_alt/patched.sanitized/stdout.bin`

### `INCOMPLETE_FIX` — security_nested_object_truncated (sanitized)

HEAP_BUFFER_OVERFLOW still reproduces on the patched build for this input

- confidence: `high`
- base: HEAP_BUFFER_OVERFLOW detected by address_sanitizer at cJSON.c:787 (exit code 1)
- patched: HEAP_BUFFER_OVERFLOW detected by address_sanitizer at cJSON.c:787 (exit code 1)
- correlation with the diff: `LIKELY` (confidence `medium`)
  - affected: `cJSON.c` in `parse_object()`
  - the relationship is indirect, through a caller
  - frame #1: the fault is inside parse_object() (lines 1607-1724), which the patch modified, but not on a changed line
  - the relationship is indirect: the fault surfaced in parse_string at cJSON.c:787, which is reached from the changed code
  - frame #0: cJSON.c was modified by the patch, but the fault is outside every changed function
- note: the input that triggered the original fault still triggers a fault after the patch
- evidence: `exec/security_nested_object_truncated/base.sanitized/stderr.bin`, `exec/security_nested_object_truncated/base.sanitized/stdout.bin`, `exec/security_nested_object_truncated/patched.sanitized/stderr.bin`, `exec/security_nested_object_truncated/patched.sanitized/stdout.bin`

## Functional findings

| kind | test | mode | authoritative | summary |
|---|---|---|---|---|
| `FUNCTIONAL_FIX` | security_object_truncated_after_comma | sanitized | no | the patched build now satisfies a specification requirement that the base build violated |
| `FUNCTIONAL_FIX` | security_object_truncated_after_comma_alt | sanitized | no | the patched build now satisfies a specification requirement that the base build violated |
| `PRE_EXISTING_DEFECT` | security_nested_object_truncated | sanitized | no | both builds violate the specification for this input, identically |

## Release build versus sanitized build

4 case(s) produced a fault only under the sanitized build. The release build gave no indication of a problem for these inputs:

| test | version | release | sanitized |
|---|---|---|---|
| security_object_truncated_after_comma | base | clean (exit 1) | HEAP_BUFFER_OVERFLOW |
| security_object_truncated_after_comma_alt | base | clean (exit 1) | HEAP_BUFFER_OVERFLOW |
| security_nested_object_truncated | base | clean (exit 1) | HEAP_BUFFER_OVERFLOW |
| security_nested_object_truncated | patched | clean (exit 1) | HEAP_BUFFER_OVERFLOW |

## Reproduction

| finding | replays | matched | stability | bundle |
|---|---|---|---|---|
| `sec/security_object_truncated_after_comma/sanitized` | 3 | 3 | `stable` | `bundles/sec__security_object_truncated_after_comma__sanitized` |

## Minimization

| finding | original | minimized | reduction | probes | stopped because |
|---|---|---|---|---|---|
| `sec/security_object_truncated_after_comma/sanitized` | 7 B | 6 B | 14.29% | 13 | no further reduction possible |

## Generated regression tests

- `regression_security_object_truncated_after_comma_70b71985` (6 B) from finding `sec/security_object_truncated_after_comma/sanitized` → `regression/regression_security_object_truncated_after_comma_70b71985/testcase.yaml`

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
| full_matrix_executed | pass | 96/96 executions completed |
| base_fault_reproduced | pass | a fault was observed on the base build |
| findings_reproducible | pass | every confirmed finding replayed consistently |
| correlation_attempted | pass | every security finding was correlated against the diff |
| hardening_analyzed | pass | binary protections compared between both release builds |
| functional_oracle_available | pass | 24 test case(s) carry an oracle |
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
