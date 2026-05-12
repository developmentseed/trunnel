# trunnel-cli

> Automated SSM tunneling and credential lookup for private RDS instances.

`trunnel-cli` is the developer-facing component of the Trunnel project. It automates the discovery of Bastion hosts,
RDS instances, and Secrets Manager credentials via AWS tags, then establishes an encrypted SSM tunnel so local database
clients can connect to private RDS instances.

## Installation

**Prerequisites**:

- AWS CLI v2
- SSM Session Manager Plugin
- Python 3.12+

To add to your project using `uv`,

```bash
uv add --dev "trunnel-cli @ git+https://github.com/developmentseed/trunnel#subdirectory=packages/trunnel-cli"
```

## Commands

### `trunnel connect`

Opens an encrypted SSM port-forward tunnel to a private RDS instance. Resources are located by tag `key=value` pairs.

```bash
trunnel connect --rds-key Service --rds-value payments-api
```

| Option | Default | Env var |
|---|---|---|
| `--bastion-key` | `Role` | `TRUNNEL_CONNECT_BASTION_KEY` |
| `--bastion-value` | `Bastion` | `TRUNNEL_CONNECT_BASTION_VALUE` |
| `--rds-key` | *(required)* | `TRUNNEL_CONNECT_RDS_KEY` |
| `--rds-value` | *(required)* | `TRUNNEL_CONNECT_RDS_VALUE` |
| `--local-port` | `5432` | `TRUNNEL_CONNECT_LOCAL_PORT` |
| `--profile` | | `TRUNNEL_CONNECT_PROFILE` |
| `--reconnect` | | `TRUNNEL_CONNECT_RECONNECT` |

### `trunnel secrets`

Looks up an AWS Secrets Manager secret by tag and prints its `SecretString` to stdout. If multiple secrets match,
you are prompted to choose one by name.

```bash
trunnel secrets --secret-key Stack --secret-value payments-api
```

The output is suitable for piping into tools like `jq`:

```bash
trunnel secrets --secret-key Stack --secret-value payments-api | jq '.password'
```

| Option | Default | Env var |
|---|---|---|
| `--secret-key` | *(required)* | `TRUNNEL_SECRETS_SECRET_KEY` |
| `--secret-value` | *(required)* | `TRUNNEL_SECRETS_SECRET_VALUE` |
| `--profile` | | `TRUNNEL_SECRETS_PROFILE` |

## Environment variables

All options can be configured via environment variables. Each subcommand uses its own prefix
(`TRUNNEL_CONNECT_` or `TRUNNEL_SECRETS_`), which makes it easy to use [direnv](https://direnv.net/) per project:

```bash
# .envrc
export TRUNNEL_CONNECT_RDS_KEY=Service
export TRUNNEL_CONNECT_RDS_VALUE=payments-api
export TRUNNEL_SECRETS_SECRET_KEY=Stack
export TRUNNEL_SECRETS_SECRET_VALUE=payments-api
```
