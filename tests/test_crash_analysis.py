"""Crash classification: error types, mechanisms, and the boundaries.

The boundaries matter as much as the classification itself.  A timeout must
never become a memory error, a non-zero exit must never become a crash, and a
resource limit must stay outside the security axis.
"""

from __future__ import annotations

import signal

import pytest

from conftest import (
    ASAN_STACK_OVERFLOW,
    ASAN_USE_AFTER_FREE,
    FORTIFY_ABORT,
    STACK_SMASH,
    UBSAN_OVERFLOW,
    analyze,
    make_result,
)


class TestSanitizerDetection:
    def test_address_sanitizer_stack_overflow(self):
        crash = analyze(
            make_result(exit_code=1, stderr=ASAN_STACK_OVERFLOW.encode())
        )
        assert crash.outcome == "security_event"
        assert crash.error_type == "STACK_BUFFER_OVERFLOW"
        assert crash.detection_mechanism == "address_sanitizer"
        assert crash.confidence == "high"
        assert crash.fault_address == "0x76c677f00040"

    def test_use_after_free(self):
        crash = analyze(make_result(exit_code=1, stderr=ASAN_USE_AFTER_FREE.encode()))
        assert crash.error_type == "USE_AFTER_FREE"

    def test_undefined_behaviour(self):
        crash = analyze(make_result(exit_code=0, stderr=UBSAN_OVERFLOW.encode()))
        assert crash.outcome == "security_event"
        assert crash.error_type == "INTEGER_OVERFLOW"
        assert crash.detection_mechanism == "undefined_behavior_sanitizer"

    def test_ubsan_synthesises_a_frame_from_its_own_location(self):
        crash = analyze(make_result(stderr=UBSAN_OVERFLOW.encode()))
        assert crash.frames
        assert crash.frames[0].file.endswith("app.c")
        assert crash.frames[0].line == 12

    def test_unmapped_sanitizer_category_is_reported_verbatim(self):
        text = "==1==ERROR: AddressSanitizer: some-future-check on address 0x1\n"
        crash = analyze(make_result(stderr=text.encode()))
        assert crash.error_type == "ASAN_SOME_FUTURE_CHECK"
        assert any("unmapped" in note for note in crash.notes)


class TestLibcDiagnostics:
    def test_fortify_is_attributed_to_fortify_not_to_the_signal(self):
        crash = analyze(
            make_result(
                exit_code=134,
                signal=signal.SIGABRT,
                signal_inferred=True,
                stderr=FORTIFY_ABORT.encode(),
            )
        )
        assert crash.error_type == "BUFFER_OVERFLOW"
        assert crash.detection_mechanism == "fortify_source"

    def test_stack_protector_is_distinguished_from_fortify(self):
        crash = analyze(
            make_result(signal=signal.SIGABRT, stderr=STACK_SMASH.encode())
        )
        assert crash.error_type == "STACK_BUFFER_OVERFLOW"
        assert crash.detection_mechanism == "stack_protector"

    @pytest.mark.parametrize(
        ("message", "error_type"),
        [
            ("free(): invalid pointer", "INVALID_FREE"),
            ("double free or corruption (out)", "DOUBLE_FREE"),
            ("malloc(): corrupted top size", "HEAP_CORRUPTION"),
        ],
    )
    def test_glibc_malloc_checks(self, message, error_type):
        crash = analyze(
            make_result(signal=signal.SIGABRT, stderr=message.encode())
        )
        assert crash.error_type == error_type
        assert crash.detection_mechanism == "glibc_malloc_check"


