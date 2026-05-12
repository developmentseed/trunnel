# trunnel-infra

> AWS CDK Construct for self-healing, auto-rotating Bastion hosts.

`trunnel-infra` provides the `AutoRotatingBastion` construct. It manages an Auto Scaling Group (ASG) designed
specifically for SSM-based tunneling.

## Key Features

- **Zero Ingress:** No SSH/Port 22 or public subnet required. All traffic travels via SSM's encrypted websocket channel.
- **Auto-Rotation:** Automatically triggers an ASG Instance Refresh when a referenced SSM Parameter (AMI ID) is updated.
- **Least Privilege:** Automatically manages Security Group egress/ingress based on the provided RDS targets using the
  CDK Connections API.
- **Unattended Upgrades:** Automatically applies security updates on every instance launch via `dnf-automatic` (Amazon
  Linux 2023 default).

## Unattended Security Updates

By default the bastion runs `dnf-automatic` on launch, configured for security-only updates — equivalent to
`unattended-upgrades` with `--priority=low` on Debian systems.

For non-AL2023 images, pass a custom `user_data` using one of the provided helpers:

```python
# Debian/Ubuntu AMI
AutoRotatingBastion(
    self,
    "Bastion",
    vpc=vpc,
    db_targets=[my_rds_instance],
    ami="ami-0123456789abcdef0",
    user_data=AutoRotatingBastion.debian_user_data(),
)

# Fully custom script
from aws_cdk import aws_ec2 as ec2

custom_ud = ec2.UserData.for_linux()
custom_ud.add_commands("your-custom-setup-here")

AutoRotatingBastion(
    self, "Bastion", vpc=vpc, db_targets=[my_rds_instance], user_data=custom_ud
)
```

## Installation

To add to your project using `uv`,

```bash
uv add --group deploy "trunnel-infra @ git+https://github.com/developmentseed/trunnel#subdirectory=packages/trunnel-infra"
```
