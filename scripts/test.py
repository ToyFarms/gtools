import os
import sys
from pathlib import Path
import click

from scripts.utils import call, capture_stdout, executable_exists


@click.command()
@click.option("-r", "--run-server", is_flag=True, help="run http server")
def test(run_server: bool) -> None:
    if not executable_exists("coverage"):
        print("coverage.py is required (pip install coverage)")
        return

    if not executable_exists("pytest"):
        print("pytest is required (pip install pytest)")
        return

    if "--forked" not in capture_stdout(["pytest", "--help"]):
        print("pytest-forked is required (pip install pytest-forked)")
        return

    call(["coverage", "run", "-m", "pytest", "--forked", "-vv"])
    call(["coverage", "html"])
    call(["coverage", "report", "-m"])

    report = Path("htmlcov")
    if not report.exists():
        print("unexpected, htmlcov/ should exists after running `coverage html`")
        return

    if run_server:
        port = 9576
        print(f"go to http://localhost:{port} for the coverage report")
        os.chdir(report)
        try:
            call([sys.executable, "-m", "http.server", port])
        except (KeyboardInterrupt, InterruptedError):
            pass
