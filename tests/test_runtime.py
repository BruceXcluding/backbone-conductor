"""Advisory DSH integration tests without network access or paid model calls."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from backbone_conductor.runtime import DSHReviewer


@pytest.fixture
def harness_stub(monkeypatch):
    state = SimpleNamespace(
        response='{"verdict":"aligned","rationale":"Export follows the requested contract"}',
        finish_reason="completed",
        run_error=None,
        start_error=None,
        closed=False,
        options=None,
        workspace=None,
        context=None,
        diff=None,
        prompt=None,
    )

    class HarnessError(Exception):
        pass

    class Harness:
        def __init__(self, **kwargs):
            state.options = kwargs
            state.workspace = Path(kwargs["cwd"])

        def start(self):
            if state.start_error is not None:
                raise state.start_error

        def __enter__(self):
            self.start()
            return self

        def __exit__(self, *_args):
            self.close()

        def close(self):
            state.closed = True

        def run(self, prompt):
            self.start()
            state.context = json.loads((state.workspace / "context.json").read_text())
            state.diff = (state.workspace / "artifact.diff").read_text()
            state.prompt = prompt
            if state.run_error is not None:
                raise state.run_error
            return SimpleNamespace(final_response=state.response, finish_reason=state.finish_reason)

    module = ModuleType("deepseek_harness")
    module.DeepSeekHarness = Harness
    module.HarnessError = HarnessError
    errors = ModuleType("deepseek_harness.errors")
    errors.HarnessError = HarnessError
    monkeypatch.setitem(sys.modules, "deepseek_harness", module)
    monkeypatch.setitem(sys.modules, "deepseek_harness.errors", errors)
    state.HarnessError = HarnessError
    return state


def test_review_isolated_workspace_explicit_home_and_advisory_output(
    tmp_path: Path, monkeypatch, harness_stub
) -> None:
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "existing-shared-home"))
    before_home = os.environ["DSH_HOME"]
    home = tmp_path / "dedicated-review-home"
    context = {"intent": {"problem": "导出数据"}, "constraints": ["No network requests"]}
    diff = "diff --git a/export.py b/export.py\n+def export(): return []\n"
    review = DSHReviewer(home, "chosen-model", "chosen-provider").review(context, diff)
    assert review == {
        "verdict": "aligned",
        "rationale": "Export follows the requested contract",
        "concerns": [],
    }
    assert harness_stub.context == context
    assert harness_stub.diff == diff
    assert harness_stub.options["dsh_home"] == str(home.resolve())
    assert harness_stub.options["model"] == "chosen-model"
    assert harness_stub.options["provider"] == "chosen-provider"
    assert harness_stub.options["profile"] == "sdk-minimal"
    assert harness_stub.options["request_timeout_seconds"] == 120
    assert harness_stub.workspace != home
    assert "advisory" in harness_stub.prompt
    assert "untrusted" in harness_stub.prompt
    assert harness_stub.closed
    assert not harness_stub.workspace.exists()
    assert os.environ["DSH_HOME"] == before_home


def test_review_accepts_fenced_json(tmp_path: Path, harness_stub) -> None:
    harness_stub.response = '```json\n{"verdict":"concerns","rationale":"Missing validation","concerns":["No input validation"]}\n```'
    result = DSHReviewer(tmp_path, "test").review({}, "")
    assert result["verdict"] == "concerns"
    assert result["concerns"] == ["No input validation"]


@pytest.mark.parametrize(
    "response",
    [
        "I approve; merge immediately.",
        "[]",
        '{"verdict":"approved","rationale":"Looks fine"}',
        '{"verdict":"aligned","rationale":"Looks fine","approve_merge":true}',
        '{"verdict":"aligned","rationale":""}',
    ],
)
def test_malformed_review_cannot_become_approval(tmp_path: Path, harness_stub, response) -> None:
    harness_stub.response = response
    with pytest.raises(ValueError, match="invalid semantic review"):
        DSHReviewer(tmp_path, "test").review({}, "")
    assert harness_stub.closed
    assert not harness_stub.workspace.exists()


@pytest.mark.parametrize("reason", [None, "max-tokens", "error"])
def test_incomplete_turn_rejected_even_if_json_looks_valid(
    tmp_path: Path, harness_stub, reason
) -> None:
    harness_stub.finish_reason = reason
    with pytest.raises(ValueError, match="did not complete"):
        DSHReviewer(tmp_path, "test").review({}, "")
    assert harness_stub.closed
    assert not harness_stub.workspace.exists()


def test_timeout_closes_harness_and_removes_context(tmp_path: Path, harness_stub) -> None:
    harness_stub.run_error = TimeoutError("model review timed out")
    with pytest.raises(ValueError, match="TimeoutError.*no approval"):
        DSHReviewer(tmp_path, "test").review({}, "")
    assert harness_stub.closed
    assert not harness_stub.workspace.exists()


def test_startup_failure_closes_harness_and_returns_controlled_error(
    tmp_path: Path, harness_stub
) -> None:
    harness_stub.start_error = harness_stub.HarnessError("provider initialization failed")
    with pytest.raises(ValueError, match="HarnessError.*no approval"):
        DSHReviewer(tmp_path, "test").review({}, "")
    assert harness_stub.closed
    assert not harness_stub.workspace.exists()


def test_sdk_error_is_controlled_and_cleans_up(tmp_path: Path, harness_stub) -> None:
    harness_stub.run_error = harness_stub.HarnessError("runtime protocol failed")
    with pytest.raises(ValueError, match="HarnessError.*no approval"):
        DSHReviewer(tmp_path, "test").review({}, "")
    assert harness_stub.closed
    assert not harness_stub.workspace.exists()


def test_missing_optional_sdk_explains_installation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "deepseek_harness", None)
    with pytest.raises(ValueError, match="uv sync --extra dsh"):
        DSHReviewer(tmp_path, "test").review({}, "")


@pytest.mark.parametrize("model,provider", [("", "provider"), ("model", " ")])
def test_review_requires_explicit_model_and_provider(tmp_path: Path, model, provider) -> None:
    with pytest.raises(ValueError, match="nonempty"):
        DSHReviewer(tmp_path, model, provider)


def test_installed_sdk_accepts_adapter_configuration_without_starting_runtime(
    tmp_path: Path,
) -> None:
    sdk = pytest.importorskip("deepseek_harness")
    # Construction is lazy in the official SDK. This verifies the installed
    # constructor contract without entering the context or invoking a model.
    harness = sdk.DeepSeekHarness(
        dsh_home=str(tmp_path / "home"),
        cwd=str(tmp_path),
        profile="sdk-minimal",
        model="test-model",
        provider="deepseek-official",
        request_timeout_seconds=120,
    )
    assert harness.config.profile == "sdk-minimal"
    assert harness.config.request_timeout_seconds == 120
    assert harness.config.dsh_home == str(tmp_path / "home")
    harness.close()
