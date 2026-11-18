# Reproducing sec/security_object_truncated_after_comma/sanitized

Everything needed to observe this fault again is in this directory.

## What was observed

    HEAP_BUFFER_OVERFLOW detected by address_sanitizer
    at cJSON.c:787

Replayed 3 times during the run; result: stable.

## Exact version

    repository   /tmp/claude-1000/-home-alireza-Desktop-security-project/bdf060c1-e9f7-47a3-8a11-95ad23ab9263/scratchpad/pv/targets/cjson/repo
    revision     pv-base
    commit       826cd6f842ae7e46ee38bbc097f9a34f2947388d
    version      base

## Exact binary

    path         /tmp/patch-validator-20261118T125516Z-dfqo_13o/build/base.sanitized/cjson_cli
    sha256       11c2a12dff974f5ac7bfaf21931ca29c497358a2bb787091a4fb69c642730016
    compiler     gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
    cflags       -std=c99 -O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined
    ldflags      -fsanitize=address,undefined -lm

If the binary is gone, rebuild it from the commit above with:

    gcc -std=c99 -O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined -I/tmp/patch-validator-20261118T125516Z-dfqo_13o/src/base -o /tmp/patch-validator-20261118T125516Z-dfqo_13o/build/base.sanitized/cjson_cli /tmp/claude-1000/-home-alireza-Desktop-security-project/bdf060c1-e9f7-47a3-8a11-95ad23ab9263/scratchpad/pv/targets/cjson/harness/cjson_cli.c /tmp/patch-validator-20261118T125516Z-dfqo_13o/src/base/cJSON.c -fsanitize=address,undefined -lm

## Replay

    patch-validator reproduce <path to this directory>

The command rebuilds nothing. It checks the binary against the recorded
SHA256, feeds it `minimized.bin` through the recorded input method
(file) under the same sandbox and resource limits,
and reports whether the same crash signature appears.

## Input

    original     input.bin (7 bytes, sha256 880e9c79fdec2261160585730499727d63cd811a6d0792dcc04b46bce307d259)
    minimized    minimized.bin (6 bytes, sha256 70b719852671c82ae4508bc308c00a864dbbb9f38aea282e8130d61981b6acc1)
