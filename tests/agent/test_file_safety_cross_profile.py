"""Regression tests for the Hermes cross-profile guard early-return path.

These tests target ``agent.file_safety._resolve_active_profile_name`` and
``agent.file_safety.classify_cross_profile_target`` directly, because the
cross-profile logic is a soft guard whose behavior must remain stable under
path-normalization edge cases.

Reviewer feedback (teknium1, PR #48784) asked for a concrete fixture proving
that the same-profile early return cannot be bypassed by symlinks or relative
paths, while a genuine other-profile target is still guarded.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import agent.file_safety as file_safety


@pytest.fixture
def hermes_root(tmp_path: Path) -> Path:
    """Create an isolated Hermes hierarchy: root with two profiles."""
    root = tmp_path / "hermes_root"
    (root / "skills").mkdir(parents=True)
    (root / "cron").mkdir(parents=True)
    profiles = root / "profiles"
    profiles.mkdir(parents=True)

    default_profile = profiles / "default"
    other_profile = profiles / "other"
    for profile in (default_profile, other_profile):
        for area in file_safety.PROFILE_SCOPED_AREAS:
            (profile / area).mkdir(parents=True)

    return root


def _get_target(path: Path) -> dict | None:
    """Evaluate the public guard under controlled path resolution."""
    return file_safety.classify_cross_profile_target(str(path))


class TestCrossProfileGuardEarlyReturn:
    """Verify the same-profile early return still applies after normalization."""

    def test_same_profile_path_is_not_guarded(self, hermes_root: Path) -> None:
        """A path inside the active profile's scoped area returns None."""
        with patch.object(
            file_safety,
            "_hermes_home_path",
            return_value=hermes_root / "profiles" / "default",
        ), patch.object(file_safety, "_hermes_root_path", return_value=hermes_root):
            target = hermes_root / "profiles" / "default" / "skills" / "foo"
            assert _get_target(target) is None

    def test_relative_path_resolving_to_active_profile_hits_early_return(
        self, hermes_root: Path, tmp_path: Path
    ) -> None:
        """A relative path that resolves into the active profile is in-profile.

        This exercises the concrete relative-path fixture requested by the
        reviewer: a ``../default/skills/...`` reference that, after
        ``Path.resolve()`` , lands inside the active profile's allowed area.
        """
        active_profile = hermes_root / "profiles" / "default"
        other_profile = hermes_root / "profiles" / "other"

        # Work from the sibling profile directory so the relative path is real.
        cwd = other_profile
        rel_path = Path("..") / "default" / "skills" / "bar"

        with patch.object(
            file_safety,
            "_hermes_home_path",
            return_value=active_profile,
        ), patch.object(file_safety, "_hermes_root_path", return_value=hermes_root):
            with patch.object(os, "getcwd", return_value=str(cwd)):
                result = _get_target(rel_path)

        # The relative path resolves to the active profile's skills area, so
        # the early return applies and this must NOT be flagged as cross-profile.
        assert result is None

    def test_symlinked_profile_path_does_not_bypass_guard(
        self, hermes_root: Path, tmp_path: Path
    ) -> None:
        """A symlink whose target is another profile must remain guarded.

        Even though ``Path.resolve()`` follows the symlink, the guard
        identifies the resolved target as belonging to a different profile
        and therefore does not take the same-profile early return.
        """
        active_profile = hermes_root / "profiles" / "default"
        other_profile = hermes_root / "profiles" / "other"
        symlink_dir = tmp_path / "alias"

        # Create a symlink pointing to the other profile's skills directory.
        symlink_dir.symlink_to(other_profile / "skills")

        with patch.object(
            file_safety,
            "_hermes_home_path",
            return_value=active_profile,
        ), patch.object(file_safety, "_hermes_root_path", return_value=hermes_root):
            target = symlink_dir / "baz"
            result = _get_target(target)

        assert result is not None
        assert result["active_profile"] == "default"
        assert result["target_profile"] == "other"
        assert result["area"] == "skills"

    def test_genuine_other_profile_target_is_still_blocked(
        self, hermes_root: Path
    ) -> None:
        """A direct path into another profile remains guarded (paired assertion)."""
        active_profile = hermes_root / "profiles" / "default"
        target = hermes_root / "profiles" / "other" / "cron" / "job"

        with patch.object(
            file_safety,
            "_hermes_home_path",
            return_value=active_profile,
        ), patch.object(file_safety, "_hermes_root_path", return_value=hermes_root):
            result = _get_target(target)

        assert result is not None
        assert result["active_profile"] == "default"
        assert result["target_profile"] == "other"
        assert result["area"] == "cron"
