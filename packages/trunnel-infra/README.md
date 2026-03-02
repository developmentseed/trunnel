# trunnel-infra

> AWS CDK Construct for self-healing, auto-rotating Bastion hosts.

`trunnel-infra` provides the `AutoRotatingBastion` construct. It manages an Auto Scaling Group (ASG) designed
specifically for SSM-based tunneling.

## Key Features

- **Zero Ingress:** No SSH/Port 22 or public subnet required. All traffic travels via SSM's encrypted websocket channel.
- **Auto-Rotation:** Automatically triggers an ASG Instance Refresh when a referenced SSM Parameter (AMI ID) is updated.
- **Least Privilege:** Automatically manages Security Group egress/ingress based on the provided RDS targets using the
  CDK Connections API.

## Installation

To add to your project using `uv`,

```bash
uv add --group deploy "trunnel-infra @ git+https://github.com/developmentseed/trunnel#subdirectory=packages/trunnel-infra"
```
