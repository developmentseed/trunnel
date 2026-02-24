"""
Trunnel Refresh Handler: Triggers ASG Instance Refresh on AMI updates.
"""

from __future__ import annotations

import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

asg_client = boto3.client("autoscaling")


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    """
    AWS Lambda handler to trigger a rolling ASG Instance Refresh.

    Parameters
    ----------
    event : dict[str, Any]
        EventBridge event containing Parameter Store change details.
    context : Any
        Lambda context object.

    Returns
    -------
    dict[str, str]
        Status message.
    """
    asg_name = os.environ["ASG_NAME"]

    ami_id = event.get("detail", {}).get("value", "unknown")

    try:
        asg_client.create_or_update_tags(
            Tags=[
                {
                    "ResourceId": asg_name,
                    "ResourceType": "auto-scaling-group",
                    "Key": "AmiId",
                    "Value": ami_id,
                    "PropagateAtLaunch": True,
                }
            ]
        )

        asg_client.start_instance_refresh(
            AutoScalingGroupName=asg_name,
            Strategy="Rolling",
            Preferences={"MinHealthyPercentage": 100},
        )
        print(f"Refresh triggered for {asg_name} (AMI: {ami_id})")
        return {"status": "success"}

    except ClientError as e:
        if e.response["Error"]["Code"] == "InstanceRefreshInProgress":
            print(f"Refresh already in progress for {asg_name}. Ignoring.")
            return {"status": "skipped_already_in_progress"}
        raise
