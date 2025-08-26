#!/bin/bash
# KU Essay Grading - CodeBuild CDK Deployment
# Automated deployment using AWS CodeBuild

echo "KU Essay Grading - CodeBuild CDK Deployment"
echo "==========================================="

# ------------------------- AWS CLI Fix for Spaces in Path -------------------------

# Function to run AWS CLI commands (handles path with spaces issue)
run_aws() {
    # Try different methods to run AWS CLI
    if command -v aws >/dev/null 2>&1 && aws --version >/dev/null 2>&1; then
        # System AWS CLI works
        aws "$@"
    elif python3 -c "import awscli" >/dev/null 2>&1; then
        # Use Python module
        python3 -m awscli "$@"
    elif /usr/local/bin/aws --version >/dev/null 2>&1; then
        # Try common system location
        /usr/local/bin/aws "$@"
    else
        echo "Error: AWS CLI not available"
        exit 1
    fi
}

# ------------------------- Configuration -------------------------

# Get AWS profile from parameter or prompt
if [ -n "$1" ]; then
    AWS_PROFILE="$1"
elif [ -z "$AWS_PROFILE" ]; then
    read -p "Enter AWS profile name [KUDeveloper]: " AWS_PROFILE
    AWS_PROFILE=${AWS_PROFILE:-KUDeveloper}
fi

# Auto-detect GitHub URL from current repo
GITHUB_URL=$(git remote get-url origin 2>/dev/null)
if [ -z "$GITHUB_URL" ]; then
    echo "Could not detect GitHub URL. Make sure you're in a git repository."
    exit 1
fi
echo "Detected GitHub URL: $GITHUB_URL"

if [ -z "$PROJECT_NAME" ]; then
    read -p "Enter CodeBuild project name [ku-essay-grading]: " PROJECT_NAME
    PROJECT_NAME=${PROJECT_NAME:-ku-essay-grading}
fi

# Get AWS account and region from the specified profile
echo "Using AWS profile: $AWS_PROFILE"
AWS_ACCOUNT=$(run_aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text 2>/dev/null)
AWS_REGION=$(run_aws configure get region --profile "$AWS_PROFILE" 2>/dev/null || echo "us-east-1")
ENVIRONMENT="dev"

if [ -z "$AWS_ACCOUNT" ] || [ "$AWS_ACCOUNT" = "None" ]; then
    echo "Failed to get account ID from profile: $AWS_PROFILE"
    echo "Available profiles:"
    run_aws configure list-profiles
    exit 1
fi

echo "Configuration:"
echo "  Project: $PROJECT_NAME"
echo "  GitHub: $GITHUB_URL"
echo "  Account: $AWS_ACCOUNT"
echo "  Region: $AWS_REGION"
echo "  Environment: $ENVIRONMENT"
echo ""

# ------------------------- Setup CodeBuild -------------------------

ROLE_NAME="${PROJECT_NAME}-codebuild-service-role"

echo "Phase 1: Setting up CodeBuild for CDK deployment..."

# Create IAM role if needed
if ! run_aws iam get-role --role-name "$ROLE_NAME" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
    echo "Creating IAM role..."

    TRUST_POLICY='{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "codebuild.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'

    run_aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST_POLICY" --profile "$AWS_PROFILE" >/dev/null
    run_aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/AdministratorAccess" --profile "$AWS_PROFILE"

    # Additional policies for CDK and Bedrock
    ADDITIONAL_POLICY='{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:ListFoundationModels"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "sts:AssumeRole",
                    "cloudformation:*",
                    "s3:*",
                    "lambda:*",
                    "dynamodb:*",
                    "apigateway:*",
                    "iam:*",
                    "logs:*"
                ],
                "Resource": "*"
            }
        ]
    }'

    run_aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "KUEssayGradingAdditionalPermissions" --policy-document "$ADDITIONAL_POLICY" --profile "$AWS_PROFILE"
    sleep 10
    echo "IAM role created"
