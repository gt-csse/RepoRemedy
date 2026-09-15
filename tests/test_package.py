# noqa: CPY001
"""Check the installed package exposes its distribution version."""

from importlib.metadata import version

import RepoRemedy


def test_distribution_version():
    assert RepoRemedy.__version__ == version("reporemedy")
