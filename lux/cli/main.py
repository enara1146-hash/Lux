from __future__ import annotations

import os

import typer

app = typer.Typer(help="Lux coding-agent commands.")


@app.command()
def worker() -> None:
    """Run the durable SQLite-backed worker loop."""
    from lux.server.runner import run

    run()


@app.command()
def doctor() -> None:
    """Check the configuration required to run Lux jobs."""
    checks = {
        "LLM_API_KEY or OPENAI_API_KEY": bool(
            os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        ),
        "LLM_MODEL or OPENAI_MODEL": bool(
            os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "nvidia/nemotron-3-ultra-550b-a55b:free"
        ),
    }
    for name, present in checks.items():
        typer.echo(f"{'ok' if present else 'missing'}: {name}")
    if not all(checks.values()):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
