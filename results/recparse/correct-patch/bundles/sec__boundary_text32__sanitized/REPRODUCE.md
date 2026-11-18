# Reproducing sec/boundary_text32/sanitized

Everything needed to observe this fault again is in this directory.

## What was observed

    STACK_BUFFER_OVERFLOW detected by address_sanitizer
    at src/record.c:22

Replayed 3 times during the run; result: stable.

## Exact version

    repository   /tmp/claude-1000/-home-alireza-Desktop-security-project/bdf060c1-e9f7-47a3-8a11-95ad23ab9263/scratchpad/pv/targets/recparse/repo
    revision     base
    commit       9d8c9fe9666bfb20611f3ea388bdac598b3bdda0
    version      base

## Exact binary

    path         /tmp/patch-validator-20261118T125435Z-pfun0_j7/build/base.sanitized/recparse
    sha256       34df5c1b0ccc87c8bc9eed0a762422a7c7a9469016a739619fc7e5fba6615054
    compiler     gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
    cflags       -O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined
    ldflags      -fsanitize=address,undefined

If the binary is gone, rebuild it from the commit above with:

    cmake -S /tmp/patch-validator-20261118T125435Z-pfun0_j7/src/base -B /tmp/patch-validator-20261118T125435Z-pfun0_j7/build/base.sanitized -DCMAKE_BUILD_TYPE=None -DCMAKE_C_COMPILER=gcc -DCMAKE_C_FLAGS=-O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined -DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined
    cmake --build /tmp/patch-validator-20261118T125435Z-pfun0_j7/build/base.sanitized --parallel 12

## Replay

    patch-validator reproduce <path to this directory>

The command rebuilds nothing. It checks the binary against the recorded
SHA256, feeds it `input.bin` through the recorded input method
(file) under the same sandbox and resource limits,
and reports whether the same crash signature appears.

## Input

    original     input.bin (40 bytes, sha256 81a3c2ba1545711d5b6088e264f77a1bdbf04546c87ac6c57f8aec735d499ab4)
