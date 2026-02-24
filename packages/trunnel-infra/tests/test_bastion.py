"""
Unit tests for Trunnel Infra CDK constructs.
"""

from __future__ import annotations

import pytest
from aws_cdk import Stack, aws_ec2 as ec2, aws_rds as rds
from aws_cdk.assertions import Match, Template

from trunnel_infra.bastion import AutoRotatingBastion


@pytest.fixture
def cdk_context() -> tuple[Stack, ec2.Vpc, rds.IDatabaseInstance]:
    stack = Stack(env={"region": "us-east-1"})
    vpc = ec2.Vpc(stack, "TestVPC")
    db = rds.DatabaseInstance(
        stack,
        "TestDB",
        engine=rds.DatabaseInstanceEngine.POSTGRES,
        vpc=vpc,
    )
    return stack, vpc, db


def test_bastion_creation_with_default_ami(
    cdk_context: tuple[Stack, ec2.Vpc, rds.IDatabaseInstance],
) -> None:
    """Case 1: Verify creation with NO ami argument (Defaults to AL2023)."""
    stack, vpc, db = cdk_context

    AutoRotatingBastion(stack, "DefaultBastion", vpc=vpc, db_targets=[db])

    template = Template.from_stack(stack)

    # Should have an ASG and Security Group
    template.resource_count_is("AWS::AutoScaling::AutoScalingGroup", 1)
    template.resource_count_is("AWS::EC2::SecurityGroup", 2)  # DB SG + Bastion SG

    # NO automation resources should be present
    template.resource_count_is("AWS::Lambda::Function", 0)
    template.resource_count_is("AWS::Events::Rule", 0)


def test_bastion_creation_with_static_ami_string(
    cdk_context: tuple[Stack, ec2.Vpc, rds.IDatabaseInstance],
) -> None:
    """Case 2: Verify creation with a static AMI ID string (No automation)."""
    stack, vpc, db = cdk_context
    static_ami = "ami-0123456789abcdef0"

    AutoRotatingBastion(stack, "StaticBastion", vpc=vpc, db_targets=[db], ami=static_ami)

    template = Template.from_stack(stack)

    # Verify the ASG uses the hardcoded AMI
    template.has_resource_properties(
        "AWS::AutoScaling::LaunchConfiguration",
        {"ImageId": static_ami},
    )

    # NO automation resources should be present for static AMIs
    template.resource_count_is("AWS::Lambda::Function", 0)
    template.resource_count_is("AWS::Events::Rule", 0)


def test_bastion_automation_with_ssm_param(
    cdk_context: tuple[Stack, ec2.Vpc, rds.IDatabaseInstance],
) -> None:
    """Case 3: Verify full automation suite is created when an SSM path is provided."""
    stack, vpc, db = cdk_context
    ssm_path = "/company/images/latest-ami"

    AutoRotatingBastion(stack, "SsmBastion", vpc=vpc, db_targets=[db], ami=ssm_path)

    template = Template.from_stack(stack)

    # Automation resources MUST exist for SSM mode
    template.resource_count_is("AWS::Lambda::Function", 1)
    template.resource_count_is("AWS::Events::Rule", 1)

    # Verify the EventBridge Rule targets the specific SSM parameter
    template.has_resource_properties(
        "AWS::Events::Rule",
        {"EventPattern": {"detail": {"name": [ssm_path]}}},
    )


def test_sg_egress_rules(cdk_context: tuple[Stack, ec2.Vpc, rds.IDatabaseInstance]) -> None:
    stack, vpc, db = cdk_context

    AutoRotatingBastion(stack, "Bastion", vpc=vpc, db_targets=[db])
    template = Template.from_stack(stack)

    template.has_resource_properties(
        "AWS::EC2::SecurityGroupIngress",
        {
            "FromPort": Match.any_value(),
            "ToPort": Match.any_value(),
            "IpProtocol": "tcp",
        },
    )
