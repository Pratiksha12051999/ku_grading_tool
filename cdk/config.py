# ku_essay_grading/config.py
from aws_cdk import aws_dynamodb as dynamodb, aws_apigateway as apigateway, RemovalPolicy

class EnvironmentConfig:
    """Environment-specific configuration for KU Essay Grading Stack"""

    CONFIGS = {
        "dev": {
            "memory_size": {
                "ku_rubric_generation_lambda": 1024,
                "ku_essay_grading_lambda": 1024,
            },
            "timeout": {
                "ku_rubric_generation_lambda": 300,
                "ku_essay_grading_lambda": 300,
            },
            "table_settings": {
                "billing_mode": dynamodb.BillingMode.PAY_PER_REQUEST,
                "removal_policy": RemovalPolicy.DESTROY,
            },
            "api_settings": {
                "logging_level": apigateway.MethodLoggingLevel.INFO,
                "data_trace_enabled": True,
                "metrics_enabled": True,
            },
            "bedrock_settings": {
                "model_id": "amazon.nova-pro-v1:0",
                "max_tokens": 4096,
                "temperature": 0.7,
            }
        },
        "test": {
            "memory_size": {
                "ku_rubric_generation_lambda": 1024,
                "ku_essay_grading_lambda": 1024,
            },
            "timeout": {
                "ku_rubric_generation_lambda": 600,
                "ku_essay_grading_lambda": 600,
            },
            "table_settings": {
                "billing_mode": dynamodb.BillingMode.PAY_PER_REQUEST,
                "removal_policy": RemovalPolicy.RETAIN,
            },
            "api_settings": {
                "logging_level": apigateway.MethodLoggingLevel.INFO,
                "data_trace_enabled": True,
                "metrics_enabled": True,
            },
            "bedrock_settings": {
                "model_id": "amazon.nova-pro-v1:0",
                "max_tokens": 4096,
                "temperature": 0.5,
            }
        },
        "prod": {
            "memory_size": {
                "ku_rubric_generation_lambda": 1024,
                "ku_essay_grading_lambda": 1024,
            },
            "timeout": {
                "ku_rubric_generation_lambda": 300,
                "ku_essay_grading_lambda": 300,
            },
            "table_settings": {
                "billing_mode": dynamodb.BillingMode.PAY_PER_REQUEST,
                "removal_policy": RemovalPolicy.RETAIN,
            },
            "api_settings": {
                "logging_level": apigateway.MethodLoggingLevel.ERROR,
                "data_trace_enabled": False,
                "metrics_enabled": True,
            },
            "bedrock_settings": {
                "model_id": "amazon.nova-pro-v1:0",
                "max_tokens": 4096,
                "temperature": 0.3,
            }
        }
    }

    @classmethod
    def get_config(cls, env_name: str):
        """Get configuration for specified environment"""
        return cls.CONFIGS.get(env_name, cls.CONFIGS["dev"])