else
    echo "IAM role exists"
fi

ROLE_ARN=$(run_aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text --profile "$AWS_PROFILE")

# Create buildspec.yml if it doesn't exist
if [ ! -f "buildspec.yml" ]; then
    echo "Creating buildspec.yml..."
    cat > buildspec.yml << 'EOF'
version: 0.2

phases:
  install:
    runtime-versions:
      python: 3.11
      nodejs: 18
    commands:
      - echo "Installing CDK..."
      - npm install -g aws-cdk@latest
      - echo "CDK version:" $(cdk --version)

  pre_build:
    commands:
      - echo "Pre-build phase started on $(date)"
      - echo "Current directory:" $(pwd)
      - echo "Listing files:" && ls -la
      - cd cdk
      - echo "Installing Python dependencies..."
      - python -m pip install --upgrade pip
      - pip install -r ../requirements.txt
      - echo "CDK Bootstrap check..."
      - cdk bootstrap --context account=$AWS_ACCOUNT --context region=$AWS_REGION

  build:
    commands:
      - echo "Build phase started on $(date)"
      - echo "Synthesizing CDK stack..."
      - cdk synth --context env=$ENVIRONMENT --context account=$AWS_ACCOUNT --context region=$AWS_REGION
      - echo "Deploying CDK stack..."
      - cdk deploy --context env=$ENVIRONMENT --context account=$AWS_ACCOUNT --context region=$AWS_REGION --require-approval never

  post_build:
    commands:
      - echo "Post-build phase started on $(date)"
      - echo "Getting stack outputs..."
      - aws cloudformation describe-stacks --stack-name KUEssayGradingStack-$ENVIRONMENT --region $AWS_REGION
      - echo "Build completed on $(date)"

artifacts:
  files:
    - '**/*'
EOF
    echo "buildspec.yml created"
fi

