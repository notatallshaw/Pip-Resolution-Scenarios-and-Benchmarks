# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "build",
#   "typer",
#   "uv",
# ]
# ///
"""
Build Airflow wheels at a specific commit so scenarios can install them
via file:// URLs rather than git+ URLs.

This exists because Jarek's ResolutionTooDeep reports (in pip issue
#13281) all use locally built wheels via file:// URLs. Pip handles a
direct file:// URL the same way it handles a git+ URL (one pinned
candidate, no version search), but git+ URLs trigger a full clone per
subdirectory, which makes a 30-provider Airflow scenario take 30+
minutes per run.

This script clones once into a persistent cache, builds every
requested wheel, and prints the paths so a scenario can reference them
without re-cloning. Each commit lives under cache/<commit>/wheels/.

Usage:

    uv run build_airflow_wheels.py \\
        --commit 8642105ced79c887ffcddad0997f61323cb03b07 \\
        --subdir . \\
        --subdir airflow-core \\
        --subdir providers/amazon

Subsequent runs with the same commit hit the cache. Pass --force to
rebuild.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import typer

DEFAULT_REPO = "https://github.com/apache/airflow.git"
DEFAULT_CACHE = Path.home() / ".cache" / "pip-resolution-scenarios" / "airflow-wheels"


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    print(f"  $ {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


def ensure_clone(repo: str, commit: str, src: Path) -> None:
    if src.exists():
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=src, text=True
        ).strip()
        if head == commit:
            return
        run(["git", "fetch", "--depth", "1", "origin", commit], cwd=src)
        run(["git", "checkout", "-q", commit], cwd=src)
        return
    src.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--filter=blob:none", "--quiet", repo, str(src)])
    run(["git", "checkout", "-q", commit], cwd=src)


def build_one(src: Path, subdir: str, out_dir: Path) -> Path:
    """Build a single wheel and return its absolute path."""
    target = src if subdir in (".", "") else src / subdir
    if not target.exists():
        raise RuntimeError(f"subdirectory does not exist in repo: {subdir}")

    wheel_dir = out_dir / subdir.replace("/", "_") if subdir not in (".", "") else out_dir / "_root"
    wheel_dir.mkdir(parents=True, exist_ok=True)

    existing = list(wheel_dir.glob("*.whl"))
    if existing:
        return existing[0]

    run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheel_dir), str(target)],
    )
    built = list(wheel_dir.glob("*.whl"))
    if not built:
        raise RuntimeError(f"no wheel produced for {subdir}")
    return built[0]


def main(
    commit: str = typer.Option(..., help="Git commit SHA to build."),
    subdir: list[str] = typer.Option(
        ..., "--subdir", help="Subdirectory to build (repeatable). Use '.' for repo root."
    ),
    repo: str = typer.Option(DEFAULT_REPO, help="Git URL to clone."),
    cache_dir: Path = typer.Option(DEFAULT_CACHE, help="Where to keep clones and built wheels."),
    force: bool = typer.Option(False, help="Rebuild even if cached wheels exist."),
    output_format: str = typer.Option(
        "manifest", help="Output format: 'manifest' (json subdir->path) or 'paths' (one path per line)."
    ),
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    commit_dir = cache_dir / commit
    src = commit_dir / "src"
    wheels_dir = commit_dir / "wheels"

    ensure_clone(repo, commit, src)

    if force and wheels_dir.exists():
        import shutil
        shutil.rmtree(wheels_dir)
    wheels_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, str] = {}
    for sd in subdir:
        wheel = build_one(src, sd, wheels_dir)
        manifest[sd] = str(wheel.resolve())

    if output_format == "manifest":
        print(json.dumps(manifest, indent=2))
    elif output_format == "paths":
        for path in manifest.values():
            print(path)
    else:
        raise typer.BadParameter(f"unknown output_format: {output_format}")


if __name__ == "__main__":
    typer.run(main)
