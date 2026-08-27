# Security policy

## Read-only design

The incident triage agent is intentionally incapable of mutating AWS resources. Its runtime code
calls only five AWS APIs:

| Allowed action | Purpose |
| --- | --- |
| `ecs:DescribeClusters` | Read cluster health |
| `ecs:DescribeServices` | Read service, deployment, and event health |
| `ecs:ListTasks` | Find tasks belonging to the configured service |
| `ecs:DescribeTasks` | Read bounded task/container status |
| `logs:FilterLogEvents` | Read bounded events from the configured log group |

The Terraform policy scopes those actions to the demo cluster, service, tasks, and log group. ECS
requires `Resource: "*"` for `ListTasks`; that statement uses the supported `ecs:cluster` condition,
and the collector always supplies the configured `serviceName`. The
OpenAI model receives three custom tools, all implemented by these read-only calls or local pattern
analysis. It never receives boto3 clients, shell access, Terraform, AWS CLI, ECS Exec, or a generic
HTTP tool.

CI tests parse the collector source and IAM policy and fail if the approved API/action sets change.
This protects the repository contract, but effective permissions still depend on every policy
attached to the real user or role. Verify the complete identity with IAM policy simulation or Access
Analyzer before use.

## Data handling

CloudWatch messages and operator context can contain secrets or sensitive operational data. The
agent redacts common labeled credentials, bearer tokens, AWS access-key IDs, OpenAI-style keys, and
private-key blocks before model submission. Inputs and pages are bounded.

Redaction is best effort. Do not log credentials. Review `--collect-only` output before enabling
model analysis, follow your organization's OpenAI data-handling requirements, and review generated
reports before sharing. The ignored `incidents/` directory should be treated as sensitive.

## Safe deployment checklist

- Use a dedicated IAM role with only the generated policy; do not reuse an administrator role.
- Prefer short-lived credentials and restrict who can assume the role.
- Confirm the target cluster, service, log group, account, and region before every run.
- Start with `--collect-only` and a narrow lookback.
- Restrict demo ingress to a trusted `/32` or private network.
- Never deploy the intentional `/crash` endpoint as part of a production service.
- Keep Terraform state out of Git and store real shared state in an encrypted, locked backend.
- Run Gitleaks against the complete history before making any GitHub repository public.

## Reporting a vulnerability

Do not open a public issue for suspected credential exposure or an exploitable vulnerability. Use
GitHub's private vulnerability reporting feature after it is enabled for the repository. Include the
affected commit, impact, reproduction steps with sanitized data, and a proposed fix if available.

If private reporting has not yet been enabled, contact the repository owner privately through their
published GitHub contact channel. Do not include live credentials in the report. Rotate any exposed
credential immediately; deleting it from the latest commit is not sufficient because Git history
and forks may retain it.

## Supported versions

Security fixes are applied to the default branch. No released compatibility branches are currently
maintained.