class TestBoundaries:
    """The rules that keep the security axis honest."""

    def test_nonzero_exit_alone_is_not_a_crash(self):
        crash = analyze(make_result(exit_code=2, stderr=b"error: too long\n"))
        assert crash.outcome == "clean"
        assert crash.error_type == "NONE"

    def test_timeout_is_not_a_security_event(self):
        crash = analyze(make_result(exit_code=None, signal=9, timed_out=True))
        assert crash.outcome == "timeout"
        assert not crash.is_security_event

    def test_a_timeout_wins_over_a_partial_sanitizer_report(self):
        # A run killed mid-report must not be read as a confirmed memory error.
        crash = analyze(
            make_result(timed_out=True, stderr=ASAN_STACK_OVERFLOW.encode())
        )
        assert crash.outcome == "timeout"
        assert not crash.is_security_event

    @pytest.mark.parametrize(
        ("signal_number", "kind"),
        [(signal.SIGXCPU, "CPU_TIME"), (signal.SIGXFSZ, "FILE_SIZE")],
    )
    def test_resource_signals_are_not_security_events(self, signal_number, kind):
        crash = analyze(make_result(exit_code=None, signal=signal_number))
        assert crash.outcome == "resource_limit"
        assert crash.error_type == f"RESOURCE_LIMIT_{kind}"
        assert not crash.is_security_event

    def test_sigkill_without_a_diagnostic_states_the_cause_is_unknown(self):
        crash = analyze(make_result(exit_code=None, signal=signal.SIGKILL))
        assert crash.outcome == "resource_limit"
        assert any("not established" in note for note in crash.notes)

    def test_segfault_without_a_sanitizer_does_not_claim_a_class(self):
        crash = analyze(make_result(exit_code=None, signal=signal.SIGSEGV))
        assert crash.error_type == "SEGMENTATION_FAULT"
        assert crash.detection_mechanism == "os_signal"
        assert any("not determined" in note for note in crash.notes)

    def test_an_inferred_signal_lowers_confidence_and_says_so(self):
        crash = analyze(
            make_result(exit_code=139, signal=signal.SIGSEGV, signal_inferred=True)
        )
        assert crash.confidence == "medium"
        assert any("128+N" in note for note in crash.notes)


class TestSignatures:
    def test_signature_is_stable_across_identical_observations(self):
        first = analyze(make_result(stderr=ASAN_STACK_OVERFLOW.encode()))
        second = analyze(make_result(stderr=ASAN_STACK_OVERFLOW.encode()))
        assert first.signature == second.signature
        assert first.signature_quality == "symbolized"

    def test_line_change_alters_the_precise_signature_only(self):
        shifted = ASAN_STACK_OVERFLOW.replace("record.c:22", "record.c:28")
        original = analyze(make_result(stderr=ASAN_STACK_OVERFLOW.encode()))
        moved = analyze(make_result(stderr=shifted.encode()))
        assert original.signature != moved.signature
        # Same function, same call path: a patch that shifts lines must not
        # make the fault look like a different one.
        assert original.location_signature == moved.location_signature

    def test_different_call_path_gives_a_different_location_signature(self):
        other = ASAN_STACK_OVERFLOW.replace("handle_text", "handle_raw")
        assert (
            analyze(make_result(stderr=ASAN_STACK_OVERFLOW.encode())).location_signature
            != analyze(make_result(stderr=other.encode())).location_signature
        )

    def test_different_error_type_gives_a_different_signature(self):
        assert (
            analyze(make_result(stderr=ASAN_STACK_OVERFLOW.encode())).signature
            != analyze(make_result(stderr=ASAN_USE_AFTER_FREE.encode())).signature
        )

    def test_unsymbolized_frames_are_marked_as_such(self):
        text = (
            "==1==ERROR: AddressSanitizer: SEGV on unknown address 0x000000000000\n"
            "    #0 0x4005f0 (/opt/app/target+0x4005f0)\n"
            "    #1 0x400700 (/opt/app/target+0x400700)\n"
        )
        crash = analyze(make_result(stderr=text.encode()))
        assert crash.signature_quality == "unsymbolized"
        assert crash.signature

    def test_null_dereference_is_named_from_the_fault_address(self):
        text = (
            "==1==ERROR: AddressSanitizer: SEGV on unknown address 0x000000000000\n"
            "    #0 0x4005f0 in deref /src/app.c:9\n"
        )
        assert analyze(make_result(stderr=text.encode())).error_type == (
            "NULL_POINTER_DEREFERENCE"
        )

    def test_clean_runs_carry_no_signature(self):
        assert analyze(make_result(exit_code=0)).signature == ""


class TestFrameHandling:
    def test_interceptor_frames_are_excluded_from_target_frames(self):
        crash = analyze(make_result(stderr=ASAN_STACK_OVERFLOW.encode()))
        functions = [frame.function for frame in crash.target_frames]
        assert "__libc_start_call_main" not in functions
        assert functions[0] == "copy_payload"

    def test_paths_are_made_relative_to_the_source_root(self, tmp_path):
        root = tmp_path / "src" / "base"
        (root / "src").mkdir(parents=True)
        (root / "src" / "record.c").write_text("int main(void){return 0;}\n")
        text = ASAN_STACK_OVERFLOW.replace("/work/src/base", str(root))
        crash = analyze(make_result(stderr=text.encode()), roots=(root,))
        assert crash.target_frames[0].file == "src/record.c"
        assert crash.location == "src/record.c:22"
