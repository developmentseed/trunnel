# Trunnel

> Automated SSM tunneling and self-healing bastion host for private RDS.

```text
       __________________________________________________________________
      | %%% H H H H H H H H H H H H H H H H H H H H H H H H H H H H H%%%|
      | %%% H H H H H H H H H H H H H H H H H H H H H H H H H H H H H%%%|
      | %%% [ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ]  %%%|
      | %%%__________________________________________________________%%%|
      | %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%|
      | %%%%%%     _________________        _________________     %%%%%%|
      | %%%%%     / ############### \      / ############### \     %%%%%|
      | %%%%     / ################# \    / ################# \     %%%%|
      | %%%     | ####### [ ] ####### |  | ####### [ ] ####### |     %%%|
      | %%%     | #####  LOCAL  ##### |  | #####  PRIVATE ##### |    %%%|
      | %%%     | ####  MACHINE  #### |  | ####    RDS    #### |     %%%|
      | %%%     | #####  :5432  ##### |  | #####  ACCESS  ##### |    %%%|
      | %%%     | ################### |  | ################### |     %%%|
     _| %%%_____| ################### |__| ################### |_____%%%|_
    | |=========| ################### |==| ################### |========| |
    |_|_________|_____________________|__|_____________________|________|_|
      [ SSM ]   ################################################  [ VPC ]
```

Trunnel (a play on the [East Side Trolley Tunnel], or a wooden peg used to form a strong connection between pieces of
wood) helps automate securely connecting to your private AWS infrastructure through AWS Systems Manager (SSM). It
replaces manual SSH management with automated SSM discovery and a self-healing CDK bastion. Trunnel does NOT handle
fetching database credentials, but does make it easier to securely make the connection.

This tool was designed in response to help reduce minor frustrations like,

- What is the EC2 instance identifier for my bastion host?
- What is the RDS host URL and port I need to use?
- What is the syntax for the `aws ssm` command I need to use?
- How can I keep my Bastion host up to date with new AMIs?

Trunnel is composed of two packages: one for infrastructure deployment (`trunnel-infra`) and another for end users
(`trunnel-cli`).

## Trunnel Infrastructure

To deploy the EC2 bastion host using AWS Cloud Development Kit (CDK), first add the package to your deployment
dependencies.

```bash
uv add --group deploy "trunnel-infra @ git+https://github.com/developmentseed/trunnel#subdirectory=packages/trunnel-infra"
```

Next, integrate the AutoRotatingBastion construct into your CDK stack. It handles the Auto Scaling Group (ASG) setup,
SSM permissions, and automated AMI rotation logic.

```python
from trunnel_infra.bastion import AutoRotatingBastion

# Inside your Stack...
AutoRotatingBastion(
    self,
    "Bastion",
    vpc=vpc,
    # Databases you want to connect to can be specified below.
    # You could also leave this blank if you'd prefer to have
    # RDS owners manage their own Security Group ingress rules
    db_targets=[my_rds_instance],
    # Tracks an SSM parameter. Updating the parameter triggers
    # a zero-downtime rolling Instance Refresh.
    ami="/company/images/latest-linux-ami"
    # Optionally export the Security Group ID so other stacks can reference it
    export_sg_name="BastionSG-Production"
)
```

## Trunnel CLI

The Trunnel CLI makes it easy to find the bastion host and connect to your RDS database via an encrypted SSM tunnel.
Install it into your project's development dependencies:

```bash
uv add --group deploy "trunnel-cli @ git+https://github.com/developmentseed/trunnel#subdirectory=packages/trunnel-cli"
```

### Example Usage

To connect to an RDS instance tagged with App=my-service:

```bash
$ trunnel --rds-value my-service --reconnect

🔍 Searching AWS...
Select a Bastion:
 • i-0abcd1234efgh5678 - Production-Bastion
 • i-09876fedcba54321 - Staging-Bastion

Enter Bastion ID: i-0abcd1234efgh5678

🚀 Trunnel Active: localhost:5432 -> my-service-db.cluster.aws.com
🔗 my-service-db via Production-Bastion (i-0abcd1234efgh5678)

Starting session with SessionId: developer-0123456789abcdef
Port 5432 opened for session developer-0123456789abcdef.
Waiting for connections...
```

You can also view the full help text,

```bash
$ trunnel --help

Usage: trunnel [OPTIONS]

  Securely bore a tunnel to RDS via Trunnel.

Options:
  --bastion-key TEXT     Tag key for Bastion. [default: Role]
  --bastion-value TEXT   Tag value for Bastion. [default: Bastion]
  --rds-key TEXT         Tag key for RDS. [default: App]
  --rds-value TEXT       Tag value for RDS. [required]
  --local-port INTEGER   [default: 5432]
  --profile TEXT         AWS CLI profile.
  --reconnect            Auto-retry on disconnect.
  --help                 Show this message and exit.
```

[East Side Trolley Tunnel]: https://en.wikipedia.org/wiki/East_Side_Trolley_Tunnel
