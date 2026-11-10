from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def check(root):
    errors = []
    files = [*root.glob("*.md"), *(root/"docs").rglob("*.md")]
    for document in files:
        text = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.S)
        for link in re.findall(r"\]\(([^)]+)\)", text):
            target = urlsplit(link.split()[0].strip("<>"))
            if target.scheme or not target.path:continue
            path = document.parent/unquote(target.path)
            if not path.exists():errors.append(f"{document.relative_to(root)}: {target.path}")
    if errors:raise SystemExit("Broken documentation links:\n"+"\n".join(errors))
    print(f"Checked local links in {len(files)} documentation files")


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1])