# Check if CodeBuild project exists
echo "Checking for existing CodeBuild project..."
if run_aws codebuild describe-project --name "$PROJECT_NAME" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
    echo "CodeBuild project exists, updating configuration to use cdk_stack branch..."
    run_aws codebuild update-project \
        --name "$PROJECT_NAME" \
        --source "{\"type\": \"GITHUB\", \"location\": \"$GITHUB_URL\"}" \
        --source-version "cdk_stack" \
        --artifacts '{"type": "NO_ARTIFACTS"}' \
        --environment "{
            \"type\": \"LINUX_CONTAINER\",
            \"image\": \"aws/codebuild/amazonlinux-x86_64-standard:5.0\",
            \"computeType\": \"BUILD_GENERAL1_MEDIUM\",
            \"environmentVariables\": [
                {\"name\": \"AWS_ACCOUNT\", \"value\": \"$AWS_ACCOUNT\"},
                {\"name\": \"AWS_REGION\", \"value\": \"$AWS_REGION\"},
                {\"name\": \"ENVIRONMENT\", \"value\": \"$ENVIRONMENT\"}
            ]
        }" \
        --service-role "$ROLE_ARN" \
        --profile "$AWS_PROFILE" >/dev/null

    if [ $? -eq 0 ]; then
        echo "CodeBuild project updated successfully to use cdk_stack branch"
    else
        echo "Failed to update CodeBuild project, but continuing with existing project..."
    fi
else
    echo "Creating new CodeBuild project with cdk_stack branch..."
    CREATE_RESULT=$(run_aws codebuild create-project \
        --name "$PROJECT_NAME" \
        --source "{\"type\": \"GITHUB\", \"location\": \"$GITHUB_URL\"}" \
        --source-version "cdk_stack" \
        --artifacts '{"type": "NO_ARTIFACTS"}' \
        --environment "{
            \"type\": \"LINUX_CONTAINER\",
            \"image\": \"aws/codebuild/amazonlinux-x86_64-standard:5.0\",
            \"computeType\": \"BUILD_GENERAL1_MEDIUM\",
            \"environmentVariables\": [
                {\"name\": \"AWS_ACCOUNT\", \"value\": \"$AWS_ACCOUNT\"},
                {\"name\": \"AWS_REGION\", \"value\": \"$AWS_REGION\"},
                {\"name\": \"ENVIRONMENT\", \"value\": \"$ENVIRONMENT\"}
            ]
        }" \
        --service-role "$ROLE_ARN" \
        --profile "$AWS_PROFILE" 2>&1)

    if [ $? -eq 0 ]; then
        echo "CodeBuild project created successfully with cdk_stack branch"
    else
        echo "CodeBuild project creation failed with error:"
        echo "$CREATE_RESULT"
        echo "This might be due to GitHub access permissions for private repositories."
        echo "Please ensure GitHub is connected to CodeBuild in AWS Console."
        exit 1
    fi
fi

# ------------------------- Run CDK Deployment -------------------------

echo ""
echo "Phase 2: Running CDK deployment via CodeBuild..."

BUILD_START_RESULT=$(run_aws codebuild start-build --project-name "$PROJECT_NAME" --profile "$AWS_PROFILE" 2>&1)
BUILD_ID=$(echo "$BUILD_START_RESULT" | grep -o '"id": "[^"]*"' | cut -d'"' -f4)

if [ -z "$BUILD_ID" ]; then
    echo "Failed to start CodeBuild:"
    echo "$BUILD_START_RESULT"
    echo ""
    echo "This is likely due to GitHub access permissions."
    echo "For private repositories, you need to:"
    echo "1. Go to AWS Console > CodeBuild > Settings > Source providers"
    echo "2. Connect to GitHub and authorize AWS CodeBuild"
    echo ""
    echo "Alternatively, use direct deployment:"
    echo "./simple-deploy.sh $AWS_PROFILE"
    exit 1
fi

echo "Build started: $BUILD_ID"

# Wait for build to complete
echo "Waiting for CDK deployment to complete..."

while true; do
    BUILD_STATUS=$(run_aws codebuild batch-get-builds --ids "$BUILD_ID" --profile "$AWS_PROFILE" --query 'builds[0].buildStatus' --output text)

    case $BUILD_STATUS in
        "IN_PROGRESS")
            echo "  Still building... ($(date '+%H:%M:%S'))"
            sleep 30
            ;;
        "SUCCEEDED")
            echo "CDK deployment completed successfully!"
            break
            ;;
        "FAILED")
            echo "CDK deployment failed!"
            echo "Check CodeBuild logs at:"
            echo "https://$AWS_REGION.console.aws.amazon.com/codesuite/codebuild/projects/$PROJECT_NAME/history"

            # Try to get error details
            echo ""
            echo "Build failure details:"
            run_aws codebuild batch-get-builds --ids "$BUILD_ID" --profile "$AWS_PROFILE" --query 'builds[0].phases[?phaseStatus==`FAILED`].{Phase:phaseType,Status:phaseStatus}' --output table
            exit 1
            ;;
        *)
            echo "Build status: $BUILD_STATUS"
            sleep 30
            ;;
    esac
done

# ------------------------- Get CDK Outputs -------------------------

echo ""
echo "Phase 3: Getting outputs from CloudFormation stack..."

# Wait a moment for stack to be available
sleep 10

STACK_NAME="KUEssayGradingStack-${ENVIRONMENT}"

# Get API Gateway URL
echo "Getting API Gateway URL..."
export API_URL=$(run_aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`APIGatewayURL`].OutputValue' \
    --output text \
    --profile "$AWS_PROFILE" 2>/dev/null)

# Get DynamoDB table name
echo "Getting DynamoDB table name..."
export TABLE_NAME=$(run_aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`RubricsTableName`].OutputValue' \
    --output text \
    --profile "$AWS_PROFILE" 2>/dev/null)

# Get S3 bucket name
echo "Getting S3 bucket name..."
export S3_BUCKET_NAME=$(run_aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`OutputGradingBucketName`].OutputValue' \
    --output text \
    --profile "$AWS_PROFILE" 2>/dev/null)

