############################################
# 文書置き場（S3）
############################################
resource "aws_s3_bucket" "docs" {
  bucket        = "${local.name}-docs-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "docs" {
  bucket                  = aws_s3_bucket.docs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# knowledge/ 配下をそのままアップロード（runbooks/ と drafts/）
resource "aws_s3_object" "docs" {
  for_each = fileset("${path.module}/../knowledge", "**/*.md")

  bucket       = aws_s3_bucket.docs.id
  key          = each.value
  source       = "${path.module}/../knowledge/${each.value}"
  etag         = filemd5("${path.module}/../knowledge/${each.value}")
  content_type = "text/markdown; charset=utf-8"
}

############################################
# Knowledge Base 用の IAM ロール
############################################
locals {
  embedding_model_arn = "arn:${local.partition}:bedrock:${var.region}::foundation-model/${var.embedding_model_id}"
}

data "aws_iam_policy_document" "kb_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:bedrock:${var.region}:${local.account_id}:knowledge-base/*"]
    }
  }
}

resource "aws_iam_role" "kb" {
  name               = "${local.name}-kb"
  assume_role_policy = data.aws_iam_policy_document.kb_trust.json
}

data "aws_iam_policy_document" "kb" {
  statement {
    sid       = "Embedding"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.embedding_model_arn]
  }
  statement {
    sid       = "DescribeCluster"
    actions   = ["rds:DescribeDBClusters"]
    resources = [aws_rds_cluster.this.arn]
  }
  statement {
    sid       = "DataApi"
    actions   = ["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"]
    resources = [aws_rds_cluster.this.arn]
  }
  statement {
    sid       = "KbDbSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.kb.arn]
  }
  statement {
    sid       = "ListDocs"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.docs.arn]
  }
  statement {
    sid       = "ReadDocs"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.docs.arn}/*"]
  }
}

resource "aws_iam_role_policy" "kb" {
  name   = "kb-access"
  role   = aws_iam_role.kb.id
  policy = data.aws_iam_policy_document.kb.json
}

############################################
# Knowledge Base（ベクトルストア = Aurora）
############################################
resource "aws_bedrockagent_knowledge_base" "this" {
  name     = "${local.name}-runbooks"
  role_arn = aws_iam_role.kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
    }
  }

  storage_configuration {
    type = "RDS"
    rds_configuration {
      resource_arn           = aws_rds_cluster.this.arn
      credentials_secret_arn = aws_secretsmanager_secret.kb.arn
      database_name          = var.db_name
      table_name             = "bedrock_integration.document_chunks"
      field_mapping {
        primary_key_field = "id"
        vector_field      = "embedding"
        text_field        = "chunks"
        metadata_field    = "metadata"
      }
    }
  }

  depends_on = [
    terraform_data.db_setup,
    aws_iam_role_policy.kb,
  ]
}

# 取り込むのは runbooks/ だけ。drafts/（下書き）はエージェントに見せない
resource "aws_bedrockagent_data_source" "runbooks" {
  knowledge_base_id    = aws_bedrockagent_knowledge_base.this.id
  name                 = "runbooks"
  data_deletion_policy = "RETAIN"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = aws_s3_bucket.docs.arn
      inclusion_prefixes = ["runbooks/"]
    }
  }
}
