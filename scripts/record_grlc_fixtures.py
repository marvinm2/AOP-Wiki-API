"""Record grlc responses for every AOPWikiQueries query as golden fixtures.

The fixtures pin down what the legacy grlc API returns today, so the compatibility layer can be
checked against it (same head variables, same rows) until grlc is retired.

Usage:
    python scripts/record_grlc_fixtures.py --queries-dir ../AOPWikiQueries
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://aopwiki.api.bigcat-bioinformatics.org/api-git/marvinm2/AOPWikiQueries"
ACCEPTS = {"json": "application/json", "csv": "text/csv"}
VAR_RE = re.compile(r"\?_([A-Za-z0-9]+)_(integer|en|iri|string|number|literal)\b")

# Values for parameters whose decorator default is missing or named differently from the variable.
FALLBACK = {
    ("get-methods-for-multiple-aops", "aopfilter"): "http://identifiers.org/aop/3",
    ("get-pathways-for-chemicals", "Chemfilter"): "rotenone",
    ("get-chemicals-for-ao (id)", "aopfilter"): "341",
}

# Extra parameter sets used by the VHP4Safety tutorial and the AOP-Wiki workshop.
EXTRA = {
    "get-ao-for-mie": [{"MIEfilter": "167"}],
    "get-mie-for-ao": [{"AOfilter": "345"}, {"AOfilter": "459"}],
}


def parse_query(path: Path) -> dict[str, str | None]:
    """Return {parameter name: default value} for one grlc .rq file."""
    text = path.read_text(encoding="utf-8")
    defaults: dict[str, str] = {}
    in_defaults = False
    for line in text.splitlines():
        if not line.startswith("#+"):
            continue
        body = line[2:].strip()
        if body.startswith("defaults:"):
            in_defaults = True
            continue
        if in_defaults and body.startswith("- ") and ":" in body:
            key, value = body[2:].split(":", 1)
            defaults[key.strip().lower()] = value.strip()
        elif not body.startswith("- "):
            in_defaults = False

    name = path.stem
    params: dict[str, str | None] = {}
    for var, _type in VAR_RE.findall(text):
        params[var] = defaults.get(var.lower()) or FALLBACK.get((name, var))
    return params


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def fetch(url: str, accept: str) -> tuple[int, str, bytes, float]:
    request = urllib.request.Request(url, headers={"Accept": accept})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read()
            status = response.status
            ctype = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        ctype = exc.headers.get("Content-Type", "")
    return status, ctype, body, time.perf_counter() - start


def count_rows(fmt: str, body: bytes) -> int | None:
    try:
        if fmt == "json":
            return len(json.loads(body)["results"]["bindings"])
        lines = [line for line in body.decode("utf-8").splitlines() if line.strip()]
        return max(len(lines) - 1, 0)
    except (ValueError, KeyError, UnicodeDecodeError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("tests/fixtures/grlc"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    index = []
    for path in sorted(args.queries_dir.glob("*.rq")):
        name = path.stem
        defaults = parse_query(path)
        param_sets = [{k: v for k, v in defaults.items() if v is not None}]
        param_sets += EXTRA.get(name, [])
        for params in param_sets:
            query_string = urllib.parse.urlencode(params)
            url = f"{BASE}/{urllib.parse.quote(name)}" + (
                f"?{query_string}" if query_string else ""
            )
            label = slug(name) + ("__" + slug(query_string) if query_string else "")
            for fmt, accept in ACCEPTS.items():
                status, ctype, body, elapsed = fetch(url, accept)
                out_file = args.out / f"{label}.{fmt}"
                out_file.write_bytes(body)
                entry = {
                    "query": name,
                    "params": params,
                    "format": fmt,
                    "url": url,
                    "status": status,
                    "content_type": ctype,
                    "rows": count_rows(fmt, body) if status == 200 else None,
                    "seconds": round(elapsed, 3),
                    "file": out_file.name,
                }
                index.append(entry)
                print(f"{status} {elapsed:6.2f}s rows={entry['rows']} {name} {params} {fmt}")

    recorded = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (args.out / "index.json").write_text(
        json.dumps({"recorded_at": recorded, "base": BASE, "entries": index}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
