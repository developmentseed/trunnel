"""
Trunnel CLI: Precision-bored SSM tunnels to private RDS instances.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import boto3
import click

from trunnel_cli.discovery import Discoverable, TunnelDiscoverer


def _select_resource[T: Discoverable](resources: list[T], label: str) -> T:
    """
    Interactive selector for disambiguating multiple AWS resources.

    Parameters
    ----------
    resources : list[Discoverable]
        The list of discovered resources.
    label : str
        Human-readable label for the resource type (e.g., "Bastion").

    Returns
    -------
    Discoverable
        The selected resource.

    Raises
    ------
    click.ClickException
        If no resources are provided in the list.
    """
    if not resources:
        raise click.ClickException(f"No {label} found matching criteria.")

    if len(resources) == 1:
        return resources[0]

    click.secho(f"\nSelect a {label}:", fg="yellow", bold=True)
    for i, r in enumerate(resources, 1):
        click.echo(f" {click.style(str(i), fg='cyan', bold=True)}) {r.id} - {r.name}")

    choice = click.prompt(
        "\nEnter number",
        type=click.IntRange(1, len(resources)),
    )
    return resources[choice - 1]


@contextmanager
def _aws_errors(label: str) -> Generator[None, None, None]:
    """Translate unexpected AWS/boto3 exceptions into a clean ClickException."""
    try:
        yield
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"{label}: {e}") from e


def _verify_prerequisites() -> None:
    """Ensure required CLI programs are installed"""
    for bin_name in ["aws", "session-manager-plugin"]:
        if not shutil.which(bin_name):
            raise click.UsageError(
                f"Dependency '{bin_name}' not found. Install AWS CLI and Plugin."
            )


def _assert_port_free(port: int) -> None:
    """Raise early if the local port is already in use."""
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            raise click.ClickException(
                f"Port {port} is already in use (local Postgres?). "
                f"Choose a free port with --local-port."
            )
    except OSError:
        pass  # port is free


def _wait_for_port(port: int, tunnel: subprocess.Popen[bytes], timeout: float = 30.0) -> bool:
    """Poll localhost:<port> until it accepts a connection, the tunnel exits, or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if tunnel.poll() is not None:
            return False
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _parse_db_secret(secret_string: str) -> dict[str, str]:
    """Parse a Secrets Manager SecretString as RDS JSON credentials."""
    try:
        data = json.loads(secret_string)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Secret is not valid JSON: {e}") from e
    for field in ("username", "password"):
        if field not in data:
            raise click.ClickException(f"Secret JSON missing required field: '{field}'")
    return data


def _build_ssm_cmd(
    bastion_id: str, rds_host: str, rds_port: int, local_port: int, profile: str | None
) -> list[str]:
    params = json.dumps(
        {
            "host": [rds_host],
            "portNumber": [str(rds_port)],
            "localPortNumber": [str(local_port)],
        }
    )
    cmd = [
        "aws",
        "ssm",
        "start-session",
        "--target",
        bastion_id,
        "--document-name",
        "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters",
        params,
    ]
    if profile:
        cmd.extend(["--profile", profile])
    return cmd


# ---------------------------------------------------------------------------
# Reusable option groups
# ---------------------------------------------------------------------------


def _bastion_opts(f: Callable[..., Any]) -> Callable[..., Any]:
    f = click.option(
        "--bastion-value",
        default="Bastion",
        show_default=True,
        show_envvar=True,
        help="Tag value for Bastion.",
    )(f)
    f = click.option(
        "--bastion-key",
        default="Role",
        show_default=True,
        show_envvar=True,
        help="Tag key for Bastion.",
    )(f)
    return f


def _rds_opts(f: Callable[..., Any]) -> Callable[..., Any]:
    f = click.option("--rds-value", required=True, show_envvar=True, help="Tag value for RDS.")(f)
    f = click.option("--rds-key", required=True, show_envvar=True, help="Tag key for RDS.")(f)
    return f


def _secret_opts(f: Callable[..., Any]) -> Callable[..., Any]:
    f = click.option(
        "--secret-value",
        required=True,
        show_envvar=True,
        help="Tag value for the Secrets Manager secret.",
    )(f)
    f = click.option(
        "--secret-key",
        required=True,
        show_envvar=True,
        help="Tag key for the Secrets Manager secret.",
    )(f)
    return f


def _profile_opt(f: Callable[..., Any]) -> Callable[..., Any]:
    return click.option("--profile", type=str, show_envvar=True, help="AWS CLI profile.")(f)


def _local_port_opt(f: Callable[..., Any]) -> Callable[..., Any]:
    return click.option(
        "--local-port", default=5432, type=int, show_default=True, show_envvar=True
    )(f)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@click.group(context_settings={"auto_envvar_prefix": "TRUNNEL"})
def main() -> None:
    """Trunnel: Precision-bored SSM tunnels to private RDS instances."""


