# GitHub publication metadata

Use this metadata when the repository has been created on GitHub and the complete source history is
available.

**Description**

> Read-only OpenAI agent that turns bounded Amazon ECS and CloudWatch evidence into an auditable,
> evidence-backed incident RCA.

**Topics**

`aws`, `openai`, `sre`, `devops`, `incident-response`, `ecs`, `cloudwatch`, `ai-agents`

After authenticating GitHub CLI in the real checkout:

```bash
gh repo edit --description "Read-only OpenAI agent that turns bounded Amazon ECS and CloudWatch evidence into an auditable, evidence-backed incident RCA." \
  --add-topic aws \
  --add-topic openai \
  --add-topic sre \
  --add-topic devops \
  --add-topic incident-response \
  --add-topic ecs \
  --add-topic cloudwatch \
  --add-topic ai-agents
```

Before changing repository visibility:

1. Run `gitleaks git --redact` from the real checkout with all branches/tags fetched.
2. Remove or rewrite any secret from every affected ref and rotate it before continuing.
3. Push to a private repository first and wait for CI and secret scanning to pass.
4. Enable private vulnerability reporting and branch protection for the CI and secret-scan checks.
5. Add workflow badges only after the workflows have a successful run on the default branch.
