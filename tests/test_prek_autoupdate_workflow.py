"""Contract tests for the reusable prek autoupdate workflow."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github/workflows/prek_autoupdate.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    """Return the checked-in prek autoupdate workflow text."""
    return WORKFLOW_PATH.read_text()


@pytest.mark.parametrize(
    ("expected", "contract"),
    [
        ('cron: "0 2 * * *"', "scheduled execution"),
        ("push:\n    branches:\n      - master", "default-branch push execution"),
        ("workflow_dispatch:", "manual execution"),
        ("contents: write", "repository content updates"),
        ("pull-requests: write", "pull request updates"),
    ],
)
def test_workflow_triggers_and_permissions(
    workflow_text: str, expected: str, contract: str
) -> None:
    """Preserve the workflow triggers and required write permissions."""
    assert expected in workflow_text, contract


def test_workflow_checkout_does_not_persist_credentials(workflow_text: str) -> None:
    """Use a major checkout tag without retaining its Git credentials."""
    assert re.search(r"uses: actions/checkout@v\d+\b", workflow_text)
    assert "persist-credentials: false" in workflow_text


def test_workflow_serializes_same_repository_runs(workflow_text: str) -> None:
    """Queue overlapping runs for the same repository without cancellation."""
    assert "group: prek-autoupdate-${{ github.repository }}" in workflow_text
    assert "cancel-in-progress: false" in workflow_text


def test_workflow_uses_reusable_autoupdate_action_contract(workflow_text: str) -> None:
    """Delegate updates to the selected major action with Friday scheduling."""
    assert "uses: Snuffy2/prek-autoupdate@v2" in workflow_text
    assert 'update-day: "4"' in workflow_text
