"""Configuration loading, oracle matching and input minimization."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import make_case, make_result
from patch_validator.analysis.oracle import OracleEvaluator
from patch_validator.config import load_config
from patch_validator.config.models import MinimizationSpec, OutputMatcher
from patch_validator.errors import ConfigError
from patch_validator.minimize import Minimizer
from patch_validator.util.templating import render, render_argv, unknown_placeholders

MINIMAL = {
    "schema_version": 1,
    "target": {
        "name": "demo",
        "repo_path": "repo",
        "base_revision": "main",
        "patched_revision": "fix",
    },
    "builds": [
        {
            "mode": "release",
            "commands": [["cc", "{cflags}", "-o", "{build_dir}/app", "{source}/a.c"]],
            "binary_path": "{build_dir}/app",
        }
    ],
    "input": {"method": "stdin"},
    "tests": [{"id": "t1", "category": "valid", "input": {"text": "hello"}}],
}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return tmp_path


def write_config(workspace: Path, payload: dict) -> Path:
    path = workspace / "config.yaml"
    path.write_text(yaml.safe_dump(payload))
    return path


class TestConfigLoading:
    def test_a_minimal_configuration_loads(self, workspace):
        config = load_config(write_config(workspace, MINIMAL))
        assert config.target.name == "demo"
        assert config.modes == ("release",)
        assert config.tests[0].read_input() == b"hello"

    def test_defaults_are_applied(self, workspace):
        config = load_config(write_config(workspace, MINIMAL))
        assert config.limits.timeout_s == 10.0
        assert config.sandbox.backend == "bubblewrap"
        assert config.reproduction.replays == 3

    def test_a_missing_file_is_a_configuration_error(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nope.yaml")

    def test_an_unknown_key_is_rejected(self, workspace):
        payload = {**MINIMAL, "surprise": 1}
        with pytest.raises(ConfigError, match="schema violation"):
            load_config(write_config(workspace, payload))

    def test_a_release_build_is_required(self, workspace):
        payload = {**MINIMAL}
        payload["builds"] = [{**MINIMAL["builds"][0], "mode": "sanitized"}]
        with pytest.raises(ConfigError, match="'release' build is required"):
            load_config(write_config(workspace, payload))

    def test_a_non_git_repository_is_rejected(self, tmp_path):
        payload = {**MINIMAL}
        (tmp_path / "repo").mkdir()
        with pytest.raises(ConfigError, match="not a git repository"):
            load_config(write_config(tmp_path, payload))

    def test_duplicate_test_ids_are_rejected(self, workspace):
        payload = {**MINIMAL, "tests": [MINIMAL["tests"][0], MINIMAL["tests"][0]]}
        with pytest.raises(ConfigError, match="duplicate test id"):
            load_config(write_config(workspace, payload))

    def test_an_unknown_placeholder_is_caught_before_anything_runs(self, workspace):
        payload = {**MINIMAL}
        payload["builds"] = [
            {**MINIMAL["builds"][0], "binary_path": "{nonsense}/app"}
        ]
        with pytest.raises(ConfigError, match="unknown placeholder"):
            load_config(write_config(workspace, payload))

    def test_the_file_input_method_requires_its_placeholder(self, workspace):
        payload = {**MINIMAL, "input": {"method": "file", "argv": ["--no-placeholder"]}}
        with pytest.raises(ConfigError, match=r"\{input_file\}"):
            load_config(write_config(workspace, payload))

    def test_the_unisolated_backend_requires_acknowledgement(self, workspace):
        payload = {**MINIMAL, "sandbox": {"backend": "subprocess"}}
        with pytest.raises(ConfigError, match="no isolation"):
            load_config(write_config(workspace, payload))

    def test_fewer_than_three_replays_is_rejected(self, workspace):
        payload = {**MINIMAL, "reproduction": {"replays": 2}}
        with pytest.raises(ConfigError, match="schema violation"):
            load_config(write_config(workspace, payload))

    def test_base64_input(self, workspace):
        payload = {
            **MINIMAL,
            "tests": [{"id": "b", "category": "valid", "input": {"base64": "aGk="}}],
        }
        assert load_config(write_config(workspace, payload)).tests[0].read_input() == b"hi"


class TestTemplating:
    def test_known_placeholders_are_replaced(self):
        assert render("{a}/x", {"a": "/tmp"}) == "/tmp/x"

    def test_unknown_placeholders_are_left_alone(self):
        # Compiler flags contain braces; silently reformatting them would be
        # worse than leaving them untouched.
        assert render("-Wl,--defsym={sym}=1", {}) == "-Wl,--defsym={sym}=1"

    def test_unknown_placeholders_are_reportable(self):
        assert unknown_placeholders("{a} {b}", ["a"]) == ["b"]

    def test_a_string_command_is_split_before_substitution(self):
        argv = render_argv("cc -o {out} {src}", {"out": "a b", "src": "x.c"})
        assert argv == ["cc", "-o", "a b", "x.c"]

    def test_empty_arguments_are_dropped(self):
        assert render_argv(["cc", "{ldflags}", "x.c"], {"ldflags": ""}) == ["cc", "x.c"]


class TestOracle:
    def test_exact_match(self):
        case = make_case(stdout=OutputMatcher(match="exact", value="ok\n"))
        verdict = OracleEvaluator().evaluate(case, make_result(stdout=b"ok\n"))
        assert verdict.matched

    def test_exact_mismatch_reports_both_sides(self):
        case = make_case(stdout=OutputMatcher(match="exact", value="ok\n"))
        verdict = OracleEvaluator().evaluate(case, make_result(stdout=b"nope\n"))
        assert not verdict.matched
        failure = verdict.failures()[0]
        assert "ok" in failure.expected and "nope" in failure.observed

    def test_contains_and_regex(self):
        case = make_case(stderr=OutputMatcher(match="contains", value="too long"))
        assert OracleEvaluator().evaluate(
            case, make_result(stderr=b"error: text record too long (40)\n")
        ).matched

        case = make_case(stdout=OutputMatcher(match="regex", value=r"^records: \d+$"))
        assert OracleEvaluator().evaluate(case, make_result(stdout=b"records: 3")).matched

    def test_absent_requires_empty_output(self):
        case = make_case(stderr=OutputMatcher(match="absent"))
        assert OracleEvaluator().evaluate(case, make_result()).matched
        assert not OracleEvaluator().evaluate(case, make_result(stderr=b"x")).matched

    def test_a_timeout_fails_an_exit_code_expectation(self):
        case = make_case(exit_code=0)
        verdict = OracleEvaluator().evaluate(
            case, make_result(exit_code=None, timed_out=True)
        )
        assert not verdict.matched
        assert "within" in verdict.failures()[0].observed

    def test_no_oracle_is_not_applicable_rather_than_a_pass(self):
        verdict = OracleEvaluator().evaluate(make_case(with_oracle=False), make_result())
        assert verdict.verdict == "NOT_APPLICABLE"
        assert not verdict.applicable


class TestMinimizer:
    @pytest.fixture
    def minimizer(self) -> Minimizer:
        return Minimizer(MinimizationSpec(max_iterations=5000, budget_seconds=30))

    def test_it_reduces_to_the_relevant_bytes(self, minimizer):
        data = bytes(range(256)) * 4
        result = minimizer.minimize(
            data,
            lambda candidate: b"\x41\x42\x43" in candidate,
            finding_id="f",
            predicate_description="contains ABC",
        )
        assert result.minimized == b"ABC"
        assert result.reduction_percent > 99

    def test_it_never_returns_something_the_predicate_rejects(self, minimizer):
        result = minimizer.minimize(
            b"abcdef",
            lambda candidate: candidate == b"abcdef",
            finding_id="f",
            predicate_description="identity",
        )
        assert result.minimized == b"abcdef"
        assert result.reduction_percent == 0.0

    def test_the_iteration_budget_is_honoured(self):
        calls = 0

        def predicate(candidate: bytes) -> bool:
            nonlocal calls
            calls += 1
            return b"\xff" in candidate

        minimizer = Minimizer(MinimizationSpec(max_iterations=5, budget_seconds=60))
        minimizer.minimize(
            bytes(400) + b"\xff" + bytes(400),
            predicate,
            finding_id="f",
            predicate_description="p",
        )
        # The cache can serve repeats, so the cap bounds real executions.
        assert calls <= 6

    def test_repeated_candidates_are_served_from_the_cache(self, minimizer):
        seen: list[bytes] = []

        def predicate(candidate: bytes) -> bool:
            seen.append(candidate)
            return b"\x7f" in candidate

        result = minimizer.minimize(
            bytes(64) + b"\x7f" + bytes(64),
            predicate,
            finding_id="f",
            predicate_description="p",
        )
        assert len(seen) == len(set(seen))
        assert any(attempt.cached for attempt in result.attempts) or result.iterations

    def test_the_reduction_is_reported_honestly(self, minimizer):
        result = minimizer.minimize(
            b"0123456789",
            lambda candidate: b"5" in candidate,
            finding_id="f",
            predicate_description="p",
        )
        assert result.original_size == 10
        assert result.minimized_size == len(result.minimized)
        expected = round(100 * (10 - result.minimized_size) / 10, 2)
        assert result.reduction_percent == expected


class TestFlagExpansion:
    """Only flag placeholders expand into several arguments."""

    VALUES = {"cflags": "-O2 -g -fsanitize=address", "out": "a path", "ldflags": ""}

    def test_a_flag_placeholder_becomes_several_arguments(self):
        from patch_validator.util.templating import FLAG_PLACEHOLDERS

        assert render_argv(
            ["gcc", "{cflags}", "x.c"], self.VALUES, splittable=FLAG_PLACEHOLDERS
        ) == ["gcc", "-O2", "-g", "-fsanitize=address", "x.c"]

    def test_a_path_with_spaces_stays_one_argument(self):
        from patch_validator.util.templating import FLAG_PLACEHOLDERS

        assert render_argv(
            ["cc", "-o", "{out}"], self.VALUES, splittable=FLAG_PLACEHOLDERS
        ) == ["cc", "-o", "a path"]

    def test_an_embedded_flag_placeholder_is_not_split(self):
        from patch_validator.util.templating import FLAG_PLACEHOLDERS

        assert render_argv(
            ["cmake", "-DCMAKE_C_FLAGS={cflags}"],
            self.VALUES,
            splittable=FLAG_PLACEHOLDERS,
        ) == ["cmake", "-DCMAKE_C_FLAGS=-O2 -g -fsanitize=address"]
