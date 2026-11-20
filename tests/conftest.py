"""Shared pytest setup."""

import os

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """On GitHub Actions, turn each test failure into an annotation (shown on the run's page
    and inline on pull requests) so the reason is visible without opening the full log."""
    outcome = yield
    report = outcome.get_result()
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return
    path, line, _ = report.location
    text = report.longreprtext.strip().splitlines()
    detail = "%0A".join(text[-25:]).replace("::", ": :")  # %0A = newline in annotations
    print(
        f"\n::error file=tests/{os.path.basename(path)},line={(line or 0) + 1},"
        f"title={item.name} ({report.when})::{detail}"
    )
