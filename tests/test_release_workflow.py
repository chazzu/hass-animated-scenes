"""Tests for the release version update script."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest


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


def test_release_version_cli_updates_requested_paths(
    tmp_path: Path, release_version_script: ModuleType
) -> None:
    """Honor the explicit paths passed by the release workflow."""
    manifest_path = tmp_path / "manifest.json"
    const_path = tmp_path / "const.py"
    manifest_path.write_text(json.dumps({"domain": "animated_scenes", "version": "1.0.0"}))
    const_path.write_text('VERSION = "1.0.0"\n')

    exit_code = release_version_script.main(
        [
            "--tag-name",
            "2.0.0",
            "--manifest-path",
            str(manifest_path),
            "--const-path",
            str(const_path),
        ]
    )

    assert exit_code == 0
    assert json.loads(manifest_path.read_text())["version"] == "2.0.0"
    assert const_path.read_text() == 'VERSION = "2.0.0"\n'
