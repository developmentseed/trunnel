"""
Trunnel CLI: Precision-bored SSM tunnels to private RDS instances.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from functools import partial

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
        f"\nEnter number",
        type=click.IntRange(1, len(resources)),
    )
    return resources[choice - 1]


def _verify_prerequisites() -> None:
    """Ensure required CLI programs are installed"""
    for bin_name in ["aws", "session-manager-plugin"]:
        if not shutil.which(bin_name):
            raise click.UsageError(
                f"Dependency '{bin_name}' not found. Install AWS CLI and Plugin."
            )


opt = partial(click.option, show_envvar=True)


@click.group(context_settings={"auto_envvar_prefix": "TRUNNEL"})
def main() -> None:
    """Trunnel: Precision-bored SSM tunnels to private RDS instances."""


@main.command()
@click.pass_context
@opt("--bastion-key", default="Role", show_default=True, help="Tag key for Bastion.")
@opt("--bastion-value", default="Bastion", show_default=True, help="Tag value for Bastion.")
@opt("--rds-key", required=True, help="Tag key for RDS.")
@opt("--rds-value", required=True, help="Tag value for RDS.")
@opt("--local-port", default=5432, type=int, show_default=True)
@opt("--profile", type=str, help="AWS CLI profile.")
@opt("--reconnect", is_flag=True, help="Auto-retry on disconnect.")
def connect(
    ctx: click.Context,
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

    try:
        target_bastion = _select_resource(
            discoverer.find_bastions(bastion_key, bastion_value), "Bastion"
        )
    except Exception as e:
        raise click.ClickException(f"EC2 Lookup Failed: {e}") from e
    try:
        target_rds = _select_resource(discoverer.find_rds(rds_key, rds_value), "RDS")
    except Exception as e:
        raise click.ClickException(f"RDS Lookup Failed: {e}") from e

    params = json.dumps(
        {
            "host": [target_rds.id],
            "portNumber": [str(target_rds.port)],
            "localPortNumber": [str(local_port)],
        }
    )
    aws_cmd = [
        "aws",
        "ssm",
        "start-session",
        "--target",
        target_bastion.id,
        "--document-name",
        "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters",
        params,
    ]
    if profile:
        aws_cmd.extend(["--profile", profile])

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
@opt("--secret-key", required=True, help="Tag key to filter secrets.")
@opt("--secret-value", required=True, help="Tag value to filter secrets.")
@opt("--profile", type=str, help="AWS CLI profile.")
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

    try:
        found = discoverer.find_secrets(secret_key, secret_value)
    except Exception as e:
        raise click.ClickException(f"Secrets Lookup Failed: {e}") from e

    target = _select_resource(found, "Secret")

    try:
        response = discoverer._secrets.get_secret_value(SecretId=target.id)
    except Exception as e:
        raise click.ClickException(f"Failed to fetch secret '{target.name}': {e}") from e

    secret_value = response.get("SecretString") or response.get("SecretBinary", b"").decode()
    click.echo(secret_value)
