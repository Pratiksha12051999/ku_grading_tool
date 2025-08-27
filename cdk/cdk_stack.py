from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_dynamodb as dynamodb,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_s3 as s3,
    CfnOutput,
    RemovalPolicy,
    Duration,
    Tags,
)
from constructs import Construct
import os
from config import EnvironmentConfig


class KUEssayGradingStack(Stack):
    """AWS CDK Stack for KU Essay Grading System"""

    def __init__(self, scope: Construct, construct_id: str, env_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.config = EnvironmentConfig.get_config(env_name)

        # Create resources
        self.create_dynamodb_tables()
        self.create_s3_buckets()
        self.create_iam_roles()
        self.create_lambda_functions()
        self.create_api_gateway()
        self.create_outputs()

        # Add environment tags
        Tags.of(self).add("Environment", env_name)
        Tags.of(self).add("Project", "KU-Essay-Grading")

    def create_dynamodb_tables(self):
        """Create DynamoDB tables"""
        # ku_grading_rubrics table with composite key structure
        self.rubrics_table = dynamodb.Table(
            self, "KURubricsTable",
            table_name="ku_grading_rubrics",
            partition_key=dynamodb.Attribute(
                name="essay_type",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="content_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=self.config["table_settings"]["billing_mode"],
            removal_policy=self.config["table_settings"]["removal_policy"],
            deletion_protection=self.env_name == "prod"
        )

    def create_s3_buckets(self):
        """Create S3 buckets"""
        # Output grading bucket (matching existing bucket name)
        self.output_grading_bucket = s3.Bucket(
            self, "KUOutputGradingBucket",
            # bucket_name="ku-grading-output-bucket",
            removal_policy=self.config["table_settings"]["removal_policy"],
            auto_delete_objects=self.env_name != "prod",
            versioned=self.env_name == "prod",
            public_read_access=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL
        )

    def create_iam_roles(self):
        """Create IAM roles for Lambda functions matching existing configuration"""

        # Rubric Generation Lambda Role (matches ku_rubric_lambda_execution_role)
        self.rubric_lambda_role = iam.Role(
            self, "KURubricLambdaExecutionRole",
            role_name="ku_rubric_lambda_execution_role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for ku_rubric_generation_lambda",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        # Add Bedrock permissions (exact match)
        self.rubric_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=["arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0"]
            )
        )

        # Add DynamoDB permissions (full CRUD - exact match)
        self.rubric_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem"
                ],
                resources=[f"arn:aws:dynamodb:{self.region}:{self.account}:table/ku_grading_rubrics"]
            )
        )

        # Add S3 read permissions (any S3 bucket - exact match)
        self.rubric_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:ListBucket"
                ],
                resources=["arn:aws:s3:::*", "arn:aws:s3:::*/*"]
            )
        )

        # Essay Grading Lambda Role (matches ku_essay_grading_lambda-role-x51llveh)
        self.essay_grading_lambda_role = iam.Role(
            self, "KUEssayGradingLambdaRole",
            role_name=f"ku_essay_grading_lambda_role_{self.env_name}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for ku_essay_grading_lambda",
            path="/service-role/"
        )

        # Custom managed policy for CloudWatch Logs (matching existing structure)
        log_policy = iam.ManagedPolicy(
            self, "EssayGradingLambdaLogPolicy",
            managed_policy_name=f"AWSLambdaBasicExecutionRole-{self.env_name}",
            description="CloudWatch Logs policy for essay grading lambda",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["logs:CreateLogGroup"],
                    resources=[f"arn:aws:logs:{self.region}:{self.account}:*"]
                ),
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/lambda/ku_essay_grading_lambda:*"]
                )
            ]
        )

        self.essay_grading_lambda_role.add_managed_policy(log_policy)

        # Add Bedrock permissions (exact match)
        self.essay_grading_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=["arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0"]
            )
        )

        # Add DynamoDB read permissions (exact match)
        self.essay_grading_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan"
                ],
                resources=["arn:aws:dynamodb:*:*:table/ku_grading_rubrics"]
            )
        )

        # Add S3 permissions for output bucket (exact match)
        self.essay_grading_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:PutObject",
                    "s3:PutObjectAcl"
                ],
                resources=["arn:aws:s3:::ku-grading-output-bucket/*"]
            )
        )

        self.essay_grading_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:ListBucket"],
                resources=["arn:aws:s3:::ku-output-grading-bucket"]
            )
        )

        self.rubric_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:ListBucket"
                ],
                resources=["arn:aws:s3:::*", "arn:aws:s3:::*/*"]
            )
        )

        # Add specific permissions for kansas-uni-documents bucket
        self.rubric_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:ListBucket"
                ],
                resources=[
                    "arn:aws:s3:::ku-documents",
                    "arn:aws:s3:::ku-documents/*"
                ]
            )
        )

    def create_lambda_functions(self):
        """Create Lambda functions"""

        # Rubric Generation Lambda
        self.rubric_generation_lambda = lambda_.Function(
            self, "KURubricGenerationLambda",
            function_name="ku_rubric_generation_lambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset("../lambda/rubric_generation"),  # Fixed path
            timeout=Duration.seconds(self.config["timeout"]["ku_rubric_generation_lambda"]),
            memory_size=self.config["memory_size"]["ku_rubric_generation_lambda"],
            role=self.rubric_lambda_role,
            environment={
                "TABLE_NAME": self.rubrics_table.table_name,
                "LOG_LEVEL": "INFO"
            },
            description="Lambda function for generating rubrics"
        )

        # Essay Grading Lambda
        self.essay_grading_lambda = lambda_.Function(
            self, "KUEssayGradingLambda",
            function_name="ku_essay_grading_lambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset("../lambda/essay_grading"),  # Fixed path
            timeout=Duration.seconds(self.config["timeout"]["ku_essay_grading_lambda"]),
            memory_size=self.config["memory_size"]["ku_essay_grading_lambda"],
            role=self.essay_grading_lambda_role,
            environment={
                "RUBRICS_TABLE": self.rubrics_table.table_name,
                "OUTPUT_BUCKET_NAME": self.output_grading_bucket.bucket_name,
                "LOG_LEVEL": "INFO"
            },
            description="Lambda function for grading essays"
        )

    def create_api_gateway(self):
        """Create API Gateway matching existing configuration"""

        # Create REST API (matching existing "essay-grading-api")
        self.api = apigateway.RestApi(
            self, "KUEssayGradingAPI",
            rest_api_name="essay-grading-api",  # Exact match to existing
            description="API for automated essay grading using Bedrock",
            deploy_options=apigateway.StageOptions(
                stage_name=self.env_name,
                logging_level=self.config["api_settings"]["logging_level"],
                data_trace_enabled=self.config["api_settings"]["data_trace_enabled"],
                metrics_enabled=self.config["api_settings"]["metrics_enabled"]
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=["*"],
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"]
            ),
            endpoint_configuration=apigateway.EndpointConfiguration(
                types=[apigateway.EndpointType.REGIONAL]
            )
        )

        # Create API Gateway integration for essay grading (AWS_PROXY integration)
        essay_grading_integration = apigateway.LambdaIntegration(
            self.essay_grading_lambda,
            proxy=True,  # Use AWS_PROXY integration like existing
            integration_responses=[
                apigateway.IntegrationResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Access-Control-Allow-Origin": "'*'"
                    }
                )
            ]
        )

        # Create /grade-essay resource and POST method
        grade_essay_resource = self.api.root.add_resource("grade-essay")
        grade_essay_method = grade_essay_resource.add_method(
            "POST",
            essay_grading_integration,
            authorization_type=apigateway.AuthorizationType.NONE,
            method_responses=[
                apigateway.MethodResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Access-Control-Allow-Origin": False
                    },
                    response_models={
                        "application/json": apigateway.Model.EMPTY_MODEL
                    }
                )
            ]
        )

        # Grant API Gateway permission to invoke essay grading lambda
        self.essay_grading_lambda.add_permission(
            "AllowAPIGatewayInvoke",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:{self.api.rest_api_id}/*/POST/grade-essay"
        )

        # NEW: Create API Gateway integration for rubric generation
        rubric_generation_integration = apigateway.LambdaIntegration(
            self.rubric_generation_lambda,
            proxy=True,  # Use AWS_PROXY integration
            integration_responses=[
                apigateway.IntegrationResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Access-Control-Allow-Origin": "'*'"
                    }
                )
            ]
        )

        # NEW: Create /generate-rubric resource and POST method
        generate_rubric_resource = self.api.root.add_resource("generate-rubric")
        generate_rubric_method = generate_rubric_resource.add_method(
            "POST",
            rubric_generation_integration,
            authorization_type=apigateway.AuthorizationType.NONE,
            method_responses=[
                apigateway.MethodResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Access-Control-Allow-Origin": False
                    },
                    response_models={
                        "application/json": apigateway.Model.EMPTY_MODEL
                    }
                )
            ]
        )

        # NEW: Grant API Gateway permission to invoke rubric generation lambda
        self.rubric_generation_lambda.add_permission(
            "AllowAPIGatewayInvokeRubricGeneration",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:{self.api.rest_api_id}/*/POST/generate-rubric"
        )

    def create_outputs(self):
        """Create CloudFormation outputs"""

        CfnOutput(
            self, "RubricsTableName",
            value=self.rubrics_table.table_name,
            description="Name of the rubrics DynamoDB table"
        )

        CfnOutput(
            self, "OutputGradingBucketName",
            value=self.output_grading_bucket.bucket_name,
            description="Name of the output grading S3 bucket"
        )

        CfnOutput(
            self, "RubricGenerationLambdaArn",
            value=self.rubric_generation_lambda.function_arn,
            description="ARN of the rubric generation Lambda function"
        )

        CfnOutput(
            self, "EssayGradingLambdaArn",
            value=self.essay_grading_lambda.function_arn,
            description="ARN of the essay grading Lambda function"
        )

        CfnOutput(
            self, "APIGatewayURL",
            value=self.api.url,
            description="URL of the API Gateway"
        )

        CfnOutput(
            self, "GradeEssayEndpoint",
            value=f"{self.api.url}grade-essay",
            description="Endpoint for grading essays"
        )

        CfnOutput(
            self, "GenerateRubricEndpoint",
            value=f"{self.api.url}generate-rubric",
            description="Endpoint for generating rubrics"
        )