# Get Lambda function ARNs
echo "Getting Lambda function ARNs..."
export RUBRIC_LAMBDA_ARN=$(run_aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`RubricGenerationLambdaArn`].OutputValue' \
    --output text \
    --profile "$AWS_PROFILE" 2>/dev/null)

export ESSAY_LAMBDA_ARN=$(run_aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`EssayGradingLambdaArn`].OutputValue' \
    --output text \
    --profile "$AWS_PROFILE" 2>/dev/null)

echo "API Gateway URL: $API_URL"
echo "DynamoDB Table: $TABLE_NAME"
echo "S3 Bucket: $S3_BUCKET_NAME"
echo "Rubric Lambda: $RUBRIC_LAMBDA_ARN"
echo "Essay Grading Lambda: $ESSAY_LAMBDA_ARN"

# Verify outputs
if [ "$API_URL" = "None" ] || [ -z "$API_URL" ]; then
    echo "Could not get API URL from CloudFormation stack"
    echo "Available stacks:"
    run_aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query 'StackSummaries[].StackName' --profile "$AWS_PROFILE"
    exit 1
fi

# ------------------------- Test Deployment -------------------------

echo ""
echo "Phase 4: Testing deployment..."

# Test API Gateway health
echo "Testing API Gateway..."
if command -v curl >/dev/null 2>&1; then
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS "${API_URL}grade-essay" || echo "000")
    if [ "$HTTP_STATUS" -eq 200 ]; then
        echo "API Gateway is responding correctly"
    else
        echo "API Gateway test returned status: $HTTP_STATUS"
    fi
else
    echo "curl not available, skipping API test"
fi

# Test Lambda functions
echo "Testing Lambda functions..."
RUBRIC_LAMBDA_NAME=$(echo $RUBRIC_LAMBDA_ARN | cut -d':' -f7)
ESSAY_LAMBDA_NAME=$(echo $ESSAY_LAMBDA_ARN | cut -d':' -f7)

RUBRIC_STATUS=$(run_aws lambda get-function --function-name "$RUBRIC_LAMBDA_NAME" --query 'Configuration.State' --output text --profile "$AWS_PROFILE" 2>/dev/null)
ESSAY_STATUS=$(run_aws lambda get-function --function-name "$ESSAY_LAMBDA_NAME" --query 'Configuration.State' --output text --profile "$AWS_PROFILE" 2>/dev/null)

echo "Rubric Lambda Status: $RUBRIC_STATUS"
echo "Essay Lambda Status: $ESSAY_STATUS"

# Test DynamoDB
echo "Testing DynamoDB..."
TABLE_STATUS=$(run_aws dynamodb describe-table --table-name "$TABLE_NAME" --query 'Table.TableStatus' --output text --profile "$AWS_PROFILE" 2>/dev/null)
echo "DynamoDB Status: $TABLE_STATUS"

# ------------------------- Success -------------------------

echo ""
echo "DEPLOYMENT COMPLETE!"
echo "==================="
echo ""
echo "Your KU Essay Grading System:"
echo "  Backend API: $API_URL"
echo "  Test Endpoint: ${API_URL}grade-essay"
echo "  DynamoDB Table: $TABLE_NAME"
echo "  S3 Bucket: $S3_BUCKET_NAME"
echo ""
echo "Test the API:"
echo "curl -X POST \"${API_URL}grade-essay\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{"
echo "    \"essay_text\": \"Sample essay for testing\","
echo "    \"essay_type\": \"narrative\","
echo "    \"essay_id\": \"test-123\","
echo "    \"student_id\": \"student-456\","
echo "    \"assignment_id\": \"assignment-789\""
echo "  }'"
echo ""
echo "CodeBuild Console: https://$AWS_REGION.console.aws.amazon.com/codesuite/codebuild/projects/$PROJECT_NAME/history"
echo ""
echo "All done!"