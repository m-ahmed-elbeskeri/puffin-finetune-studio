"""Top-level `puffin` CLI."""
from __future__ import annotations

import platform

import typer

from llmops import __version__
from llmops.common.versioning import git_sha, package_versions

app = typer.Typer(
    name="puffin",
    help="puffin-finetune-studio: cloud-portable LLM fine-tuning template.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print package version."""
    typer.echo(__version__)


@app.command()
def info() -> None:
    """Show environment info: Python, key package versions, git SHA."""
    typer.echo(f"puffin   {__version__}")
    typer.echo(f"Python   {platform.python_version()}")
    typer.echo(f"Platform {platform.platform()}")
    typer.echo(f"Git SHA  {git_sha() or 'n/a'}")
    typer.echo("Packages:")
    for pkg, ver in package_versions().items():
        typer.echo(f"  {pkg:15s} {ver}")


@app.command()
def hash_config(path: str) -> None:
    """Print a stable hash of a YAML config (lineage tag)."""
    from llmops.common.config import config_hash, load_yaml

    typer.echo(config_hash(load_yaml(path)))


if __name__ == "__main__":
    app()
