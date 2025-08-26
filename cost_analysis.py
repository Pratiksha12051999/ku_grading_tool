#!/usr/bin/env python3
"""
AWS Cost Analysis for KU Grader Tool - Serverless Essay Grading Application
"""

import json
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors

class AWSCostCalculator:
    def __init__(self):
        self.region = "US East 1 (Virginia)"
        self.currency = "USD"
        
    def calculate_api_gateway_costs(self):
        """Calculate API Gateway costs"""
        total_requests = 10050  # 10,000 + 50
        # First 1M requests: $3.50 per million
        cost = (total_requests / 1_000_000) * 3.50
        return {
            "service": "API Gateway",
            "requests": total_requests,
            "monthly_cost": round(cost, 4),
            "details": f"{total_requests:,} REST API requests"
        }
    
    def calculate_lambda_costs(self):
        """Calculate Lambda costs for both functions"""
        # Rubric Generation Lambda
        rubric_invocations = 50
        rubric_duration = 180  # seconds
        rubric_memory = 1024  # MB
        
        # Essay Grading Lambda  
        grading_invocations = 10000
        grading_duration = 9  # seconds per invocation
        grading_memory = 1024  # MB
        
        # Lambda pricing (US East 1)
        request_cost_per_million = 0.20
        gb_second_cost = 0.0000166667
        
        # Calculate costs
        total_invocations = rubric_invocations + grading_invocations
        request_cost = (total_invocations / 1_000_000) * request_cost_per_million
        
        # Compute time costs
        rubric_gb_seconds = (rubric_memory / 1024) * rubric_duration * rubric_invocations
        grading_gb_seconds = (grading_memory / 1024) * grading_duration * grading_invocations
        total_gb_seconds = rubric_gb_seconds + grading_gb_seconds
        
        compute_cost = total_gb_seconds * gb_second_cost
        total_cost = request_cost + compute_cost
        
        return {
            "service": "AWS Lambda",
            "invocations": total_invocations,
            "gb_seconds": round(total_gb_seconds, 2),
            "monthly_cost": round(total_cost, 4),
            "details": f"Rubric: {rubric_invocations} invocations, Grading: {grading_invocations:,} invocations"
        }
    
    def calculate_bedrock_costs(self):
        """Calculate Amazon Bedrock Nova Pro costs"""
        # Pricing for amazon.nova-pro-v1:0 (as of 2024)
        input_token_cost = 0.0008 / 1000  # per 1K tokens
        output_token_cost = 0.0032 / 1000  # per 1K tokens
        
        # Rubric Generation
        rubric_requests = 50
        rubric_input_tokens = 3000 * rubric_requests
        rubric_output_tokens = 1500 * rubric_requests
        
        # Essay Grading
        grading_requests = 10000
        grading_input_tokens = 2000 * grading_requests
        grading_output_tokens = 800 * grading_requests
        
        # Calculate costs
        total_input_tokens = rubric_input_tokens + grading_input_tokens
        total_output_tokens = rubric_output_tokens + grading_output_tokens
        
        input_cost = total_input_tokens * input_token_cost
        output_cost = total_output_tokens * output_token_cost
        total_cost = input_cost + output_cost
        
        return {
            "service": "Amazon Bedrock (Nova Pro)",
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "monthly_cost": round(total_cost, 2),
            "details": f"Input: {total_input_tokens:,} tokens, Output: {total_output_tokens:,} tokens"
        }
    
    def calculate_dynamodb_costs(self):
        """Calculate DynamoDB costs"""
        # On-demand pricing
        read_request_cost = 0.25 / 1_000_000  # per million RRUs
        write_request_cost = 1.25 / 1_000_000  # per million WRUs
        storage_cost_per_gb = 0.25
        
        read_requests = 10000
        write_requests = 50
        storage_gb = 5
        
        read_cost = read_requests * read_request_cost
        write_cost = write_requests * write_request_cost
        storage_cost = storage_gb * storage_cost_per_gb
        
        total_cost = read_cost + write_cost + storage_cost
        
        return {
            "service": "DynamoDB",
            "read_requests": read_requests,
            "write_requests": write_requests,
            "storage_gb": storage_gb,
            "monthly_cost": round(total_cost, 4),
            "details": f"Reads: {read_requests:,}, Writes: {write_requests}, Storage: {storage_gb}GB"
        }
    
    def calculate_s3_costs(self):
        """Calculate S3 costs"""
        # Standard storage pricing
        storage_cost_per_gb = 0.023
        put_request_cost = 0.0005 / 1000  # per 1K requests
        get_request_cost = 0.0004 / 1000  # per 1K requests
        
        storage_gb = 20
        put_requests = 10000
        get_requests = 1000
        
        storage_cost = storage_gb * storage_cost_per_gb
        put_cost = put_requests * put_request_cost
        get_cost = get_requests * get_request_cost
        
        total_cost = storage_cost + put_cost + get_cost
        
        return {
            "service": "Amazon S3",
            "storage_gb": storage_gb,
            "put_requests": put_requests,
            "get_requests": get_requests,
            "monthly_cost": round(total_cost, 4),
            "details": f"Storage: {storage_gb}GB, PUT: {put_requests:,}, GET: {get_requests:,}"
        }
    
    def calculate_data_transfer_costs(self):
        """Calculate data transfer costs"""
        # First 1GB free, then $0.09/GB for next 9.999TB
        outbound_gb = 5
        free_tier = 1
        billable_gb = max(0, outbound_gb - free_tier)
        
        cost = billable_gb * 0.09
        
        return {
            "service": "Data Transfer",
            "outbound_gb": outbound_gb,
            "monthly_cost": round(cost, 4),
            "details": f"{outbound_gb}GB outbound ({billable_gb}GB billable)"
        }
    
    def calculate_cloudwatch_costs(self):
        """Calculate CloudWatch Logs costs"""
        # Estimate log ingestion for Lambda functions
        log_ingestion_gb = 0.5  # Conservative estimate
        cost_per_gb = 0.50
        
        cost = log_ingestion_gb * cost_per_gb
        
        return {
            "service": "CloudWatch Logs",
            "log_ingestion_gb": log_ingestion_gb,
            "monthly_cost": round(cost, 4),
            "details": f"{log_ingestion_gb}GB log ingestion"
        }
    
    def generate_cost_analysis(self):
        """Generate complete cost analysis"""
        services = [
            self.calculate_api_gateway_costs(),
            self.calculate_lambda_costs(),
            self.calculate_bedrock_costs(),
            self.calculate_dynamodb_costs(),
            self.calculate_s3_costs(),
            self.calculate_data_transfer_costs(),
            self.calculate_cloudwatch_costs()
        ]
        
        total_monthly = sum(service["monthly_cost"] for service in services)
        annual_cost = total_monthly * 12
        
        # Sort by cost to identify top drivers
        services_sorted = sorted(services, key=lambda x: x["monthly_cost"], reverse=True)
        
        return {
            "services": services,
            "total_monthly": round(total_monthly, 2),
            "annual_cost": round(annual_cost, 2),
            "top_cost_drivers": services_sorted[:3],
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

def create_pdf_report(cost_data, filename="ku_grader_cost_analysis.pdf"):
    """Create PDF report from cost analysis data"""
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1  # Center
    )
    story.append(Paragraph("KU Grader Tool - AWS Cost Analysis", title_style))
    story.append(Paragraph("Serverless Essay Grading Application", styles['Heading2']))
    story.append(Spacer(1, 20))
    
    # Executive Summary
    story.append(Paragraph("Executive Summary", styles['Heading2']))
    summary_text = f"""
    <b>Total Monthly Cost:</b> ${cost_data['total_monthly']}<br/>
    <b>Annual Projection:</b> ${cost_data['annual_cost']}<br/>
    <b>Analysis Date:</b> {cost_data['analysis_date']}<br/>
    <b>Region:</b> US East 1 (Virginia)
    """
    story.append(Paragraph(summary_text, styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Detailed Cost Breakdown
    story.append(Paragraph("Detailed Cost Breakdown", styles['Heading2']))
    
    # Create table data
    table_data = [['Service', 'Monthly Cost', 'Details']]
    for service in cost_data['services']:
        table_data.append([
            service['service'],
            f"${service['monthly_cost']}",
            service['details']
        ])
    
    # Add total row
    table_data.append(['TOTAL', f"${cost_data['total_monthly']}", ''])
    
    # Create table
    table = Table(table_data, colWidths=[2*inch, 1*inch, 3*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(table)
    story.append(Spacer(1, 20))
    
    # Top Cost Drivers
    story.append(Paragraph("Top 3 Cost Drivers", styles['Heading2']))
    for i, driver in enumerate(cost_data['top_cost_drivers'], 1):
        story.append(Paragraph(f"{i}. {driver['service']}: ${driver['monthly_cost']}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Optimization Recommendations
    story.append(Paragraph("Cost Optimization Recommendations", styles['Heading2']))
    recommendations = [
        "1. <b>Bedrock Optimization:</b> Implement token caching and batch processing to reduce API calls",
        "2. <b>Lambda Optimization:</b> Consider provisioned concurrency for consistent workloads and optimize memory allocation",
        "3. <b>DynamoDB Optimization:</b> Monitor usage patterns and consider switching to provisioned capacity if usage becomes predictable"
    ]
    
    for rec in recommendations:
        story.append(Paragraph(rec, styles['Normal']))
        story.append(Spacer(1, 10))
    
    # Architecture Notes
    story.append(Spacer(1, 20))
    story.append(Paragraph("Architecture Notes", styles['Heading2']))
    arch_notes = """
    • Regional deployment in US East 1 for optimal performance and cost<br/>
    • On-demand billing for development environment flexibility<br/>
    • Standard encryption at rest across all services<br/>
    • Batch processing capability for peak academic periods
    """
    story.append(Paragraph(arch_notes, styles['Normal']))
    
    doc.build(story)
    return filename

if __name__ == "__main__":
    calculator = AWSCostCalculator()
    cost_analysis = calculator.generate_cost_analysis()
    
    # Print summary to console
    print("KU Grader Tool - AWS Cost Analysis")
    print("=" * 50)
    print(f"Total Monthly Cost: ${cost_analysis['total_monthly']}")
    print(f"Annual Projection: ${cost_analysis['annual_cost']}")
    print("\nService Breakdown:")
    for service in cost_analysis['services']:
        print(f"  {service['service']}: ${service['monthly_cost']}")
    
    # Generate PDF
    pdf_filename = create_pdf_report(cost_analysis)
    print(f"\nPDF report generated: {pdf_filename}")