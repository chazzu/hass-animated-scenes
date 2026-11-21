"""Security and release-order contracts for GitHub Actions workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
RELEASE_MUTATION_STEPS = (
    "Commit & Push Version Changes",
    "Update Release with Version Changes Commit",
)


def _job(workflow: str, job: str) -> dict[str, Any]:
    """Return one parsed workflow job.

    Args:
        workflow: Workflow file name.
        job: Job id inside the workflow.

    Returns:
        The parsed job mapping.

    """
    parsed = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    return parsed["jobs"][job]


def _write_scopes(job: dict[str, Any]) -> set[str]:
    """Return the token scopes a job can write."""
    return {scope for scope, access in job["permissions"].items() if access == "write"}


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a named step from a job."""
    return next(step for step in job["steps"] if step.get("name") == name)


def test_job_running_pr_code_has_no_write_token() -> None:
    """Keep write access and persisted credentials away from pull request code."""
    job = _job("pytest_coverage.yml", "tests")

    assert _write_scopes(job) == set()
    assert _step(job, "Checkout Repository")["with"]["persist-credentials"] is False


def test_coverage_publication_is_isolated_to_trusted_pushes() -> None:
    """Grant content write only to a push job that runs no repository commands."""
    job = _job("pytest_coverage.yml", "publish-coverage-data")

    assert job["if"] == "github.event_name == 'push'"
    assert job["needs"] == "tests"
    assert _write_scopes(job) == {"contents"}
    assert not [step for step in job["steps"] if "run" in step]


def test_privileged_comment_workflow_never_checks_out_pr_code() -> None:
    """Keep the workflow_run job from executing untrusted pull request content."""
    job = _job("post_coverage_to_pr.yml", "test")

    assert _write_scopes(job) == {"pull-requests"}
    assert not [step for step in job["steps"] if "actions/checkout" in step.get("uses", "")]


@pytest.mark.parametrize("step_name", RELEASE_MUTATION_STEPS)
def test_release_moves_refs_only_for_published_branch_targets(step_name: str) -> None:
    """Skip version commits and retags for edits, drafts, prereleases, and SHAs."""
    condition = _step(_job("release.yml", "update_version_and_create_zip"), step_name)["if"]

    assert "github.event.action == 'published'" in condition
    assert "github.event.release.draft == false" in condition
    assert "github.event.release.prerelease == false" in condition
    assert "steps.release-target.outputs.is_branch == 'true'" in condition


def test_release_uploads_zip_before_moving_refs() -> None:
    """Publish the HACS asset even if the later version write-back fails."""
    job = _job("release.yml", "update_version_and_create_zip")
    names = [step["name"] for step in job["steps"]]

    assert names.index("Upload Zip to Release") < min(map(names.index, RELEASE_MUTATION_STEPS))
    assert _step(job, "Upload Zip to Release")["with"]["files"] == "./animated_scenes.zip"
    assert '"$GITHUB_WORKSPACE/animated_scenes.zip"' in _step(job, "Create Zip")["run"]


def test_release_shell_steps_do_not_interpolate_event_data() -> None:
    """Pass release metadata through the environment instead of shell text."""
    job = _job("release.yml", "update_version_and_create_zip")

    assert not [step["name"] for step in job["steps"] if "github.event" in step.get("run", "")]
