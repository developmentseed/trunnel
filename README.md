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
replaces manual SSH management with automated SSM discovery and a self-healing CDK bastion. Trunnel can discover
the bastion and RDS instance you need to connect to, fetch database credentials stored in Secrets Manager, and
bore the encrypted tunnel — all from a single CLI.

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
)

# Export the Security Group ID so other stacks can reference it
bastion.export_security_group("BastionSG-Production")
```

## Trunnel CLI

The Trunnel CLI makes it easy to find the bastion host and connect to your RDS database via an encrypted SSM tunnel,
and to fetch connection credentials stored in AWS Secrets Manager. Resources are located by tag `key=value` pairs.

### Installation

Before beginning, you must first have the following installed:

- AWS CLI v2
- SSM Session Manager Plugin

Install into your project's development dependencies (for example using `uv`):

```bash
uv add --dev "trunnel-cli @ git+https://github.com/developmentseed/trunnel#subdirectory=packages/trunnel-cli"
```

### trunnel connect

Opens an encrypted SSM port-forward tunnel to a private RDS instance.

```bash
$ trunnel connect --rds-key Service --rds-value payments-api --reconnect

🔍 Searching AWS...
Select a Bastion:
 • i-0abcd1234efgh5678 - Production-Bastion
 • i-09876fedcba54321 - Staging-Bastion

Enter Bastion ID: i-0abcd1234efgh5678

🚎 Trunnel Active: localhost:5432 -> payments-api-db.cluster.aws.com
🔗 payments-api-db via Production-Bastion (i-0abcd1234efgh5678)

Starting session with SessionId: developer-0123456789abcdef
Port 5432 opened for session developer-0123456789abcdef.
Waiting for connections...
```

```bash
$ trunnel connect --help

Usage: trunnel connect [OPTIONS]

  Securely bore a tunnel to RDS via Trunnel.

Options:
  --bastion-key TEXT    Tag key for Bastion.  [env var: TRUNNEL_CONNECT_BASTION_KEY; default: Role]
  --bastion-value TEXT  Tag value for Bastion.  [env var: TRUNNEL_CONNECT_BASTION_VALUE; default: Bastion]
  --rds-key TEXT        Tag key for RDS.  [env var: TRUNNEL_CONNECT_RDS_KEY; required]
  --rds-value TEXT      Tag value for RDS.  [env var: TRUNNEL_CONNECT_RDS_VALUE; required]
  --local-port INTEGER  [env var: TRUNNEL_CONNECT_LOCAL_PORT; default: 5432]
  --profile TEXT        AWS CLI profile.  [env var: TRUNNEL_CONNECT_PROFILE]
  --reconnect           Auto-retry on disconnect.  [env var: TRUNNEL_CONNECT_RECONNECT]
  --help                Show this message and exit.
```

### trunnel secrets

Looks up an AWS Secrets Manager secret by tag and prints its value to stdout.

```bash
$ trunnel secrets --secret-key Stack --secret-value payments-api

🔍 Searching AWS Secrets Manager...
{"username":"app","password":"s3cr3t","host":"payments-api-db.cluster.aws.com","port":5432}
```

If multiple secrets match the tag filter, Trunnel prompts you to choose:

```bash
Select a Secret:
 • payments-api/db-credentials - Primary database credentials
 • payments-api/readonly-credentials - Read-only replica credentials

Enter Secret ID: payments-api/db-credentials
```

```bash
$ trunnel secrets --help

Usage: trunnel secrets [OPTIONS]

  Fetch and print a Secrets Manager secret by tag.

Options:
  --secret-key TEXT    Tag key to filter secrets.  [env var: TRUNNEL_SECRETS_SECRET_KEY; required]
  --secret-value TEXT  Tag value to filter secrets.  [env var: TRUNNEL_SECRETS_SECRET_VALUE; required]
  --profile TEXT    AWS CLI profile.  [env var: TRUNNEL_SECRETS_PROFILE]
  --help            Show this message and exit.
```

### Environment variables

All options can be set via environment variables. Each subcommand has its own prefix:

| Subcommand         | Prefix                  | Example                              |
|--------------------|-------------------------|--------------------------------------|
| `trunnel connect`  | `TRUNNEL_CONNECT_`      | `TRUNNEL_CONNECT_RDS_KEY=Service`    |
| `trunnel secrets`  | `TRUNNEL_SECRETS_`      | `TRUNNEL_SECRETS_SECRET_KEY=Stack`   |

You might consider using [direnv](https://direnv.net/) to set these per project. For example,

```bash
# .envrc
export TRUNNEL_CONNECT_RDS_KEY=Service
export TRUNNEL_CONNECT_RDS_VALUE=payments-api
export TRUNNEL_SECRETS_SECRET_KEY=Stack
export TRUNNEL_SECRETS_SECRET_VALUE=payments-api
```

[East Side Trolley Tunnel]: https://en.wikipedia.org/wiki/East_Side_Trolley_Tunnel
