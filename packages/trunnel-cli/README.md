# trunnel-cli

> Automated SSM tunneling and credential lookup for private RDS instances.

`trunnel-cli` is the developer-facing component of the Trunnel project. It automates the discovery of Bastion hosts, RDS
instances, and Secrets Manager credentials via AWS tags, then establishes an encrypted SSM tunnel so local database
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

| Option            | Default      | Env var                         |
| ----------------- | ------------ | ------------------------------- |
| `--bastion-key`   | `Role`       | `TRUNNEL_CONNECT_BASTION_KEY`   |
| `--bastion-value` | `Bastion`    | `TRUNNEL_CONNECT_BASTION_VALUE` |
| `--rds-key`       | _(required)_ | `TRUNNEL_CONNECT_RDS_KEY`       |
| `--rds-value`     | _(required)_ | `TRUNNEL_CONNECT_RDS_VALUE`     |
| `--local-port`    | `5432`       | `TRUNNEL_CONNECT_LOCAL_PORT`    |
| `--profile`       |              | `TRUNNEL_CONNECT_PROFILE`       |
| `--reconnect`     |              | `TRUNNEL_CONNECT_RECONNECT`     |

### `trunnel secrets`

Looks up an AWS Secrets Manager secret by tag and prints its `SecretString` to stdout. If multiple secrets match, you
are prompted to choose one by name.

```bash
trunnel secrets --secret-key Stack --secret-value payments-api
```

The output is suitable for piping into tools like `jq`:

```bash
trunnel secrets --secret-key Stack --secret-value payments-api | jq '.password'
```

| Option           | Default      | Env var                        |
| ---------------- | ------------ | ------------------------------ |
| `--secret-key`   | _(required)_ | `TRUNNEL_SECRETS_SECRET_KEY`   |
| `--secret-value` | _(required)_ | `TRUNNEL_SECRETS_SECRET_VALUE` |
| `--profile`      |              | `TRUNNEL_SECRETS_PROFILE`      |

### `trunnel psql`

Looks up credentials from Secrets Manager, opens an SSM tunnel in the background, and launches `psql`. Requires `psql`
to be installed. The RDS and secret tags can differ — useful when a shared database has per-user secrets.

```bash
trunnel psql \
  --rds-key Stack --rds-value payments-api \
  --secret-key Stack --secret-value payments-api-user-alice
```

If port 5432 is already in use locally (e.g. a local Postgres), use `--local-port` to pick a free port:

```bash
trunnel psql --rds-key Stack --rds-value payments-api \
             --secret-key Stack --secret-value payments-api-user-alice \
             --local-port 15432
```

| Option            | Default      | Env var                      |
| ----------------- | ------------ | ---------------------------- |
| `--bastion-key`   | `Role`       | `TRUNNEL_PSQL_BASTION_KEY`   |
| `--bastion-value` | `Bastion`    | `TRUNNEL_PSQL_BASTION_VALUE` |
| `--rds-key`       | _(required)_ | `TRUNNEL_PSQL_RDS_KEY`       |
| `--rds-value`     | _(required)_ | `TRUNNEL_PSQL_RDS_VALUE`     |
| `--secret-key`    | _(required)_ | `TRUNNEL_PSQL_SECRET_KEY`    |
| `--secret-value`  | _(required)_ | `TRUNNEL_PSQL_SECRET_VALUE`  |
| `--local-port`    | `5432`       | `TRUNNEL_PSQL_LOCAL_PORT`    |
| `--profile`       |              | `TRUNNEL_PSQL_PROFILE`       |

## Environment variables

All options can be configured via environment variables. Each subcommand uses its own prefix, which makes it easy to use
[direnv](https://direnv.net/) per project:

```bash
# .envrc
export TRUNNEL_CONNECT_RDS_KEY=Stack
export TRUNNEL_CONNECT_RDS_VALUE=payments-api
export TRUNNEL_PSQL_RDS_KEY=Stack
export TRUNNEL_PSQL_RDS_VALUE=payments-api
export TRUNNEL_PSQL_SECRET_KEY=Stack
export TRUNNEL_PSQL_SECRET_VALUE=payments-api-user-alice
```
