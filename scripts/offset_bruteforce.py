import click
import subprocess
import os


def parse_range(range_str: str) -> range:
    """Parse '{start}-{end}' or '{n}' into a range."""
    if "-" in range_str:
        parts = range_str.split("-", 1)
        start, end = int(parts[0]), int(parts[1])
        return range(start, end + 1)
    else:
        n = int(range_str)
        return range(n, n + 1)


@click.command()
@click.argument("command")
@click.argument("range_str", metavar="RANGE")
def offset_bruteforce(command: str, range_str: str) -> None:
    """
    Run COMMAND for every offset in RANGE, passing the offset
    via the OFFSET environment variable.

    RANGE format: {start}-{end}  (inclusive) or {n} (single value)

    Prints each offset that does NOT produce output containing 'error'.
    """
    try:
        offsets = parse_range(range_str)
    except ValueError:
        raise click.BadParameter(
            "Must be '{start}-{end}' or '{n}'", param_hint="RANGE"
        )

    successes = []

    for offset in offsets:
        env = {**os.environ, "OFFSET": str(offset)}
        result = subprocess.run(
            command,
            shell=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # merge stderr into stdout
            text=True,
        )
        combined = result.stdout or ""

        if "error" in combined.lower():
            status = click.style("FAIL", fg="red")
        else:
            status = click.style("OK  ", fg="green")
            successes.append(offset)

        click.echo(f"[{status}] OFFSET={offset:<6}  {combined.strip()[:80]}")

    click.echo()
    if successes:
        click.echo(
            click.style("Successful offsets: ", bold=True)
            + ", ".join(str(s) for s in successes)
        )
    else:
        click.echo(click.style("No successful offsets found.", fg="yellow"))
