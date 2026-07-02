import os
import re
import sys

FLASK_PATTERNS = {
    "request.args": r"request\.args",
    "request.form": r"request\.form",
    "request.path": r"request\.path",
    "request.values": r"request\.values",
    "current_app": r"current_app",
    "app.config mutation": r"config\[[\"']",
    "before_request": r"before_request",
    "after_request": r"after_request",
    "context_processor": r"context_processor",
    "Flask Blueprint": r"Blueprint",
    "flask import": r"from flask|import flask",
}

TEMPLATE_PATTERNS = {
    "jinja request.args": r"\{\{\s*request\.args",
    "jinja request.form": r"\{\{\s*request\.form",
    "jinja request.path": r"\{\{\s*request\.path",
    "jinja url_for misuse": r"\{\{\s*url_for",
}


REPLACEMENTS = {
    "request.args": "request.query_params",
    "request.form": "await request.form() (FastAPI async)",
    "request.path": "request.url.path",
    "current_app": "request.app or dependency-injected app",
    "app.config mutation": "use app.state or Settings class",
    "before_request": "FastAPI dependency or middleware",
    "after_request": "FastAPI middleware",
    "context_processor": "Jinja global injection via templates.env.globals",
}


def scan_file(filepath, patterns, results, is_template=False):
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            for name, pattern in patterns.items():
                if re.search(pattern, line):
                    results.append({
                        "file": filepath,
                        "line": i,
                        "issue": name,
                        "code": line.strip(),
                        "fix": REPLACEMENTS.get(name, "manual review required"),
                        "type": "template" if is_template else "python"
                    })
    except Exception as e:
        print(f"Error reading {filepath}: {e}")


def scan_directory(root_dir):
    results = []

    for dirpath, _, filenames in os.walk(root_dir):
        for file in filenames:
            filepath = os.path.join(dirpath, file)

            if file.endswith(".py"):
                scan_file(filepath, FLASK_PATTERNS, results)

            elif file.endswith(".html"):
                scan_file(filepath, TEMPLATE_PATTERNS, results, is_template=True)

    return results


def print_report(results):
    print("\n" + "=" * 90)
    print(" FLASK LEGACY LEAK AUDIT REPORT (FASTAPI MIGRATION)")
    print("=" * 90)

    if not results:
        print("\n✅ No Flask leaks detected.")
        return

    grouped = {}
    for r in results:
        grouped.setdefault(r["file"], []).append(r)

    for file, issues in grouped.items():
        print(f"\n📄 {file}")
        print("-" * 90)

        for issue in issues:
            print(f"Line {issue['line']}: {issue['issue']}")
            print(f"  Code: {issue['code']}")
            print(f"  🔧 Fix: {issue['fix']}")
            print()

    print("\n" + "=" * 90)
    print(f"Total issues found: {len(results)}")
    print("=" * 90)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python flask_leak_audit.py <project_root>")
        sys.exit(1)

    root = sys.argv[1]
    results = scan_directory(root)
    print_report(results)