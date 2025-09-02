#!/bin/bash

# Frontend Deployment Script for KU Essay Grading Tool
# Usage: ./deploy-frontend.sh [environment] [aws-profile]

set -e

# Default values
ENV=${1:-dev}
PROFILE=${2:-default}
REGION=${3:-us-east-1}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
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

# Validate environment
if [[ ! "$ENV" =~ ^(dev|test|prod)$ ]]; then
    print_error "Invalid environment: $ENV. Must be one of: dev, test, prod"
    exit 1
fi

print_status "Starting frontend deployment for environment: $ENV"
print_status "Using AWS profile: $PROFILE"
print_status "Target region: $REGION"

# Check if we're in the correct directory (ku_grader_tool root)
if [[ ! -d "frontend" ]] || [[ ! -d "backend" ]] || [[ ! -f "backend/cdk.json" ]]; then
    print_error "Please run this script from the ku_grader_tool root directory"
    print_error "Expected structure: frontend/, backend/, backend/cdk.json"
    exit 1
fi

PROJECT_ROOT="."
print_status "Found project structure in current directory"

# Check prerequisites
print_status "Checking prerequisites..."

# Check Node.js
if ! command -v node &> /dev/null; then
    print_error "Node.js is not installed. Please install Node.js first."
    exit 1
fi

# Check npm
if ! command -v npm &> /dev/null; then
    print_error "npm is not installed. Please install npm first."
    exit 1
fi

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    print_error "AWS CLI is not installed. Please install AWS CLI first."
    exit 1
fi

# Check CDK CLI
if ! command -v cdk &> /dev/null; then
    print_error "AWS CDK CLI is not installed. Please install with: npm install -g aws-cdk"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

print_success "All prerequisites are installed"

# Install frontend dependencies
print_status "Installing frontend dependencies..."
cd frontend
if [[ ! -d "node_modules" ]] || [[ "package.json" -nt "node_modules" ]]; then
    npm install
    print_success "Frontend dependencies installed"
else
    print_status "Frontend dependencies are up to date"
fi

# Build frontend
print_status "Building React application..."
npm run build

if [[ ! -d "build" ]]; then
    print_error "Frontend build failed - build directory not found"
    exit 1
fi

print_success "Frontend build completed"

# Navigate back to project root and then to backend directory
cd ..

# Navigate to backend directory (where cdk.json is located)
cd backend

# Install CDK dependencies
print_status "Installing CDK dependencies..."
if [[ -f "requirements.txt" ]]; then
    # Check if virtual environment exists, if not create it
    if [[ ! -d ".venv" ]]; then
        print_status "Creating Python virtual environment..."
        python3 -m venv .venv
    fi

    # Activate virtual environment and install dependencies
    print_status "Activating virtual environment and installing dependencies..."
    source .venv/bin/activate
    pip install -r requirements.txt
    print_success "CDK dependencies installed"
else
    print_warning "requirements.txt not found in backend directory"
fi

# Bootstrap CDK (if needed)
print_status "Checking CDK bootstrap status..."
if ! aws cloudformation describe-stacks --stack-name CDKToolkit --profile $PROFILE --region $REGION &> /dev/null; then
    print_warning "CDK not bootstrapped in this account/region. Bootstrapping now..."
    cdk bootstrap --profile $PROFILE
    if [[ $? -ne 0 ]]; then
        print_error "CDK bootstrap failed. Please check your AWS credentials and permissions."
        exit 1
    fi
    print_success "CDK bootstrap completed"
else
    print_status "CDK already bootstrapped"
fi

# Synthesize CDK stack
print_status "Synthesizing CDK stack..."
cdk synth --context env=$ENV --context profile=$PROFILE --context region=$REGION

# Deploy CDK stack
print_status "Deploying infrastructure and frontend..."
cdk deploy KUEssayGradingStack-$ENV \
    --context env=$ENV \
    --context profile=$PROFILE \
    --context region=$REGION \
    --require-approval never

if [[ $? -eq 0 ]]; then
    print_success "Deployment completed successfully!"
    
    # Get CloudFront URL
    print_status "Retrieving deployment information..."
    CLOUDFRONT_URL=$(aws cloudformation describe-stacks \
        --stack-name KUEssayGradingStack-$ENV \
        --profile $PROFILE \
        --region $REGION \
        --query 'Stacks[0].Outputs[?OutputKey==`FrontendURL`].OutputValue' \
        --output text 2>/dev/null || echo "")
    
    API_URL=$(aws cloudformation describe-stacks \
        --stack-name KUEssayGradingStack-$ENV \
        --profile $PROFILE \
        --region $REGION \
        --query 'Stacks[0].Outputs[?OutputKey==`APIGatewayURL`].OutputValue' \
        --output text 2>/dev/null || echo "")
    
    echo ""
    print_success "=== DEPLOYMENT SUMMARY ==="
    echo -e "${GREEN}Environment:${NC} $ENV"
    echo -e "${GREEN}AWS Profile:${NC} $PROFILE"
    echo -e "${GREEN}Region:${NC} $REGION"
    
    if [[ -n "$CLOUDFRONT_URL" ]]; then
        echo -e "${GREEN}Frontend URL:${NC} $CLOUDFRONT_URL"
    fi
    
    if [[ -n "$API_URL" ]]; then
        echo -e "${GREEN}API URL:${NC} $API_URL"
    fi
    
    echo ""
    print_warning "Note: CloudFront distribution may take 10-15 minutes to fully propagate globally."
    print_status "You can check the status in the AWS Console or use: aws cloudfront get-distribution --id <distribution-id>"
    
else
    print_error "Deployment failed!"
    exit 1
fi