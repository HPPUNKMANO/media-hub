"""Guard rail: the organizer must never contain code that deletes or overwrites files."""
import re
from pathlib import Path

FORBIDDEN = re.compile(
    r"os\.remove|os\.unlink|\.unlink\(|rmtree|shutil\.move|os\.rmdir|\.rmdir\(|os\.replace|\.replace\(\s*[A-Za-z_]+\s*\)\s*$"
    r"|send2trash|\.truncate\(|removedirs"
)


def test_no_delete_calls_in_source():
    src = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for py in src.rglob("*.py"):
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if FORBIDDEN.search(code):
                offenders.append(f"{py.name}:{n}: {line.strip()}")
    assert not offenders, "delete/overwrite calls found:\n" + "\n".join(offenders)
