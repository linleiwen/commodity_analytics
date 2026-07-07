"""Command-line interface (spec 6.3).

Thin Typer wrapper over :mod:`app.pipeline` and the exporters. Run ``python -m app.cli --help``.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from app import settings
from app.exporters import excel as excel_exporter
from app.exporters import qa_report as qa_exporter
from app.storage import db

app = typer.Typer(add_completion=False, help="Japan -> DMV arbitrage analytics pipeline.")

DEFAULT_RUN_ID = "2026-07-japan-trip"


def _echo(obj) -> None:
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


@app.command("init-db")
def init_db() -> None:
    """Create the SQLite analytics database from the schema."""
    settings.load_env()
    path = db.init_db()
    warnings = settings.validate_scoring_config()
    for w in warnings:
        typer.secho(f"config warning: {w}", fg=typer.colors.YELLOW)
    typer.secho(f"Initialized database at {path}", fg=typer.colors.GREEN)


@app.command("import-seeds")
def import_seeds(file: Path = typer.Option(..., "--file", exists=True, help="Seeds YAML file.")) -> None:
    """Load candidate SKUs / aliases into Product Master."""
    from app import pipeline

    count, messages = pipeline.import_seeds(file)
    for m in messages:
        typer.secho(m, fg=typer.colors.YELLOW)
    typer.secho(f"Imported / updated {count} products.", fg=typer.colors.GREEN)


@app.command("collect")
def collect(
    sources: str = typer.Option(..., "--sources", help="Comma-separated collector names."),
    run_id: str = typer.Option(DEFAULT_RUN_ID, "--run-id"),
) -> None:
    """Run API collectors (missing-credential / disabled collectors are skipped + logged)."""
    from app import pipeline

    names = [s.strip() for s in sources.split(",") if s.strip()]
    _echo(pipeline.run_collect(names, run_id))


@app.command("manual-import")
def manual_import(
    type: str = typer.Option(..., "--type", help="field_prices | terapeak | social_notes | google_trends"),
    file: Path = typer.Option(..., "--file", exists=True),
    run_id: str = typer.Option(DEFAULT_RUN_ID, "--run-id"),
) -> None:
    """Import a human-exported CSV."""
    from app import pipeline

    _echo(pipeline.run_manual_import(type, file, run_id))


@app.command("normalize")
def normalize(run_id: str = typer.Option(DEFAULT_RUN_ID, "--run-id")) -> None:
    """Currency + unit conversion, product matching, shelf-life, fees."""
    from app import pipeline

    _echo(pipeline.run_normalize(run_id))


@app.command("score")
def score(run_id: str = typer.Option(DEFAULT_RUN_ID, "--run-id")) -> None:
    """Compliance rules -> weighted score -> penalties -> tiers -> luggage plan."""
    from app import pipeline

    _echo(pipeline.run_score(run_id))


@app.command("export-xlsx")
def export_xlsx(
    run_id: str = typer.Option(DEFAULT_RUN_ID, "--run-id"),
    out: Path = typer.Option(settings.EXPORT_DIR / "japan_dmv_product_rankings.xlsx", "--out"),
) -> None:
    """Write the decision workbook."""
    path = excel_exporter.export_workbook(run_id, out)
    typer.secho(f"Wrote workbook: {path}", fg=typer.colors.GREEN)


@app.command("qa-report")
def qa_report(
    run_id: str = typer.Option(DEFAULT_RUN_ID, "--run-id"),
    out: Path = typer.Option(settings.EXPORT_DIR / "qa_report.md", "--out"),
) -> None:
    """Write the Markdown QA report."""
    path = qa_exporter.export_report(run_id, out)
    typer.secho(f"Wrote QA report: {path}", fg=typer.colors.GREEN)


@app.command("capture")
def capture(
    url: str = typer.Option(..., "--url", help="Page to open in a visible browser for manual capture."),
    label: str = typer.Option("capture", "--label"),
    run_id: str = typer.Option(DEFAULT_RUN_ID, "--run-id"),
) -> None:
    """Headed browser + manual snapshot for login/CAPTCHA pages (never bypasses challenges)."""
    from app.collectors.browser_capture import BrowserCapture

    settings.load_env()
    result = BrowserCapture(run_id).capture(url, label)
    with db.connect() as conn:
        for log in result.logs:
            db.log_source(conn, log)
    _echo([log.get("message") for log in result.logs])


@app.command("run-all")
def run_all(
    run_id: str = typer.Option(DEFAULT_RUN_ID, "--run-id"),
    seeds: Path = typer.Option(settings.CONFIG_DIR / "keyword_seeds.yaml", "--seeds"),
    collect_sources: str = typer.Option("", "--collect", help="Optional comma-separated collectors to run."),
    out: Path = typer.Option(settings.EXPORT_DIR / "japan_dmv_product_rankings.xlsx", "--out"),
) -> None:
    """Convenience: init-db, seeds, sample manual imports, normalize, score, export, QA."""
    from app import pipeline

    db.init_db()
    typer.secho("1/8 init-db done", fg=typer.colors.CYAN)

    count, _ = pipeline.import_seeds(seeds)
    typer.secho(f"2/8 imported {count} seeds", fg=typer.colors.CYAN)

    imports = [
        ("field_prices", settings.MANUAL_IMPORT_DIR / "japan_store_prices.csv"),
        ("terapeak", settings.MANUAL_IMPORT_DIR / "terapeak.csv"),
        ("social_notes", settings.MANUAL_IMPORT_DIR / "xhs_notes.csv"),
        ("google_trends", settings.MANUAL_IMPORT_DIR / "google_trends.csv"),
    ]
    for i, (mtype, path) in enumerate(imports, start=3):
        if Path(path).exists():
            res = pipeline.run_manual_import(mtype, path, run_id)
            typer.secho(f"{i}/8 manual-import {mtype}: obs={res.get('observations')} sig={res.get('signals')}",
                        fg=typer.colors.CYAN)
        else:
            typer.secho(f"{i}/8 manual-import {mtype}: file missing, skipped ({path})", fg=typer.colors.YELLOW)

    if collect_sources.strip():
        names = [s.strip() for s in collect_sources.split(",") if s.strip()]
        pipeline.run_collect(names, run_id)
        typer.secho(f"   collect: {', '.join(names)}", fg=typer.colors.CYAN)

    pipeline.run_normalize(run_id)
    typer.secho("7/8 normalize done", fg=typer.colors.CYAN)
    pipeline.run_score(run_id)
    typer.secho("   score done", fg=typer.colors.CYAN)

    xlsx = excel_exporter.export_workbook(run_id, out)
    qa = qa_exporter.export_report(run_id, settings.EXPORT_DIR / "qa_report.md")
    typer.secho(f"8/8 exported:\n  {xlsx}\n  {qa}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
