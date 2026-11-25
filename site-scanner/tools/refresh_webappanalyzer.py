"""Copy a fresh WebAppAnalyzer signature snapshot into vendor/.

The signature files stay under GPL-3.0. This script does not change the matcher.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "vendor" / "webappanalyzer"
REPO = "https://github.com/enthec/webappanalyzer.git"


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/webappanalyzer-refresh")
    if target.exists():
        shutil.rmtree(target)
    subprocess.run(["git", "clone", "--depth", "1", REPO, str(target)], check=True)
    commit = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tech = DEST / "technologies"
    if tech.exists():
        shutil.rmtree(tech)
    shutil.copytree(target / "src" / "technologies", tech)
    shutil.copyfile(target / "src" / "categories.json", DEST / "categories.json")
    shutil.copyfile(target / "LICENSE", DEST / "LICENSE")
    (DEST / "SOURCE_COMMIT").write_text(commit + "\n", encoding="utf-8")
    print("webappanalyzer %s" % commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
