output "vpc_id" {
  description = "ID of the service VPC."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets used by the Fargate service."
  value       = [for subnet in aws_subnet.public : subnet.id]
}

output "service_security_group_id" {
  description = "ID of the Fargate service security group."
  value       = aws_security_group.service.id
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster."
  value       = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  description = "Name of the ECS Fargate service."
  value       = aws_ecs_service.service.name
}

output "task_definition_arn" {
  description = "ARN of the active ECS task definition revision."
  value       = aws_ecs_task_definition.service.arn
}

output "cloudwatch_log_group_name" {
  description = "CloudWatch Logs group receiving the container JSON logs."
  value       = aws_cloudwatch_log_group.service.name
}

output "triage_agent_read_only_policy_arn" {
  description = "ARN of the least-privilege IAM policy to attach to the triage agent identity."
  value       = aws_iam_policy.triage_agent_read_only.arn
}
