"""The repository moved from chuanseng-ng/ to hdl-tools/.

GitHub redirects the old URLs, so most stale references still resolve. Two do
not: npm trusted publishing is bound to the repository the release workflow runs
in, and npm checks `package.json` `repository.url` against that repository's
provenance. A stale owner there fails the publish, not a link.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO = "hdl-tools/digital-chip-design-agents"
OLD_REPO = "chuanseng-ng/digital-chip-design-agents"

TEXT_SUFFIXES = {".md", ".json", ".yml", ".yaml", ".sh", ".ps1", ".mjs", ".js", ".py", ".toml"}
# The changelog records history, including the old name; this file names it to look for it.
SKIP = {"CHANGELOG.md", Path(__file__).name}
SKIP_DIRS = {".git", "node_modules", "__pycache__"}


def _tracked_text_files():
    for path in REPO_ROOT.rglob("*"):
        if path.suffix not in TEXT_SUFFIXES or path.name in SKIP or not path.is_file():
            continue
        if SKIP_DIRS.intersection(path.relative_to(REPO_ROOT).parts):
            continue
        yield path


def test_package_json_points_at_the_current_repository():
    pkg = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    assert REPO in pkg["repository"]["url"], pkg["repository"]
    assert REPO in pkg["homepage"]
    assert REPO in pkg["bugs"]["url"]


def test_no_file_names_the_old_repository():
    stale = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _tracked_text_files()
        if OLD_REPO in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not stale, f"still name {OLD_REPO}: {stale}"
