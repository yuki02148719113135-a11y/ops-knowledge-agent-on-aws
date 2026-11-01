############################################
# 会話履歴（エージェントの記憶）
############################################
resource "aws_dynamodb_table" "memory" {
  name         = "${local.name}-conversations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "created_at"

  attribute {
    name = "session_id"
    type = "S"
  }
  attribute {
    name = "created_at"
    type = "N"
  }

  # 古い会話は自動で消える
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

############################################
# エージェント Lambda
############################################
locals {
  # 推論プロファイル ID（例: us.amazon.nova-pro-v1:0）から基盤モデル ID を取り出す
  chat_base_model_id = replace(var.chat_model_id, "/^(us|eu|apac|jp|au|global)\\./", "")
  chat_uses_profile  = local.chat_base_model_id != var.chat_model_id

  chat_model_resources = concat(
    ["arn:${local.partition}:bedrock:*::foundation-model/${local.chat_base_model_id}"],
    local.chat_uses_profile ? ["arn:${local.partition}:bedrock:${var.region}:${local.account_id}:inference-profile/${var.chat_model_id}"] : []
  )

  agent_function_name = "${local.name}-agent"
}

data "archive_file" "agent" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/agent"
  output_path = "${path.module}/.build/agent.zip"
  excludes    = ["__pycache__"]
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "agent" {
  name               = "${local.name}-agent"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "agent_logs" {
  role       = aws_iam_role.agent.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "agent" {
  statement {
    sid       = "ChatModel"
    actions   = ["bedrock:InvokeModel"]
    resources = local.chat_model_resources
  }
  statement {
    sid       = "RetrieveRunbooks"
    actions   = ["bedrock:Retrieve"]
    resources = [aws_bedrockagent_knowledge_base.this.arn]
  }
  statement {
    sid       = "QueryIncidents"
    actions   = ["rds-data:ExecuteStatement"]
    resources = [aws_rds_cluster.this.arn]
  }
  statement {
    sid       = "ReadOnlyDbSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.agent.arn]
  }
  statement {
    sid       = "Memory"
    actions   = ["dynamodb:Query", "dynamodb:BatchWriteItem", "dynamodb:PutItem"]
    resources = [aws_dynamodb_table.memory.arn]
  }
}

resource "aws_iam_role_policy" "agent" {
  name   = "agent-access"
  role   = aws_iam_role.agent.id
  policy = data.aws_iam_policy_document.agent.json
}

resource "aws_cloudwatch_log_group" "agent" {
  name              = "/aws/lambda/${local.agent_function_name}"
  retention_in_days = 7
}

resource "aws_lambda_function" "agent" {
  function_name    = local.agent_function_name
  role             = aws_iam_role.agent.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.agent.output_path
  source_code_hash = data.archive_file.agent.output_base64sha256
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      MODEL_ID          = var.chat_model_id
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.this.id
      CLUSTER_ARN       = aws_rds_cluster.this.arn
      DB_SECRET_ARN     = aws_secretsmanager_secret.agent.arn
      DB_NAME           = var.db_name
      MEMORY_TABLE      = aws_dynamodb_table.memory.name
      HISTORY_TURNS     = "6"
      MEMORY_TTL_DAYS   = "7"
      SEARCH_TYPE       = "HYBRID"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.agent,
    aws_iam_role_policy_attachment.agent_logs,
    aws_iam_role_policy.agent,
  ]
}
