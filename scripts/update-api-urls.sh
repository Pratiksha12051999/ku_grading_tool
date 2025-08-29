#!/bin/bash

# Script to update API URLs in frontend environment files after CDK deployment
# Usage: ./update-api-urls.sh [environment] [aws-profile]

set -e

ENV=${1:-dev}
PROFILE=${2:-default}
REGION=${3:-us-east-1}

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_status "Updating API URLs for environment: $ENV"

# Get API Gateway URL from CloudFormation stack
STACK_NAME="KUEssayGradingStack-$ENV"

print_status "Retrieving API Gateway URL from stack: $STACK_NAME"

API_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --profile $PROFILE \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`APIGatewayURL`].OutputValue' \
    --output text 2>/dev/null)

if [[ -z "$API_URL" ]]; then
    print_error "Could not retrieve API Gateway URL from stack $STACK_NAME"
    print_error "Make sure the stack is deployed and you have the correct permissions"
    exit 1
fi

print_success "Found API Gateway URL: $API_URL"

# Update the appropriate environment file
ENV_FILE="frontend/.env.$ENV"
if [[ "$ENV" == "dev" ]]; then
    ENV_FILE="frontend/.env.development"
elif [[ "$ENV" == "prod" ]]; then
    ENV_FILE="frontend/.env.production"
elif [[ "$ENV" == "test" ]]; then
    ENV_FILE="frontend/.env.test"
fi

if [[ ! -f "$ENV_FILE" ]]; then
    print_error "Environment file $ENV_FILE not found"
    exit 1
fi

print_status "Updating $ENV_FILE"

# Create backup
cp "$ENV_FILE" "$ENV_FILE.backup"

# Update the API URL
if grep -q "REACT_APP_API_URL=" "$ENV_FILE"; then
    # Replace existing URL
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|REACT_APP_API_URL=.*|REACT_APP_API_URL=$API_URL|" "$ENV_FILE"
    else
        # Linux
        sed -i "s|REACT_APP_API_URL=.*|REACT_APP_API_URL=$API_URL|" "$ENV_FILE"
    fi
else
    # Add new URL
    echo "REACT_APP_API_URL=$API_URL" >> "$ENV_FILE"
fi

print_success "Updated $ENV_FILE with API URL: $API_URL"

# Show the updated file
print_status "Updated environment file contents:"
echo "----------------------------------------"
cat "$ENV_FILE"
echo "----------------------------------------"

print_success "API URL update completed!"
print_status "Backup saved as: $ENV_FILE.backup"
print_warning "Remember to rebuild and redeploy the frontend to use the new API URL"