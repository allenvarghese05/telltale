"""Re-check every committed agent run offline: the checker at an earlier commit versus the current one.

Usage: python scripts/recheck_checker.py <earlier-commit>   (writes checker_recheck.json, prints the summary)
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from telltale.config import ROOT
from telltale.pipeline.recheck import recheck_all


def load_checker(rev: str):
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git is not on PATH")
    source = subprocess.run(
        [git, "show", f"{rev}:telltale/verify/checker.py"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    path = Path(tempfile.mkdtemp()) / "checker_before.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("checker_before", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    rev = sys.argv[1]
    before = load_checker(rev)
    result = recheck_all(before.check_claim, before.check_verdict)
    result["checker_before"] = rev
    (ROOT / "checker_recheck.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"], indent=2))
    for c in result["changed_claims"]:
        print(f"{c['benchmark']:12} {c['run']:48} {c['before']}->{c['after']}: {c['text']}")


if __name__ == "__main__":
    main()
