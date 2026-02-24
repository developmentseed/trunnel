"""
Trunnel CLI: Precision-bored SSM tunnels to private RDS instances.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import boto3
import click

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_rds import RDSClient
    from mypy_boto3_resourcegroupstaggingapi import ResourceGroupsTaggingAPIClient


@dataclass
class Bastion:
    """EC2 Bastion metadata."""

    id: str
    name: str


@dataclass
class Database:
    """RDS Database metadata."""

    id: str
    name: str
    port: int


type Discoverable = Bastion | Database


@dataclass
class TunnelManager:
    """
    Orchestrates AWS resource discovery.

    Parameters
    ----------
    session : boto3.Session, optional
        An existing Boto3 session to use.
    ec2_client : EC2Client, optional
        Injected EC2 client.
    rds_client : RDSClient, optional
        Injected RDS client.
    tag_client : ResourceGroupsTaggingAPIClient, optional
        Resource tagging API client.
    """

    session: boto3.Session = field(default_factory=lambda: boto3.Session())
    ec2_client: EC2Client | None = None
    rds_client: RDSClient | None = None
    tag_client: ResourceGroupsTaggingAPIClient | None = None

    def __post_init__(self) -> None:
        """
        Initialize AWS clients, respecting injected overrides.
        """
        self._ec2: EC2Client = self.ec2_client or self.session.client("ec2")
        self._rds: RDSClient = self.rds_client or self.session.client("rds")
        self._tags: ResourceGroupsTaggingAPIClient = self.tag_client or self.session.client(
            "resourcegroupstaggingapi"
        )

    def find_bastions(self, key: str, value: str) -> list[Bastion]:
        """
        Find running EC2 instances via server-side tag filters.

        Parameters
        ----------
        key : str
            The tag key to filter by.
        value : str
            The tag value to filter by.

        Returns
        -------
        list[Bastion]
            A list of discovered Bastion resources.

        Raises
        ------
        click.ClickException
            If the AWS API call fails.
        """
        paginator = self._ec2.get_paginator("describe_instances")
        instances: list[Bastion] = []
        for page in paginator.paginate(
            Filters=[
                {"Name": f"tag:{key}", "Values": [value]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        ):
            for res in page.get("Reservations", []):
                for inst in res.get("Instances", []):
                    name = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                        "Unnamed",
                    )
                    instances.append(Bastion(id=inst["InstanceId"], name=name))
        return instances

    def find_rds(self, key: str, value: str) -> list[Database]:
        """
        Query available RDS instances by cross-referencing tags locally.

        Parameters
        ----------
        key : str
            The tag key to filter by.
        value : str
            The tag value to filter by.

        Returns
        -------
        list[Database]
            A list of discovered RDS resources.

        Raises
        ------
        click.ClickException
            If the AWS API call fails.
        """
        # First, ask AWS for ONLY the ARNs of databases that match this tag
        tagged_arns = []

        paginator = self._tags.get_paginator("get_resources")
        for tag_page in paginator.paginate(
            ResourceTypeFilters=["rds:db"], TagFilters=[{"Key": key, "Values": [value]}]
        ):
            tagged_arns.extend(
                [r["ResourceARN"] for r in tag_page.get("ResourceTagMappingList", [])]
            )

        if not tagged_arns:
            return []

        # Fetch the actual Endpoints for those matched ARNs
        matches: list[Database] = []
        rds_paginator = self._rds.get_paginator("describe_db_instances")

        # describe_db_instances doesn't accept a list of ARNs natively,
        # but filtering the response locally is now O(1) in API calls!
        for rds_page in rds_paginator.paginate():
            for db in rds_page.get("DBInstances", []):
                if db["DBInstanceArn"] in tagged_arns and db.get("DBInstanceStatus") == "available":
                    matches.append(
                        Database(
                            id=db["Endpoint"]["Address"],
                            name=db["DBInstanceIdentifier"],
                            port=db["Endpoint"].get("Port", 5432),
                        )
                    )

        return matches


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
    Resource
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
    options = {r.id: r for r in resources}
    for r in resources:
        click.echo(f" • {click.style(r.id, fg='cyan')} - {r.name}")

    choice_id = click.prompt(
        f"\nEnter {label} ID", type=click.Choice(list(options.keys())), show_choices=False
    )
    return options[choice_id]


def _verify_prerequisites() -> None:
    """Ensure required CLI programs are installed"""
    for bin_name in ["aws", "session-manager-plugin"]:
        if not shutil.which(bin_name):
            raise click.UsageError(
                f"Dependency '{bin_name}' not found. Install AWS CLI and Plugin."
            )


@click.command()
@click.pass_context
@click.option("--bastion-key", default="Role", show_default=True, help="Tag key for Bastion.")
@click.option(
    "--bastion-value", default="Bastion", show_default=True, help="Tag value for Bastion."
)
@click.option("--rds-key", default="App", show_default=True, help="Tag key for RDS.")
@click.option("--rds-value", required=True, help="Tag value for RDS.")
@click.option("--local-port", default=5432, type=int, show_default=True)
@click.option("--profile", type=str, help="AWS CLI profile.")
@click.option("--reconnect", is_flag=True, help="Auto-retry on disconnect.")
def main(
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

    mgr = TunnelManager(session=boto3.Session(profile_name=profile))
    click.echo("🔍 Searching AWS...")

    try:
        target_bastion = _select_resource(mgr.find_bastions(bastion_key, bastion_value), "Bastion")
    except Exception as e:
        raise click.ClickException(f"EC2 Lookup Failed: {e}") from e
    try:
        target_rds = _select_resource(mgr.find_rds(rds_key, rds_value), "RDS")
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
