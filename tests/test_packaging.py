"""Tests for Python package metadata."""

from __future__ import annotations

import ast
from pathlib import Path
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
CONST_PATH = REPO_ROOT / "custom_components" / "animated_scenes" / "const.py"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
POST_COVERAGE_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "post_coverage_to_pr.yml"
PYTEST_COVERAGE_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pytest_coverage.yml"
RELEASE_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _const_version() -> str:
    """Read VERSION from const.py without importing the integration package."""
    module = ast.parse(CONST_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError("VERSION constant not found")


def test_project_version_is_dynamic_from_integration_constant() -> None:
    """Keep package metadata version derived from const.py without importing HA."""
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert "version" in pyproject["project"].get("dynamic", [])
    assert "version" not in pyproject["project"]
    assert (
        pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"]
        == "custom_components.animated_scenes.const.VERSION"
    )
    assert _const_version()


def test_package_data_includes_runtime_yaml_and_brand_assets() -> None:
    """Include Home Assistant service descriptions and brand icons in packages."""
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert "*.yaml" in package_data["custom_components.animated_scenes"]
    assert "brand/*.png" in package_data["custom_components.animated_scenes"]


def test_release_workflow_does_not_update_dynamic_package_version() -> None:
    """Keep release automation focused on files that own version data."""
    workflow = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Update Version in pyproject.toml" not in workflow
    assert "./pyproject.toml" not in workflow


def test_post_coverage_workflow_skips_prs_without_comment_artifacts() -> None:
    """Keep the privileged coverage comment workflow aligned with artifact creation."""
    workflow = POST_COVERAGE_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Check coverage comment eligibility" in workflow
    assert "github.rest.pulls.get" in workflow
    assert "github.rest.actions.listWorkflowRunArtifacts" in workflow
    assert "artifact.name === 'python-coverage-comment-action'" in workflow
    assert "hasCommentArtifact &&" in workflow
    assert "labels.includes('dependencies')" in workflow
    assert "pullRequest.user?.type !== 'Bot'" in workflow
    assert "if: steps.coverage_eligibility.outputs.should_post == 'true'" in workflow


def test_pytest_coverage_job_is_read_only_while_running_pr_code() -> None:
    """Keep write-capable tokens out of the job that executes pull request code."""
    workflow = PYTEST_COVERAGE_WORKFLOW_PATH.read_text(encoding="utf-8")
    tests_job, publish_job = workflow.split("\n  publish-coverage-data:", maxsplit=1)

    assert "permissions:\n      contents: read" in tests_job
    assert "pull-requests: read" in tests_job
    assert "contents: write" not in tests_job
    assert "pull-requests: write" not in tests_job
    assert "Install pytest Requirements" in tests_job
    assert "Run pytest with coverage" in tests_job
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in tests_job
    assert "persist-credentials: false" in tests_job

    assert "Install pytest Requirements" not in publish_job
    assert "Run pytest with coverage" not in publish_job


def test_privileged_coverage_publication_is_push_only_and_separate() -> None:
    """Publish default-branch coverage only after the unprivileged tests job."""
    workflow = PYTEST_COVERAGE_WORKFLOW_PATH.read_text(encoding="utf-8")
    tests_job, publish_job = workflow.split("\n  publish-coverage-data:", maxsplit=1)

    assert "if: github.event_name == 'push'" in publish_job
    assert "needs: tests" in publish_job
    assert "permissions:\n      contents: write" in publish_job
    assert workflow.count("contents: write") == 1
    assert "uses: actions/download-artifact@v8" in publish_job
    assert "uses: py-cov-action/python-coverage-comment-action@v3" in publish_job
    assert "persist-credentials: false" in publish_job

    assert "if: github.event_name == 'push'" in tests_job
    assert "path: .coverage" in tests_job
    assert "include-hidden-files: true" in tests_job


def test_pr_coverage_comment_posting_remains_delegated() -> None:
    """Generate PR comment artifacts read-only and post them in workflow_run."""
    coverage_workflow = PYTEST_COVERAGE_WORKFLOW_PATH.read_text(encoding="utf-8")
    post_workflow = POST_COVERAGE_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "github.event_name == 'pull_request'" in coverage_workflow
    assert "name: python-coverage-comment-action" in coverage_workflow
    assert "path: python-coverage-comment-action.txt" in coverage_workflow
    assert "workflow_run:" in post_workflow
    assert "workflows: ['pytest and coverage']" in post_workflow
    assert "pull-requests: write" in post_workflow
    assert "contents: read" in post_workflow
    assert "contents: write" not in post_workflow
    assert "actions: read" in post_workflow
    assert "GITHUB_PR_RUN_ID: ${{ github.event.workflow_run.id }}" in post_workflow
