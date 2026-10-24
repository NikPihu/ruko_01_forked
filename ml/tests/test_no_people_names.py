"""No people's names in code, UI, docs or file names (plan v3, step 0).

Only the team's ownership lists keep them: `.github/CODEOWNERS` and the "Who owns what" / owners
table rows in CLAUDE.md and README.md (a table row naming a top-level folder). Everything else says
the role: the app, the backend, ML, data, the attack runner.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NAMES = re.compile("(?i)" + "|".join(n[::-1] for n in ("jnukin", "usnawid", "teejnam", "peedgaj")))  # reversed, so this file passes
OWNERS_ROW = re.compile(r"^\| .*`(android|backend|console|ml|data)/`")
SKIP_PREFIXES = (".github/CODEOWNERS", "red_team_blue_team/blue_team/playbooks/")   # review records hold analyst names
BINARY = (".parquet", ".png", ".jpg", ".jpeg", ".svg", ".woff2", ".apk", ".jar", ".zip", ".ico", ".webp")


def test_only_the_ownership_lists_name_people():
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split("\n")
    found = []
    for rel in filter(None, files):
        if rel.startswith(SKIP_PREFIXES) or rel.endswith(BINARY):
            continue
        if NAMES.search(rel):
            found.append(f"{rel} (file name)")
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if NAMES.search(line) and not (rel in ("CLAUDE.md", "README.md") and OWNERS_ROW.search(line)):
                found.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not found, "people's names outside the ownership lists:\n" + "\n".join(found)
