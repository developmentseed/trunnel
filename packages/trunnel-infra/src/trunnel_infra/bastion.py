"""
Trunnel Infra: Self-healing, auto-rotating AWS entry points.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    Tags,
    aws_autoscaling as autoscaling,
    aws_ec2 as ec2,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_rds as rds,
)
from constructs import Construct

HANDLER_PATH = Path(__file__).parent / "lambda_handler"


class AutoRotatingBastion(Construct):
    """
    HA Bastion construct via ASG with automated AMI lifecycle management.

    Parameters
    ----------
    scope : Construct
        The CDK scope.
    id : str
        The construct ID.
    vpc : ec2.IVpc
        The VPC to deploy the bastion into.
    db_targets : list[rds.IDatabaseInstance | rds.IDatabaseCluster]
        The RDS instances the bastion should have access to.
    ami : str, optional
        Supports three modes:
        1. None: Defaults to Amazon Linux 2023.
        2. Static ID: Uses a specific AMI string (e.g., 'ami-12345').
        3. SSM Key: Uses a path starting with '/' to enable auto-refresh.
    instance_type : ec2.InstanceType, optional
        Ec2 instance type to use for the bastion host. If not provided defaults
        to t3.micro.
    user_data : ec2.UserData, optional
        UserData script to run on instance launch. When ``ami`` is ``None``
        (default AL2023), defaults to :meth:`amazon_linux_user_data` which
        configures ``dnf-automatic`` for security-only updates. When a custom
        AMI is provided no UserData is added by default — use
        :meth:`debian_user_data` or supply a fully custom script.
    lambda_runtime : lambda_.Runtime, optional
        The runtime for the refresh Lambda. Defaults to Python 3.12.
    bastion_key : str, optional
        Tag key used by Trunnel CLI to discover the bastion.
    bastion_value : str, optional
        Tag value used by Trunnel CLI to discover the bastion.
    bastion_name : str, optional
        Value for the "Name" tag, displayed in the CLI selector.
    """

    @staticmethod
    def amazon_linux_user_data() -> ec2.UserData:
        """UserData for Amazon Linux 2023: enables dnf-automatic security updates."""
        ud = ec2.UserData.for_linux()
        ud.add_commands(
            "dnf install -y dnf-automatic",
            "sed -i 's/^upgrade_type = .*/upgrade_type = security/' /etc/dnf/automatic.conf",
            "sed -i 's/^apply_updates = .*/apply_updates = yes/' /etc/dnf/automatic.conf",
            "systemctl enable --now dnf-automatic.timer",
        )
        return ud

    @staticmethod
    def debian_user_data() -> ec2.UserData:
        """UserData for Debian/Ubuntu AMIs: enables unattended-upgrades."""
        ud = ec2.UserData.for_linux()
        ud.add_commands(
            "apt-get install -y unattended-upgrades",
            "dpkg-reconfigure --priority=low unattended-upgrades",
        )
        return ud

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        vpc: ec2.IVpc,
        db_targets: list[rds.IDatabaseInstance | rds.IDatabaseCluster],
        ami: str | None = None,
        instance_type: ec2.InstanceType | None = None,
        user_data: ec2.UserData | None = None,
        lambda_runtime: lambda_.Runtime = lambda_.Runtime.PYTHON_3_12,
        bastion_key: str = "Role",
        bastion_value: str = "Bastion",
        bastion_name: str = "Bastion",
    ) -> None:
        super().__init__(scope, id)

        if user_data is None and ami is None:
            user_data = AutoRotatingBastion.amazon_linux_user_data()

        is_ssm = isinstance(ami, str) and ami.startswith("/")
        if is_ssm:
            assert ami is not None
            machine_image = ec2.MachineImage.from_ssm_parameter(
                ami, os=ec2.OperatingSystemType.LINUX
            )
        elif isinstance(ami, str):
            machine_image = ec2.MachineImage.generic_linux({Stack.of(self).region: ami})
        else:
            machine_image = ec2.AmazonLinuxImage(
                generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2023
            )

        # Setup ASG
        self.bastion_sg = ec2.SecurityGroup(
            self,
            "BastionSG",
            vpc=vpc,
            allow_all_outbound=True,  # Allows SSM polling and 'dnf update'
            description="Bastion host private subnet",
        )

        if instance_type is None:
            instance_type = ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO)

        self.asg = autoscaling.AutoScalingGroup(
            self,
            "ASG",
            vpc=vpc,
            instance_type=instance_type,
            machine_image=machine_image,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=self.bastion_sg,
            max_capacity=2,
            update_policy=autoscaling.UpdatePolicy.rolling_update(min_instances_in_service=1),
            require_imdsv2=True,
            user_data=user_data,
        )
        self.asg.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
        )

        # Apply necessary tags for the CLI discovery
        Tags.of(self.asg).add(bastion_key, bastion_value, apply_to_launched_instances=True)
        Tags.of(self.asg).add("Name", bastion_name, apply_to_launched_instances=True)

        # Ensure Bastion can connect to RDS
        for db in db_targets:
            db.connections.allow_default_port_from(self.asg, description="Bastion Host Access")

        # Automation for AMI updates
        if is_ssm:
            assert ami is not None
            self._setup_auto_refresh(self.asg, ami, lambda_runtime)

    def export_security_group(self, export_name: str) -> CfnOutput:
        """
        Exports the Bastion's Security Group ID to CloudFormation exports.

        This allows decoupled RDS stacks to independently lookup and authorize
        the Bastion's security group using `Fn.import_value()`.

        Parameters
        ----------
        export_name : str
            The globally unique name for the CloudFormation export.

        Returns
        -------
        CfnOutput
            The CloudFormation output construct.
        """
        return CfnOutput(
            self,
            "BastionSgExport",
            value=self.bastion_sg.security_group_id,
            export_name=export_name,
        )

    def _setup_auto_refresh(
        self, asg: autoscaling.IAutoScalingGroup, param_name: str, runtime: lambda_.Runtime
    ) -> None:
        """
        Configures EventBridge and Lambda to trigger Instance Refresh.

        Parameters
        ----------
        param_name : str
            The SSM parameter name to monitor.
        runtime : lambda_.Runtime
            The Lambda runtime.
        """
        refresh_fn = lambda_.Function(
            self,
            "RefreshHandler",
            runtime=runtime,
            handler="handler.handler",
            timeout=Duration.seconds(30),
            environment={"ASG_NAME": asg.auto_scaling_group_name},
            code=lambda_.Code.from_asset(str(HANDLER_PATH)),
        )

        assert refresh_fn.role is not None
        refresh_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["autoscaling:StartInstanceRefresh", "autoscaling:CreateOrUpdateTags"],
                resources=[asg.auto_scaling_group_arn],
            )
        )

        rule = events.Rule(
            self,
            "AmiUpdateRule",
            event_pattern=events.EventPattern(
                source=["aws.ssm"],
                detail_type=["Parameter Store Change"],
                detail={"name": [param_name], "operation": ["Update"]},
            ),
        )
        rule.add_target(
            cast(events.IRuleTarget, targets.LambdaFunction(cast(lambda_.IFunction, refresh_fn)))
        )
