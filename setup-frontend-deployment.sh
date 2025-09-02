#!/bin/bash

# Setup script for KU Essay Grading Frontend Deployment
# This script helps configure the environment for first-time deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

print_status "Setting up KU Essay Grading Frontend Deployment"

# Check if we're in the correct directory
if [[ ! -f "package.json" ]] || [[ ! -d "frontend" ]] || [[ ! -d "cdk" ]]; then
    print_error "Please run this script from the Main directory"
    exit 1
fi

# Install frontend dependencies
print_status "Installing frontend dependencies..."
cd frontend
npm install
print_success "Frontend dependencies installed"

# Build frontend for the first time
print_status "Building frontend for the first time..."
npm run build
print_success "Initial frontend build completed"

cd ..

# Install CDK dependencies
print_status "Installing CDK dependencies..."
pip install -r requirements.txt
print_success "CDK dependencies installed"

# Check AWS CLI configuration
print_status "Checking AWS CLI configuration..."
if aws sts get-caller-identity &> /dev/null; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    REGION=$(aws configure get region || echo "us-east-1")
    print_success "AWS CLI is configured"
    echo -e "${GREEN}Account ID:${NC} $ACCOUNT_ID"
    echo -e "${GREEN}Region:${NC} $REGION"
else
    print_warning "AWS CLI is not configured or credentials are invalid"
    print_status "Please run 'aws configure' to set up your credentials"
fi

# Make deployment script executable
chmod +x deploy-frontend.sh
print_success "Deployment script is now executable"

echo ""
print_success "=== SETUP COMPLETE ==="
echo ""
print_status "Next steps:"
echo "1. Update the API URLs in frontend/.env.* files after deploying the backend"
echo "2. Run the deployment script: ./deploy-frontend.sh dev"
echo "3. For production: ./deploy-frontend.sh prod"
echo ""
print_warning "Note: Make sure your AWS credentials have the necessary permissions for:"
echo "  - S3 (create buckets, upload objects)"
echo "  - CloudFront (create distributions)"
echo "  - CloudFormation (create/update stacks)"
echo "  - IAM (create roles and policies)"
echo ""
print_status "For more details, see FRONTEND_DEPLOYMENT.md"