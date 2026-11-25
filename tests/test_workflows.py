"""Security and release-order contracts for GitHub Actions workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
RELEASE_MUTATION_STEP = "Commit Version and Update Release Refs"


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


@pytest.mark.parametrize(
    ("job_name", "persisted"),
    [("tests", False), ("publish-coverage-data", True)],
)
def test_only_coverage_publication_persists_credentials(job_name: str, persisted: bool) -> None:
    """Persist checkout credentials only for the trusted coverage push job.

    Args:
        job_name: Job id inside the coverage workflow.
        persisted: Whether the job's checkout should keep credentials.

    """
    job = _job("pytest_coverage.yml", job_name)

    assert _step(job, "Checkout Repository")["with"]["persist-credentials"] is persisted


def test_job_running_pr_code_has_no_write_token() -> None:
    """Keep write access away from pull request code."""
    assert _write_scopes(_job("pytest_coverage.yml", "tests")) == set()


def test_coverage_publication_is_isolated_to_trusted_pushes() -> None:
    """Grant content write only to a push job that runs no repository commands."""
    job = _job("pytest_coverage.yml", "publish-coverage-data")

    assert job["if"] == "github.event_name == 'push'"
    assert job["needs"] == "tests"
    assert _write_scopes(job) == {"contents"}
    assert not [step for step in job["steps"] if "run" in step]


def test_coverage_publication_serializes_without_cancelling() -> None:
    """Queue default-branch coverage publishes in order and leave the tests job unqueued."""
    job = _job("pytest_coverage.yml", "publish-coverage-data")

    assert job["concurrency"] == {"group": "coverage-data-publish", "cancel-in-progress": False}
    assert "concurrency" not in _job("pytest_coverage.yml", "tests")


def test_privileged_comment_workflow_never_checks_out_pr_code() -> None:
    """Keep the workflow_run job from executing untrusted pull request content."""
    workflow = yaml.safe_load((WORKFLOWS / "post_coverage_to_pr.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["post_coverage_comment"]

    assert _write_scopes(job) == {"pull-requests"}
    assert not [
        step
        for workflow_job in workflow["jobs"].values()
        for step in workflow_job["steps"]
        if "actions/checkout" in step.get("uses", "")
    ]


def test_coverage_comments_serialize_per_pr_and_queue_all_runs() -> None:
    """Keep each PR's coverage runs ordered without replacing queued work."""
    job = _job("post_coverage_to_pr.yml", "post_coverage_comment")

    assert job["concurrency"] == {
        "group": "coverage-comment-pr-${{ needs.resolve_pull_request.outputs.pr_number }}",
        "queue": "max",
    }
    assert job["needs"] == "resolve_pull_request"


def test_coverage_comment_rechecks_head_inside_serialized_job() -> None:
    """Skip stale workflow runs immediately before considering publication."""
    job = _job("post_coverage_to_pr.yml", "post_coverage_comment")
    eligibility = _step(job, "Check coverage comment eligibility")["with"]["script"]

    assert "pullRequest.head.sha !== workflowRun.head_sha" in eligibility
    assert eligibility.index("pullRequest.head.sha !== workflowRun.head_sha") < eligibility.index(
        "listWorkflowRunArtifacts"
    )


def test_fork_coverage_runs_resolve_only_exact_open_pr_heads() -> None:
    """Match fork runs by repository, branch, and exact commit before queueing."""
    job = _job("post_coverage_to_pr.yml", "resolve_pull_request")
    resolution = _step(job, "Resolve pull request for coverage run")["with"]["script"]

    assert "workflowRun.pull_requests?.[0]?.number" in resolution
    assert "candidate.state === 'open'" in resolution
    assert "candidate.head.sha === workflowRun.head_sha" in resolution
    assert "candidate.head.repo?.full_name === headRepository" in resolution
    assert "candidate.head.ref === workflowRun.head_branch" in resolution


def test_release_checks_out_full_history_at_tag_ref() -> None:
    """Resolve release events to the tag namespace with history for ancestry checks."""
    checkout = _step(_job("release.yml", "update_version_and_create_zip"), "Checkout Repository")

    assert "format('refs/tags/{0}', github.event.release.tag_name)" in checkout["with"]["ref"]
    assert "github.ref" in checkout["with"]["ref"]
    assert checkout["with"]["fetch-depth"] == 0


def test_release_moves_refs_only_for_published_branch_targets() -> None:
    """Skip version commits and retags for edits, drafts, prereleases, and SHAs."""
    step = _step(_job("release.yml", "update_version_and_create_zip"), RELEASE_MUTATION_STEP)
    condition = step["if"]

    assert "github.event.action == 'published'" in condition
    assert "github.event.release.draft == false" in condition
    assert "github.event.release.prerelease == false" in condition
    assert "steps.release-target.outputs.is_branch == 'true'" in condition
    assert step["working-directory"] == "release-payload"
    assert set(step["env"]) == {"TAG_NAME", "BRANCH"}


def test_release_uploads_zip_before_moving_refs() -> None:
    """Publish the HACS asset even if the later version write-back fails."""
    job = _job("release.yml", "update_version_and_create_zip")
    names = [step["name"] for step in job["steps"]]

    assert names.index("Upload Zip to Release") < names.index(RELEASE_MUTATION_STEP)
    assert _step(job, "Upload Zip to Release")["with"]["files"] == "./animated_scenes.zip"
    assert '"$GITHUB_WORKSPACE/animated_scenes.zip"' in _step(job, "Create Zip")["run"]


def test_release_shell_steps_do_not_interpolate_event_data() -> None:
    """Pass release metadata through the environment instead of shell text."""
    job = _job("release.yml", "update_version_and_create_zip")

    assert not [step["name"] for step in job["steps"] if "${{" in step.get("run", "")]
