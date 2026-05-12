from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_rds import RDSClient
    from mypy_boto3_resourcegroupstaggingapi import ResourceGroupsTaggingAPIClient
    from mypy_boto3_secretsmanager import SecretsManagerClient


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


@dataclass
class Secret:
    """Secrets Manager secret metadata."""

    id: str
    name: str


type Discoverable = Bastion | Database | Secret


@dataclass
class TunnelDiscoverer:
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
    secrets_client : SecretsManagerClient, optional
        Injected Secrets Manager client.
    """

    session: boto3.Session = field(default_factory=lambda: boto3.Session())
    ec2_client: EC2Client | None = None
    rds_client: RDSClient | None = None
    tag_client: ResourceGroupsTaggingAPIClient | None = None
    secrets_client: SecretsManagerClient | None = None

    def __post_init__(self) -> None:
        """
        Initialize AWS clients, respecting injected overrides.
        """
        self._ec2: EC2Client = self.ec2_client or self.session.client("ec2")
        self._rds: RDSClient = self.rds_client or self.session.client("rds")
        self._tags: ResourceGroupsTaggingAPIClient = self.tag_client or self.session.client(
            "resourcegroupstaggingapi"
        )
        self._secrets: SecretsManagerClient = self.secrets_client or self.session.client(
            "secretsmanager"
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
        rds_paginator = self._rds.get_paginator("describe_db_instances")

        matches: list[Database] = []
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

    def find_secrets(self, tag_key: str, tag_value: str) -> list[Secret]:
        """
        Find Secrets Manager secrets by tag key/value pair.

        Parameters
        ----------
        tag_key : str
            The tag key to filter by.
        tag_value : str
            The tag value to filter by.

        Returns
        -------
        list[Secret]
            A list of discovered Secret resources.
        """
        paginator = self._secrets.get_paginator("list_secrets")
        secrets: list[Secret] = []
        for page in paginator.paginate(
            Filters=[
                {"Key": "tag-key", "Values": [tag_key]},
                {"Key": "tag-value", "Values": [tag_value]},
            ]
        ):
            for s in page.get("SecretList", []):
                secrets.append(Secret(id=s["Name"], name=s.get("Description") or s["Name"]))
        return secrets
