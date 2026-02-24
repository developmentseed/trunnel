# trunnel-cli

> Automated SSM tunneling for private RDS instances.

`trunnel-cli` is the developer-facing component of the Trunnel project. It automates the discovery of Bastion hosts and
RDS instances via AWS tags and establishes an encrypted SSM tunnel to allow local database clients to connect to private
RDS instances.

## Installation

**Prerequisites**:

- AWS CLI v2
- SSM Session Manager Plugin
- Python 3.12+

To add to your project using `uv`,

```bash
uv add --group deploy "trunnel-cli @ git+https://github.com/developmentseed/trunnel#subdirectory=packages/trunnel-cli"
```
