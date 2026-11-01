variable "region" {
  description = "デプロイ先リージョン（Bedrock の Nova Pro / Titan Embeddings V2 が使えるリージョン）"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "リソース名の接頭辞"
  type        = string
  default     = "ops-agent"
}

variable "db_name" {
  description = "Aurora に作るデータベース名"
  type        = string
  default     = "opsdb"
}

variable "aurora_engine_version" {
  description = "Aurora PostgreSQL のバージョン（0 ACU の自動一時停止は 16.3 以上が必要）"
  type        = string
  default     = "16.6"
}

variable "aurora_min_acu" {
  description = "Serverless v2 の最小 ACU。0 にすると未使用時に自動で一時停止して課金がほぼ止まる"
  type        = number
  default     = 0
}

variable "aurora_max_acu" {
  description = "Serverless v2 の最大 ACU"
  type        = number
  default     = 2
}

variable "aurora_auto_pause_seconds" {
  description = "最小 ACU が 0 のとき、何秒アイドルで一時停止するか（300〜86400）"
  type        = number
  default     = 600
}

variable "chat_model_id" {
  description = "エージェントが使う会話モデル（Converse API の modelId。推論プロファイル ID も可）"
  type        = string
  default     = "us.amazon.nova-pro-v1:0"
}

variable "embedding_model_id" {
  description = "Knowledge Base の埋め込みモデル"
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "embedding_dimensions" {
  description = "埋め込みベクトルの次元数（Titan Text Embeddings V2 の既定は 1024）"
  type        = number
  default     = 1024
}

variable "python_bin" {
  description = "DB 初期化スクリプトを実行する Python コマンド"
  type        = string
  default     = "python3"
}
