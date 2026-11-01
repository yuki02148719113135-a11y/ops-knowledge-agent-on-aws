output "region" {
  value = var.region
}

output "db_name" {
  value = var.db_name
}

output "cluster_arn" {
  value = aws_rds_cluster.this.arn
}

output "cluster_identifier" {
  value = aws_rds_cluster.this.cluster_identifier
}

output "admin_secret_arn" {
  description = "管理者（クエリエディタ・調査用）"
  value       = aws_rds_cluster.this.master_user_secret[0].secret_arn
}

output "agent_secret_arn" {
  description = "読み取り専用（エージェント・MCP サーバー用）"
  value       = aws_secretsmanager_secret.agent.arn
}

output "kb_secret_arn" {
  description = "Knowledge Bases 専用"
  value       = aws_secretsmanager_secret.kb.arn
}

output "docs_bucket" {
  value = aws_s3_bucket.docs.bucket
}

output "knowledge_base_id" {
  value = aws_bedrockagent_knowledge_base.this.id
}

output "data_source_id" {
  value = aws_bedrockagent_data_source.runbooks.data_source_id
}

output "agent_function_name" {
  value = aws_lambda_function.agent.function_name
}

output "memory_table_name" {
  value = aws_dynamodb_table.memory.name
}

output "embedding_model_id" {
  value = var.embedding_model_id
}
