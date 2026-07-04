terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS Region"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique name for the S3 bucket to store GTFS data"
}

# S3 Bucket for GTFS Realtime data
resource "aws_s3_bucket" "gtfs_data" {
  bucket        = var.bucket_name
  force_destroy = false
}

# Block all public access to the bucket
resource "aws_s3_bucket_public_access_block" "block_public" {
  bucket = aws_s3_bucket.gtfs_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle rule to archive or clean up old data
resource "aws_s3_bucket_lifecycle_configuration" "lifecycle" {
  bucket = aws_s3_bucket.gtfs_data.id

  rule {
    id     = "expire_old_feeds"
    status = "Enabled"

    expiration {
      days = 365 # Keep data for 1 year
    }
  }
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "gtfs_collector_lambda_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for S3 and CloudWatch Logs
resource "aws_iam_role_policy" "lambda_policy" {
  name = "gtfs_collector_lambda_policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl"
        ]
        Resource = "${aws_s3_bucket.gtfs_data.arn}/*"
      }
    ]
  })
}

# Archive lambda code
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/lambda_function.py"
  output_path = "${path.module}/lambda.zip"
}

# Lambda Function
resource "aws_lambda_function" "gtfs_collector" {
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  function_name    = "gtfs-realtime-collector"
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.10"
  timeout          = 60
  memory_size      = 128

  environment {
    variables = {
      BUCKET_NAME = aws_s3_bucket.gtfs_data.id
    }
  }
}

# EventBridge Rule (Cron: every minute)
resource "aws_cloudwatch_event_rule" "cron" {
  name                = "gtfs-collector-scheduler"
  description         = "Trigger GTFS Realtime collector Lambda every minute"
  schedule_expression = "rate(1 minute)"
}

# Target linking EventBridge to Lambda
resource "aws_cloudwatch_event_target" "trigger_lambda" {
  rule      = aws_cloudwatch_event_rule.cron.name
  target_id = "TriggerGTFSCollector"
  arn       = aws_lambda_function.gtfs_collector.arn
}

# Permission for EventBridge to call Lambda
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.gtfs_collector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cron.arn
}
