"""
Unit tests for Trunnel CLI discovery logic.
"""

from __future__ import annotations

from collections.abc import Generator

import boto3
import pytest
from botocore.stub import Stubber
from mypy_boto3_ec2 import EC2Client
from mypy_boto3_rds import RDSClient
from mypy_boto3_resourcegroupstaggingapi import ResourceGroupsTaggingAPIClient

from trunnel_cli.discovery import TunnelDiscoverer


@pytest.fixture
def mock_ec2() -> Generator[tuple[EC2Client, Stubber], None, None]:
    """Provides a stubbed EC2 client."""
    client = boto3.client("ec2", region_name="us-east-1")
    with Stubber(client) as stubber:
        yield client, stubber


@pytest.fixture
def mock_tagging() -> Generator[tuple[ResourceGroupsTaggingAPIClient, Stubber], None, None]:
    """Provides a stubbed EC2 client."""
    client = boto3.client("resourcegroupstaggingapi", region_name="us-east-1")
    with Stubber(client) as stubber:
        yield client, stubber


@pytest.fixture
def mock_rds() -> Generator[tuple[RDSClient, Stubber], None, None]:
    """Provides a stubbed RDS client."""
    client = boto3.client("rds", region_name="us-east-1")
    with Stubber(client) as stubber:
        yield client, stubber


def test_find_bastions(mock_ec2: tuple[EC2Client, Stubber]) -> None:
    """Verify EC2 discovery parses tags and instance IDs correctly."""
    client, stubber = mock_ec2

    response = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-1234567890abcdef0",
                        "Tags": [{"Key": "Name", "Value": "Bore-Proxy"}],
                        "State": {"Name": "running"},
                    }
                ]
            }
        ]
    }

    stubber.add_response("describe_instances", response)

    # Inject the mocked client
    discoverer = TunnelDiscoverer(ec2_client=client)
    results = discoverer.find_bastions("Role", "Bastion")

    assert len(results) == 1
    assert results[0].id == "i-1234567890abcdef0"
    assert results[0].name == "Bore-Proxy"


def test_find_rds_with_tags(
    mock_tagging: tuple[ResourceGroupsTaggingAPIClient, Stubber],
    mock_rds: tuple[RDSClient, Stubber],
) -> None:
    """Verify RDS discovery correctly handles the manual tag cross-reference."""
    tag_client, tag_stubber = mock_tagging
    tag_response = {
        "ResourceTagMappingList": [
            {
                "ResourceARN": "arn:aws:rds:us-east-1:123456789012:db:prod-db",
            }
        ]
    }
    tag_stubber.add_response("get_resources", tag_response)

    rds_client, rds_stubber = mock_rds
    db_response = {
        "DBInstances": [
            {
                "DBInstanceIdentifier": "prod-db",
                "DBInstanceArn": "arn:aws:rds:us-east-1:123456789012:db:prod-db",
                "DBInstanceStatus": "available",
                "Endpoint": {"Address": "prod-db.cluster-xyz.us-east-1.rds.amazonaws.com"},
            }
        ]
    }
    rds_stubber.add_response("describe_db_instances", db_response)

    discoverer = TunnelDiscoverer(tag_client=tag_client, rds_client=rds_client)
    results = discoverer.find_rds("App", "payments")

    assert len(results) == 1
    assert results[0].id == "prod-db.cluster-xyz.us-east-1.rds.amazonaws.com"
    assert results[0].name == "prod-db"
