"""Assert a built wheel contains the compiled admin UI (ADR-0009). Usage: check_wheel.py WHEEL..."""

from __future__ import annotations

import re
import sys
import zipfile

INDEX = "oneadmin/static/index.html"


def check(path: str) -> list[str]:
    wheel = zipfile.ZipFile(path)
    names = set(wheel.namelist())
    errors = []
    if INDEX not in names:
        errors.append(f"missing {INDEX}")
    else:
        # Every script/stylesheet the page loads must ship in the wheel (relative to static/).
        page = wheel.read(INDEX).decode()
        refs = re.findall(r'(?:src|href)="\./(assets/[^"]+)"', page)
        if not any(r.endswith(".js") for r in refs):
            errors.append("index.html references no JS bundle (placeholder build?)")
        errors += [
            f"index.html references missing {r}"
            for r in refs
            if f"oneadmin/static/{r}" not in names
        ]
    if not any(n.startswith("oneadmin/auth/migrations/versions/0001") for n in names):
        errors.append("missing packaged migrations (oneadmin/auth/migrations/versions)")
    if "oneadmin/auth/migrations/env.py" not in names:
        errors.append("missing oneadmin/auth/migrations/env.py")
    if "oneadmin/py.typed" not in names:
        errors.append("missing oneadmin/py.typed")
    if any("node_modules" in n for n in names):
        errors.append("wheel contains node_modules")
    return errors


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_wheel.py WHEEL...", file=sys.stderr)
        return 2
    failed = False
    for wheel in argv:
        errors = check(wheel)
        for e in errors:
            print(f"{wheel}: {e}", file=sys.stderr)
        failed |= bool(errors)
        if not errors:
            print(f"{wheel}: ok")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
