# Reproducing sec/vuln_text_long/release

Everything needed to observe this fault again is in this directory.

## What was observed

    BUFFER_OVERFLOW detected by fortify_source
    at an unknown location

Replayed 3 times during the run; result: stable.

## Exact version

    repository   /tmp/claude-1000/-home-alireza-Desktop-security-project/bdf060c1-e9f7-47a3-8a11-95ad23ab9263/scratchpad/pv/targets/recparse/repo
    revision     base
    commit       9d8c9fe9666bfb20611f3ea388bdac598b3bdda0
    version      base

## Exact binary

    path         /tmp/patch-validator-20261118T125435Z-pfun0_j7/build/base.release/recparse
    sha256       2cf24946d6bfbb6733d3713883fbf0121dd91cbf10fc196cb3b1fb636a2123f8
    compiler     gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
    cflags       -O2 -g -fno-omit-frame-pointer
    ldflags      

If the binary is gone, rebuild it from the commit above with:

    cmake -S /tmp/patch-validator-20261118T125435Z-pfun0_j7/src/base -B /tmp/patch-validator-20261118T125435Z-pfun0_j7/build/base.release -DCMAKE_BUILD_TYPE=None -DCMAKE_C_COMPILER=gcc -DCMAKE_C_FLAGS=-O2 -g -fno-omit-frame-pointer -DCMAKE_EXE_LINKER_FLAGS=
    cmake --build /tmp/patch-validator-20261118T125435Z-pfun0_j7/build/base.release --parallel 12

## Replay

    patch-validator reproduce <path to this directory>

The command rebuilds nothing. It checks the binary against the recorded
SHA256, feeds it `minimized.bin` through the recorded input method
(file) under the same sandbox and resource limits,
and reports whether the same crash signature appears.

## Input

    original     input.bin (208 bytes, sha256 e476b45bd6b4c7b5ec56ba249a05de89b09d112988b6e04c8a6490625bb9344b)
    minimized    minimized.bin (73 bytes, sha256 901649ba33b9141d42b5e84b26afb97afc3d4ed3107c8c71bea5835fff97a675)
