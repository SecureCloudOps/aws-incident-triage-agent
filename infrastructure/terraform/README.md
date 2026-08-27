# Buggy Service on ECS Fargate

This Terraform root creates:

- a VPC with public subnets across at least two availability zones;
- an internet gateway and public route table;
- a security group for direct access to port `8000`;
- an ECS cluster with Container Insights;
- an ECS task execution IAM role;
- a Fargate task definition and service; and
- a CloudWatch log group for the application's structured JSON logs.
- a least-privilege, read-only IAM policy for the triage agent.

The design intentionally assigns public IP addresses to the tasks because it does not include a NAT gateway or load balancer. Ingress defaults to a non-routable documentation `/32`, so deployment requires an explicit trusted CIDR. ECS task public IPs are ephemeral, so add an Application Load Balancer before treating this as a stable production endpoint.

## Prerequisites

Publish the `buggy-service` image to a registry reachable by ECS. For ECR, authenticate, build for the configured task architecture, and push the image. Prefer passing an immutable image digest to Terraform.

Install Terraform `1.14.3`. The configuration and AWS provider are pinned, and the committed lock
file records provider checksums.

## Deploy

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit container_image and allowed_ingress_cidrs.

terraform init
terraform fmt -check
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

AWS credentials must be configured in your shell or through your normal AWS identity tooling. Terraform state is local unless you add a remote backend.

Local state is acceptable only for this disposable demo. For shared or long-lived use, configure an
encrypted remote backend with locking before the first apply. Never commit state, plan files, or
`terraform.tfvars`.

## Find a running task's public IP

The service does not have a load balancer, so find the task ENI and its public IP through the ECS or EC2 console. Then test it with:

```bash
curl http://<TASK_PUBLIC_IP>:8000/health
curl http://<TASK_PUBLIC_IP>:8000/crash
```

The `/crash` request emits a structured `ERROR` event to the `/ecs/buggy-service` CloudWatch log group.

## Triage agent IAM

The `triage_agent_read_only_policy_arn` output identifies the policy to attach to the user or role
running `triage-agent/agent.py`. It grants only ECS describe/list access scoped to this cluster,
service, and tasks plus CloudWatch Logs read access scoped to this service's log group. Its exact
actions are `ecs:DescribeClusters`, `ecs:DescribeServices`, `ecs:ListTasks`, `ecs:DescribeTasks`, and
`logs:FilterLogEvents`. It contains no wildcard or mutation action.

ECS does not support a cluster or service ARN in the `ListTasks` resource element, so that one
statement uses the required wildcard resource with an `ecs:cluster` condition. The collector also
always supplies the configured `serviceName`; callers cannot override it through a model tool.

## Teardown

Review the destroy plan before removing the disposable demo:

```bash
terraform plan -destroy -out=tfplan-destroy
terraform apply tfplan-destroy
```

Confirm that the ECS service, network resources, log group, and triage IAM policy were removed. ECR
images are not created by this Terraform root and must be managed separately.