@main.command()
@_bastion_opts
@_rds_opts
@_local_port_opt
@_profile_opt
@click.option("--reconnect", is_flag=True, show_envvar=True, help="Auto-retry on disconnect.")
def connect(
    bastion_key: str,
    bastion_value: str,
    rds_key: str,
    rds_value: str,
    local_port: int,
    profile: str | None,
    reconnect: bool,
) -> None:
    """
    Securely bore a tunnel to RDS via Trunnel.
    """
    _verify_prerequisites()

    discoverer = TunnelDiscoverer(session=boto3.Session(profile_name=profile))
    click.echo("🔍 Searching AWS...")

    with _aws_errors("EC2 Lookup Failed"):
        target_bastion = _select_resource(
            discoverer.find_bastions(bastion_key, bastion_value), "Bastion"
        )
    with _aws_errors("RDS Lookup Failed"):
        target_rds = _select_resource(discoverer.find_rds(rds_key, rds_value), "RDS")

    aws_cmd = _build_ssm_cmd(target_bastion.id, target_rds.id, target_rds.port, local_port, profile)

    try:
        while True:
            click.secho(
                f"\n🚎 Trunnel Active: localhost:{local_port} -> {target_rds.name}",
                fg="green",
                bold=True,
            )
            click.secho(
                f"🔗 {target_rds.id} via {target_bastion.name} ({target_bastion.id})", fg="cyan"
            )

            proc = subprocess.run(aws_cmd, check=False)

            if not reconnect or proc.returncode == 0:
                break

            click.secho("⚠️ Disconnected. Reconnecting in 5s...", fg="yellow")
            time.sleep(5)
    except KeyboardInterrupt:
        click.echo("\n👋 Trunnel interrupted. Goodbye!")
    else:
        click.echo("\n👋 Trunnel disconnected. Goodbye!")


@main.command()
@_secret_opts
@_profile_opt
def secrets(
    secret_key: str,
    secret_value: str,
    profile: str | None,
) -> None:
    """
    Fetch and print a Secrets Manager secret by tag.
    """
    discoverer = TunnelDiscoverer(session=boto3.Session(profile_name=profile))
    click.echo("🔍 Searching AWS Secrets Manager...")

    with _aws_errors("Secrets Lookup Failed"):
        target = _select_resource(discoverer.find_secrets(secret_key, secret_value), "Secret")

    with _aws_errors(f"Failed to fetch secret '{target.name}'"):
        secret_string = discoverer.fetch_secret(target.id)

    click.echo(secret_string)


@main.command()
@_bastion_opts
@_rds_opts
@_secret_opts
@_local_port_opt
@_profile_opt
def psql(
    bastion_key: str,
    bastion_value: str,
    rds_key: str,
    rds_value: str,
    secret_key: str,
    secret_value: str,
    local_port: int,
    profile: str | None,
) -> None:
    """
    Fetch credentials, open a tunnel, and launch psql.
    """
    _verify_prerequisites()
    if not shutil.which("psql"):
        raise click.UsageError("Dependency 'psql' not found. Install PostgreSQL client tools.")

    discoverer = TunnelDiscoverer(session=boto3.Session(profile_name=profile))
    click.echo("🔍 Searching AWS...")

    with _aws_errors("EC2 Lookup Failed"):
        target_bastion = _select_resource(
            discoverer.find_bastions(bastion_key, bastion_value), "Bastion"
        )
    with _aws_errors("RDS Lookup Failed"):
        target_rds = _select_resource(discoverer.find_rds(rds_key, rds_value), "RDS")
    with _aws_errors("Secrets Lookup Failed"):
        target_secret = _select_resource(
            discoverer.find_secrets(secret_key, secret_value), "Secret"
        )
    with _aws_errors(f"Failed to fetch secret '{target_secret.name}'"):
        creds = _parse_db_secret(discoverer.fetch_secret(target_secret.id))

    _assert_port_free(local_port)

    aws_cmd = _build_ssm_cmd(target_bastion.id, target_rds.id, target_rds.port, local_port, profile)

    click.secho(
        f"\n🚎 Opening tunnel: localhost:{local_port} -> {target_rds.name}",
        fg="green",
        bold=True,
    )
    click.secho(f"🔗 {target_rds.id} via {target_bastion.name} ({target_bastion.id})", fg="cyan")

    tunnel = subprocess.Popen(aws_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        click.echo("⏳ Waiting for tunnel...")
        if not _wait_for_port(local_port, tunnel):
            raise click.ClickException(f"Tunnel did not become ready on port {local_port}.")

        psql_cmd = [
            "psql",
            "-h",
            "localhost",
            "-p",
            str(local_port),
            "-U",
            creds["username"],
        ]
        if dbname := creds.get("dbname") or creds.get("database"):
            psql_cmd.extend(["-d", dbname])

        env = {**os.environ, "PGPASSWORD": creds["password"]}
        click.secho(f"🐘 Connecting as {creds['username']}...", fg="green")
        subprocess.run(psql_cmd, env=env, check=False)
    except KeyboardInterrupt:
        click.echo("\n👋 Interrupted. Goodbye!")
    finally:
        tunnel.terminate()
        tunnel.wait()
