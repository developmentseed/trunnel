from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import boto3

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
