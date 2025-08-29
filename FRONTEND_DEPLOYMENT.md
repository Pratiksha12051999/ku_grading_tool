# Frontend CDK Deployment Instructions

## Overview
This guide explains how to deploy the React frontend for the KU Essay Grading Tool using AWS CDK with CloudFront and S3.

## Prerequisites
- AWS CLI configured with appropriate credentials
- Node.js and npm installed
- AWS CDK CLI installed (`npm install -g aws-cdk`)
- Python 3.11+ with pip

## Architecture
The frontend deployment includes:
- **S3 Bucket**: Static website hosting for React build files
- **CloudFront Distribution**: CDN for global content delivery
- **Route 53** (optional): Custom domain configuration
- **Certificate Manager** (optional): SSL/TLS certificates

## Quick Start

### 1. Install Dependencies
```bash
# Install CDK dependencies
cd Main/cdk
pip install -r requirements.txt

# Install frontend dependencies
cd ../frontend
npm install
```

### 2. Build Frontend
```bash
cd Main/frontend
npm run build
```

### 3. Deploy Infrastructure
```bash
cd Main/cdk

# Deploy to dev environment
cdk deploy --context env=dev --context profile=default

# Deploy to production
cdk deploy --context env=prod --context profile=default
```

## Detailed Setup

### Environment Configuration
The CDK stack supports multiple environments:
- `dev`: Development environment with relaxed settings
- `test`: Testing environment with moderate settings  
- `prod`: Production environment with strict settings

### Deployment Commands

#### Development Deployment
```bash
cd Main/cdk
cdk deploy KUEssayGradingStack-dev --context env=dev --context profile=default
```

#### Production Deployment
```bash
cd Main/cdk
cdk deploy KUEssayGradingStack-prod --context env=prod --context profile=default
```

#### With Custom Account/Region
```bash
cdk deploy --context env=prod --context account=123456789012 --context region=us-west-2
```

## Frontend-Specific Resources

The CDK stack will create:

1. **Frontend S3 Bucket** (`ku-essay-grading-frontend-{env}`)
   - Static website hosting enabled
   - Public read access for website files
   - Automatic deployment of React build files

2. **CloudFront Distribution**
   - Global CDN for fast content delivery
   - Custom error pages for SPA routing
   - Caching optimized for static assets

3. **API Integration**
   - CORS configuration for frontend-backend communication
   - Environment-specific API endpoints

## Build and Deploy Process

### Automated Deployment Script
Create a deployment script for easy frontend updates:

```bash
#!/bin/bash
# deploy-frontend.sh

ENV=${1:-dev}
PROFILE=${2:-default}

echo "Building frontend for $ENV environment..."
cd frontend
npm run build

echo "Deploying to AWS..."
cd ../cdk
cdk deploy KUEssayGradingStack-$ENV --context env=$ENV --context profile=$PROFILE

echo "Frontend deployed successfully!"
```

Make it executable:
```bash
chmod +x deploy-frontend.sh
```

Usage:
```bash
./deploy-frontend.sh dev
./deploy-frontend.sh prod my-aws-profile
```

## Environment Variables

### Frontend Environment Configuration
Create environment-specific configuration files:

**frontend/.env.development**
```
REACT_APP_API_URL=https://your-dev-api.execute-api.us-east-1.amazonaws.com/dev
REACT_APP_ENVIRONMENT=development
```

**frontend/.env.production**
```
REACT_APP_API_URL=https://your-prod-api.execute-api.us-east-1.amazonaws.com/prod
REACT_APP_ENVIRONMENT=production
```

## Monitoring and Troubleshooting

### CloudWatch Logs
Monitor CloudFront access logs and S3 access patterns:
```bash
aws logs describe-log-groups --log-group-name-prefix "/aws/cloudfront"
```

### Invalidate CloudFront Cache
After deploying new frontend code:
```bash
aws cloudfront create-invalidation --distribution-id YOUR_DISTRIBUTION_ID --paths "/*"
```

### Common Issues

1. **CORS Errors**: Ensure API Gateway has proper CORS configuration
2. **404 Errors**: Verify CloudFront error pages redirect to index.html
3. **Caching Issues**: Use CloudFront invalidation for immediate updates

## Security Considerations

### Production Security
- Enable CloudFront security headers
- Configure Content Security Policy (CSP)
- Use HTTPS-only access
- Implement proper IAM roles and policies

### Development Security
- Restrict S3 bucket access
- Use temporary credentials
- Enable CloudTrail logging

## Cost Optimization

### Development Environment
- Use smaller CloudFront price class
- Disable unnecessary logging
- Set S3 lifecycle policies

### Production Environment
- Enable CloudFront compression
- Optimize caching strategies
- Monitor usage with AWS Cost Explorer

## Rollback Procedures

### Quick Rollback
```bash
# Revert to previous deployment
cdk deploy --context env=prod --rollback

# Or deploy specific version
git checkout previous-working-commit
./deploy-frontend.sh prod
```

### Emergency Rollback
```bash
# Disable CloudFront distribution
aws cloudfront update-distribution --id YOUR_DISTRIBUTION_ID --distribution-config file://emergency-config.json
```

## Next Steps

1. **Custom Domain**: Configure Route 53 and Certificate Manager
2. **CI/CD Pipeline**: Set up automated deployments with GitHub Actions or CodePipeline
3. **Monitoring**: Implement CloudWatch dashboards and alarms
4. **Performance**: Optimize bundle size and implement code splitting

## Support

For issues or questions:
1. Check CloudFormation stack events in AWS Console
2. Review CDK synthesis output: `cdk synth`
3. Validate configuration: `cdk diff`
4. Check AWS service limits and quotas