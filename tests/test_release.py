from __future__ import annotations

import pytest

from scripts.verify_release import release_tag


def test_alpha_package_version_maps_to_release_tag() -> None:
    assert release_tag("0.1.0a1") == "v0.1.0-alpha.1"


def test_release_tag_rejects_non_alpha_version() -> None:
    with pytest.raises(ValueError, match="alpha versions only"):
        release_tag("0.1.0")
