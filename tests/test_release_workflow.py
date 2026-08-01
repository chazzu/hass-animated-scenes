"""Release-workflow tests that protect versioning and tag-update behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/release.yml"
WORKFLOW_SCRIPT_PATH = "release-tooling/.github/scripts/update_release_version.py"


def _workflow_text() -> str:
    """Return the checked-in release workflow text."""
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _step_block(workflow: str, step_name: str) -> str:
    """Extract a named workflow step from raw workflow text.

    Args:
        workflow: Complete workflow text.
        step_name: Name of the step to extract.

    Returns:
        The text block for the requested step.
    """
    step_label = f"- name: {step_name}"
    assert step_label in workflow, f"{step_name} step is missing"
    step_index = workflow.index(step_label)
    next_step_index = workflow.find("\n      - name:", step_index + len(step_label))
    return workflow[step_index:] if next_step_index == -1 else workflow[step_index:next_step_index]


def test_edited_release_checkout_uses_release_tag() -> None:
    """Edited release runs continue from the published release tag."""
    workflow = _workflow_text()

    assert (
        "github.event_name == 'release' && github.event.release.tag_name || github.ref" in workflow
    )


def test_release_workflow_queues_same_tag_mutations() -> None:
    """Do not interrupt a same-tag release while it mutates remote state."""
    workflow = _workflow_text()

    assert "concurrency:" in workflow
    assert "${{ github.workflow }}-${{ github.event.release.tag_name || github.ref }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "cancel-in-progress: true" not in workflow


def test_published_release_checkout_uses_release_tag() -> None:
    """Published release builds check out the tag created for that release."""
    checkout_block = _step_block(_workflow_text(), "Checkout Repository")

    assert "github.event.release.tag_name" in checkout_block
    assert "github.event.release.target_commitish" not in checkout_block
    assert "path: release-payload" in checkout_block


def test_release_target_branch_is_resolved_as_an_exact_remote_head() -> None:
    """A branch target enables commit and retag steps only after validation."""
    workflow = _workflow_text()
    resolve_block = _step_block(workflow, "Resolve Release Target Branch")
    commit_block = _step_block(workflow, "Commit & Push Version Changes")
    retag_block = _step_block(workflow, "Update Release with Version Changes Commit")

    assert "TARGET_COMMITISH: ${{ github.event.release.target_commitish }}" in resolve_block
    assert 'git check-ref-format --branch "$TARGET_COMMITISH"' in resolve_block
    assert '"refs/heads/$TARGET_COMMITISH"' in resolve_block
    assert "git ls-remote --exit-code --heads origin" in resolve_block
    assert "printf 'is_branch=true\\nbranch=%s\\n' \"$TARGET_COMMITISH\"" in resolve_block
    assert "elif [[ $? -ne 2 ]]" in resolve_block
    assert "Unable to resolve the release target against remote branches" in resolve_block
    assert "branch: ${{ steps.release-target.outputs.branch }}" in commit_block
    assert "steps.release-target.outputs.is_branch == 'true'" in commit_block
    assert "steps.release-target.outputs.is_branch == 'true'" in retag_block


def test_non_branch_release_target_skips_remote_mutations() -> None:
    """A SHA or other non-branch target is packaged without moving remote refs."""
    workflow = _workflow_text()
    resolve_block = _step_block(workflow, "Resolve Release Target Branch")
    commit_block = _step_block(workflow, "Commit & Push Version Changes")
    retag_block = _step_block(workflow, "Update Release with Version Changes Commit")
    zip_block = _step_block(workflow, "Create Zip")
    upload_block = _step_block(workflow, "Upload Zip to Release")

    assert "printf 'is_branch=false\\n' >> \"$GITHUB_OUTPUT\"" in resolve_block
    assert "github.event.release.target_commitish" not in commit_block
    assert "steps.release-target.outputs.is_branch == 'true'" in commit_block
    assert "steps.release-target.outputs.is_branch == 'true'" in retag_block
    assert "steps.release-target.outputs.is_branch" not in zip_block
    assert "steps.release-target.outputs.is_branch" not in upload_block


@pytest.mark.parametrize(
    "step_name",
    [
        "Update Release Version Files",
        "Update Release with Version Changes Commit",
    ],
)
def test_release_shell_steps_use_tag_environment_variable(step_name: str) -> None:
    """Shell steps quote the release tag before moving or pushing it."""
    workflow = _workflow_text()
    step_block = _step_block(workflow, step_name)

    assert "TAG_NAME: ${{ github.event.release.tag_name }}" in step_block
    assert "${{ github.event.release.tag_name }}" not in step_block.split("run: |", 1)[1]

    assert 'git tag -f "$TAG_NAME"' in workflow
    assert 'git push -f origin "$TAG_NAME"' in workflow


def test_release_workflow_runs_checked_in_version_update_script() -> None:
    """Release workflow runs trusted tooling against the tagged payload."""
    workflow = _workflow_text()
    tooling_checkout = _step_block(workflow, "Checkout trusted release tooling")
    step_block = _step_block(workflow, "Update Release Version Files")

    assert "ref: ${{ github.workflow_sha }}" in tooling_checkout
    assert "path: release-tooling" in tooling_checkout
    assert "persist-credentials: false" in tooling_checkout
    assert "sparse-checkout: .github/scripts/update_release_version.py" in tooling_checkout
    assert "sparse-checkout-cone-mode: false" in tooling_checkout
    assert f"python {WORKFLOW_SCRIPT_PATH}" in step_block
    assert '--tag-name "$TAG_NAME"' in step_block
    assert (
        "--manifest-path release-payload/custom_components/animated_scenes/manifest.json"
        in step_block
    )
    assert "--const-path release-payload/custom_components/animated_scenes/const.py" in step_block
    assert "python .github/scripts/update_release_version.py" not in workflow
    assert "python - <<'PY'" not in workflow


@pytest.mark.parametrize(
    ("const_text", "expected_error"),
    [
        ('"""Constants."""\n\nVERSION = "v0.1.0"\nDOMAIN = "animated_scenes"\n', None),
        ('"""Constants."""\n\nDOMAIN = "animated_scenes"\n', "VERSION assignment"),
        (
            '"""Constants."""\n\nVERSION = "v0.1.0"\nVERSION = "v0.2.0"\n',
            "exactly one VERSION assignment",
        ),
    ],
)
def test_release_version_script_updates_manifest_and_const(
    tmp_path: Path,
    release_version_script: ModuleType,
    const_text: str,
    expected_error: str | None,
) -> None:
    """The version update script rewrites files or rejects invalid const metadata."""
    manifest_path = tmp_path / "manifest.json"
    const_path = tmp_path / "const.py"
    manifest_path.write_text(json.dumps({"domain": "animated_scenes", "version": "v0.1.0"}))
    const_path.write_text(const_text)

    if expected_error is not None:
        with pytest.raises(ValueError, match=expected_error):
            release_version_script.update_release_version_files(
                tag_name="v1.2.3",
                manifest_path=manifest_path,
                const_path=const_path,
            )
        return

    release_version_script.update_release_version_files(
        tag_name="v1.2.3",
        manifest_path=manifest_path,
        const_path=const_path,
    )

    assert json.loads(manifest_path.read_text())["version"] == "v1.2.3"
    assert manifest_path.read_text().endswith("\n")
    assert 'VERSION = "v1.2.3"' in const_path.read_text()


def test_edited_release_does_not_force_move_tag() -> None:
    """Edited releases skip version commits and avoid force-moving tags."""
    workflow = _workflow_text()

    guarded_steps = [
        "Commit & Push Version Changes",
        "Update Release with Version Changes Commit",
    ]

    for step_name in guarded_steps:
        step_label = f"- name: {step_name}"
        assert step_label in workflow, f"{step_name} step is missing"
        step_index = workflow.index(step_label)
        assert "github.event.action == 'published'" in workflow[step_index:], (
            f"{step_name} must be guarded to published release events"
        )
        condition_index = workflow.index(
            "github.event.action == 'published'",
            step_index,
        )
        assert condition_index > step_index
