############################################
# 共通
############################################
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

resource "random_id" "suffix" {
  byte_length = 3
}

locals {
  name       = "${var.project}-${random_id.suffix.hex}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}

############################################
# ネットワーク（デフォルト VPC を利用）
# Lambda / Bedrock / スクリプトはすべて RDS Data API（HTTPS）経由で接続するので、
# Aurora への受信ルールも NAT Gateway も作らない。
############################################
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_db_subnet_group" "this" {
  name       = local.name
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "Aurora: no inbound rules. Accessed only through the RDS Data API."
  vpc_id      = data.aws_vpc.default.id
}

############################################
# Aurora PostgreSQL Serverless v2
############################################
resource "aws_rds_cluster" "this" {
  cluster_identifier = local.name
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"
  engine_version     = var.aurora_engine_version
  database_name      = var.db_name

  # 管理者パスワードは RDS が Secrets Manager で管理（Terraform の state に残らない）
  master_username             = "postgres_admin"
  manage_master_user_password = true

  # Data API を有効化（Bedrock Knowledge Bases の Aurora 連携に必須）
  enable_http_endpoint = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  storage_encrypted      = true

  serverlessv2_scaling_configuration {
    min_capacity             = var.aurora_min_acu
    max_capacity             = var.aurora_max_acu
    seconds_until_auto_pause = var.aurora_min_acu == 0 ? var.aurora_auto_pause_seconds : null
  }

  # 検証用なので削除しやすくしておく
  skip_final_snapshot = true
  deletion_protection = false
  apply_immediately   = true
}

resource "aws_rds_cluster_instance" "writer" {
  identifier          = "${local.name}-writer"
  cluster_identifier  = aws_rds_cluster.this.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.this.engine
  engine_version      = aws_rds_cluster.this.engine_version
  publicly_accessible = false
}

############################################
# 用途別の DB ユーザーとシークレット
#   bedrock_kb     : Knowledge Bases 専用（bedrock_integration スキーマのみ）
#   agent_readonly : エージェント / MCP 用（業務テーブルの SELECT のみ）
############################################
resource "random_password" "kb" {
  length  = 32
  special = false
}

resource "random_password" "agent" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "kb" {
  name                    = "${local.name}/db/bedrock-kb"
  description             = "Aurora user for Bedrock Knowledge Bases"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "kb" {
  secret_id = aws_secretsmanager_secret.kb.id
  secret_string = jsonencode({
    username = "bedrock_kb"
    password = random_password.kb.result
  })
}

resource "aws_secretsmanager_secret" "agent" {
  name                    = "${local.name}/db/agent-readonly"
  description             = "Read-only Aurora user for the agent and the MCP server"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "agent" {
  secret_id = aws_secretsmanager_secret.agent.id
  secret_string = jsonencode({
    username = "agent_readonly"
    password = random_password.agent.result
  })
}

############################################
# DB 初期化（拡張・スキーマ・ユーザー・権限・サンプルデータ）
# Knowledge Base の作成前にテーブルが必要なので、apply の途中でスクリプトを実行する。
############################################
resource "terraform_data" "db_setup" {
  triggers_replace = [
    aws_rds_cluster.this.arn,
    filesha256("${path.module}/../sql/schema.sql"),
    filesha256("${path.module}/../sql/sample_data.sql"),
    filesha256("${path.module}/../scripts/setup_db.py"),
  ]

  depends_on = [
    aws_rds_cluster_instance.writer,
    aws_secretsmanager_secret_version.kb,
    aws_secretsmanager_secret_version.agent,
  ]

  provisioner "local-exec" {
    command = "${var.python_bin} ${path.module}/../scripts/setup_db.py"
    environment = {
      OPS_REGION           = var.region
      OPS_CLUSTER_ARN      = aws_rds_cluster.this.arn
      OPS_ADMIN_SECRET_ARN = aws_rds_cluster.this.master_user_secret[0].secret_arn
      OPS_KB_SECRET_ARN    = aws_secretsmanager_secret.kb.arn
      OPS_AGENT_SECRET_ARN = aws_secretsmanager_secret.agent.arn
      OPS_DB_NAME          = var.db_name
      OPS_EMBEDDING_DIM    = tostring(var.embedding_dimensions)
    }
  }
}
