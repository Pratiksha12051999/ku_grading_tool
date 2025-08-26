import json
import boto3
import logging
import uuid
import csv
import io
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
bedrock_client = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')

# DynamoDB table
TABLE_NAME = 'ku_grading_rubrics'
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Lambda function to generate essay rubrics using Bedrock and store in DynamoDB

    Expected event structure:
    {
        "input_type": "s3" or "direct",
        "s3_bucket": "bucket-name" (if input_type is s3),
        "s3_key": "path/to/input.json" (if input_type is s3),
        "essay_type": "Source Dependent Responses",
        "grade_level": "10",
        "source_text_title": "Winter Hibiscus",
        "author": "Minfong Ho",
        "essay_prompt": "Write a response that explains...",
        "score_range": "0-3",
        "source_text_content": "Brief summary...",
        "original_rubric_guidelines_s3_url": "s3://bucket/path/to/rubric.pdf",
        "sample_essays_csv_s3_url": "s3://bucket/path/to/essays.csv"
    }
    """

    try:
        logger.info(f"Received event: {json.dumps(event, default=str)}")

        # Extract input parameters
        input_data = extract_input_parameters(event)

        # Process S3 files to get content
        processed_data = process_s3_files(input_data)

        # Generate rubric using Bedrock
        rubric_json = generate_rubric_with_bedrock(processed_data)

        # Store rubric in DynamoDB
        result = store_rubric_in_dynamodb(processed_data, rubric_json)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Rubric generated and stored successfully',
                'essay_type': processed_data['essay_type'],
                'dynamodb_response': result
            }, default=str)
        }

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            })
        }

def extract_input_parameters(event: Dict[str, Any]) -> Dict[str, str]:
    """Extract and validate input parameters from event"""

    input_type = event.get('input_type', 'direct')

    if input_type == 's3':
        # Read main configuration from S3
        if 's3_bucket' not in event or 's3_key' not in event:
            raise ValueError("s3_bucket and s3_key are required when input_type is 's3'")

        bucket = event['s3_bucket']
        key = event['s3_key']

        logger.info(f"Reading input from S3: s3://{bucket}/{key}")

        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            s3_content = response['Body'].read().decode('utf-8')
            input_data = json.loads(s3_content)
        except Exception as e:
            raise ValueError(f"Failed to read from S3: {str(e)}")

    else:
        # Use direct input from event
        input_data = event.copy()

    # Validate required parameters
    required_params = [
        'essay_type', 'grade_level', 'source_text_title', 'author',
        'essay_prompt', 'score_range', 'source_text_content',
        'original_rubric_guidelines_s3_url', 'sample_essays_csv_s3_url'
    ]

    missing_params = [param for param in required_params if param not in input_data]
    if missing_params:
        raise ValueError(f"Missing required parameters: {', '.join(missing_params)}")

    return input_data

def process_s3_files(input_data: Dict[str, str]) -> Dict[str, str]:
    """Process S3 files to extract content"""

    processed_data = input_data.copy()

    # Process PDF rubric guidelines
    logger.info("Processing PDF rubric guidelines from S3")
    pdf_content = download_and_extract_pdf_text(input_data['original_rubric_guidelines_s3_url'])
    processed_data['original_rubric_guidelines'] = pdf_content

    # Process CSV sample essays
    logger.info("Processing CSV sample essays from S3")
    csv_content = download_and_format_csv_essays(input_data['sample_essays_csv_s3_url'])
    processed_data['sample_essays_from_csv'] = csv_content

    return processed_data

def download_and_extract_pdf_text(s3_url: str) -> str:
    """Download PDF from S3 and extract text content"""

    try:
        # Parse S3 URL
        bucket, key = parse_s3_url(s3_url)

        logger.info(f"Downloading PDF from s3://{bucket}/{key}")

        # Download PDF from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        pdf_content = response['Body'].read()

        # Extract text from PDF using PyPDF2
        try:
            import PyPDF2
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
            text_content = ""

            for page in pdf_reader.pages:
                text_content += page.extract_text() + "\n"

            logger.info(f"Successfully extracted {len(text_content)} characters from PDF")
            return text_content.strip()

        except ImportError:
            # Fallback: Try to read as text (if PDF is text-based)
            logger.warning("PyPDF2 not available, attempting to read PDF as plain text")
            try:
                text_content = pdf_content.decode('utf-8', errors='ignore')
                return text_content.strip()
            except Exception:
                raise ValueError("Cannot process PDF file - PyPDF2 library required for PDF processing")

    except Exception as e:
        logger.error(f"Error processing PDF: {str(e)}")
        raise ValueError(f"Failed to process PDF from {s3_url}: {str(e)}")

def download_and_format_csv_essays(s3_url: str) -> str:
    """Download CSV from S3 and format essay data"""

    try:
        # Parse S3 URL
        bucket, key = parse_s3_url(s3_url)

        logger.info(f"Downloading CSV from s3://{bucket}/{key}")

        # Download CSV from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        csv_content = response['Body'].read().decode('utf-8')

        # Parse CSV
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        essays_data = list(csv_reader)

        logger.info(f"Successfully parsed {len(essays_data)} essays from CSV")

        # Format essays for prompt
        formatted_essays = format_essays_for_prompt(essays_data)

        return formatted_essays

    except Exception as e:
        logger.error(f"Error processing CSV: {str(e)}")
        raise ValueError(f"Failed to process CSV from {s3_url}: {str(e)}")

def format_essays_for_prompt(essays_data: List[Dict[str, str]]) -> str:
    """Format CSV essay data for inclusion in the Bedrock prompt"""

    formatted_text = ""

    # Group essays by score
    essays_by_score = {}
    for essay in essays_data:
        score = essay.get('EssayScore', 'Unknown')
        if score not in essays_by_score:
            essays_by_score[score] = []
        essays_by_score[score].append(essay)

    # Format essays by score level
    for score in sorted(essays_by_score.keys()):
        formatted_text += f"\n=== SCORE {score} EXAMPLES ===\n"

        # Take up to 3 examples per score level to avoid overly long prompts
        examples = essays_by_score[score][:3]

        for i, essay in enumerate(examples, 1):
            essay_response = essay.get('EssayResponse', '').strip()
            score_description = essay.get('ScoreDescription', 'No description available').strip()
            author = essay.get('Author', 'Student')

            formatted_text += f"\nSample Essay {i} (Score {score}):\n"
            formatted_text += f"Author: {author}\n"
            formatted_text += f"Student Response: \"{essay_response[:500]}{'...' if len(essay_response) > 500 else ''}\"\n"
            formatted_text += f"Score Rationale: \"{score_description[:300]}{'...' if len(score_description) > 300 else ''}\"\n"
            formatted_text += "---\n"

    logger.info(f"Formatted {len(essays_data)} essays into {len(formatted_text)} characters")

    return formatted_text

def parse_s3_url(s3_url: str) -> tuple:
    """Parse S3 URL to extract bucket and key"""

    try:
        # Handle both s3://bucket/key and https://bucket.s3.region.amazonaws.com/key formats
        if s3_url.startswith('s3://'):
            parsed = urlparse(s3_url)
            bucket = parsed.netloc
            key = parsed.path.lstrip('/')
        elif 's3.' in s3_url and 'amazonaws.com' in s3_url:
            # Parse HTTPS S3 URL
            parsed = urlparse(s3_url)
            bucket = parsed.netloc.split('.')[0]
            key = parsed.path.lstrip('/')
        else:
            raise ValueError(f"Invalid S3 URL format: {s3_url}")

        if not bucket or not key:
            raise ValueError(f"Could not extract bucket and key from S3 URL: {s3_url}")

        return bucket, key

    except Exception as e:
        raise ValueError(f"Failed to parse S3 URL {s3_url}: {str(e)}")

def generate_rubric_with_bedrock(input_data: Dict[str, str]) -> Dict[str, Any]:
    """Call Bedrock to generate rubric using the prompt"""

    # Construct the Bedrock prompt
    prompt = construct_bedrock_prompt(input_data)

    logger.info("Calling Bedrock to generate rubric")

    try:
        # Use the Conversation API for Amazon Nova models
        conversation = [
            {
                "role": "user",
                "content": [{"text": prompt}]
            }
        ]

        response = bedrock_client.converse(
            modelId='amazon.nova-pro-v1:0',
            messages=conversation,
            inferenceConfig={
                "maxTokens": 8000,
                "temperature": 0.1,
                "topP": 0.9
            }
        )

        # Extract text from Nova Pro response
        rubric_text = response['output']['message']['content'][0]['text']

        logger.info(f"Received response from Bedrock: {len(rubric_text)} characters")

        # Parse the JSON response from Bedrock
        try:
            rubric_json = json.loads(rubric_text)
            logger.info("Successfully parsed Bedrock response as JSON")
            return rubric_json
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Bedrock response as JSON: {str(e)}")
            logger.error(f"Bedrock response: {rubric_text[:500]}...")
            raise ValueError(f"Bedrock did not return valid JSON: {str(e)}")

    except Exception as e:
        logger.error(f"Error calling Bedrock: {str(e)}")
        raise

def construct_bedrock_prompt(input_data: Dict[str, str]) -> str:
    """Construct the Bedrock prompt with JSON output format"""

    prompt = f"""You are an expert educational assessment specialist tasked with generating comprehensive, detailed rubrics for student essay evaluation. Create a detailed scoring rubric based on the provided essay context, sample student responses, and scoring guidelines.

## Essay Context
**Essay Type:** {input_data['essay_type']}
**Grade Level:** {input_data['grade_level']}
**Source Text:** {input_data['source_text_title']} by {input_data['author']}
**Essay Prompt:** {input_data['essay_prompt']}
**Scoring Range:** {input_data['score_range']}

## Source Text Summary
{input_data['source_text_content']}

## Original Rubric Guidelines
{input_data['original_rubric_guidelines']}

## Sample Student Responses for Context
Below are sample student essays from the CSV dataset with their scores and explanations to help inform the detailed rubric creation. These examples represent actual student work and scoring patterns:

{input_data.get('sample_essays_from_csv', 'No sample essays provided')}

## Task Requirements
Generate a comprehensive, detailed rubric that expands upon the basic guidelines provided. Use the sample student essays and their scoring rationales to understand the practical application of each score level.

## Output Format
**CRITICAL: Your response must be a valid JSON object only, with no additional text before or after.**

Structure your response as a JSON object with this exact format:

{{
  "essay_type": "{input_data['essay_type']}",
  "essay_title": "{input_data['source_text_title']}",
  "author": "{input_data['author']}",
  "grade_level": {input_data['grade_level']},
  "essay_question": "{input_data['essay_prompt']}",
  "score_range": "{input_data['score_range']}",
  "rubrics": {{
    "score_3": {{
      "score_label": "EXEMPLARY RESPONSE",
      "overall_performance": "[Detailed description of exemplary work]",
      "content_understanding": "[Specific criteria as detailed text]",
      "question_addressing": "[Specific criteria as detailed text]",
      "use_of_textual_evidence": "[Specific criteria as detailed text]",
      "analysis_and_interpretation": "[Specific criteria as detailed text]",
      "writing_quality": "[Specific criteria as detailed text]",
      "specific_examples": "[Example indicators as detailed text]",
      "look_for": "[Key characteristics as detailed text]",
      "avoid_confusing_with": "[Common misconceptions as detailed text]"
    }},
    "score_2": {{
      "score_label": "PROFICIENT RESPONSE",
      "overall_performance": "[Detailed description]",
      "content_understanding": "[Specific criteria as detailed text]",
      "question_addressing": "[Specific criteria as detailed text]",
      "use_of_textual_evidence": "[Specific criteria as detailed text]",
      "analysis_and_interpretation": "[Specific criteria as detailed text]",
      "writing_quality": "[Specific criteria as detailed text]",
      "specific_examples": "[Example indicators as detailed text]",
      "look_for": "[Key characteristics as detailed text]",
      "avoid_confusing_with": "[Common misconceptions as detailed text]"
    }},
    "score_1": {{
      "score_label": "DEVELOPING RESPONSE",
      "overall_performance": "[Detailed description]",
      "content_understanding": "[Specific criteria as detailed text]",
      "question_addressing": "[Specific criteria as detailed text]",
      "use_of_textual_evidence": "[Specific criteria as detailed text]",
      "analysis_and_interpretation": "[Specific criteria as detailed text]",
      "writing_quality": "[Specific criteria as detailed text]",
      "specific_examples": "[Example indicators as detailed text]",
      "look_for": "[Key characteristics as detailed text]",
      "avoid_confusing_with": "[Common misconceptions as detailed text]"
    }},
    "score_0": {{
      "score_label": "INADEQUATE RESPONSE",
      "overall_performance": "[Detailed description]",
      "content_understanding": "[Specific criteria as detailed text]",
      "question_addressing": "[Specific criteria as detailed text]",
      "use_of_textual_evidence": "[Specific criteria as detailed text]",
      "analysis_and_interpretation": "[Specific criteria as detailed text]",
      "writing_quality": "[Specific criteria as detailed text]",
      "specific_examples": "[Example indicators as detailed text]",
      "look_for": "[Key characteristics as detailed text]",
      "avoid_confusing_with": "[Common misconceptions as detailed text]"
    }}
  }},
  "scoring_guidance": {{
    "borderline_cases": {{
      "between_2_3": "[Specific guidance for borderline 2-3 scores]",
      "between_1_2": "[Specific guidance for borderline 1-2 scores]",
      "between_0_1": "[Specific guidance for borderline 0-1 scores]"
    }},
    "common_pitfalls": "[List of common scoring errors to avoid as detailed text]",
    "quality_assurance_checklist": "[Checklist items as detailed text]"
  }}
}}

**IMPORTANT FORMATTING NOTES:**
- Ensure all text within quotes is properly escaped for JSON
- Replace bullet points with paragraph format
- Keep all detailed content as continuous text within each field
- Do not include any markdown formatting within the JSON values
- Output ONLY the JSON object, no other text"""

    return prompt

def store_rubric_in_dynamodb(input_data: Dict[str, str], rubric_json: Dict[str, Any]) -> Dict[str, Any]:
    """Store the generated rubric in DynamoDB"""

    # Prepare DynamoDB item
    item = {
        'essay_type': input_data['essay_type'],
        'content_id': input_data['content_id'],
        'essay_title': rubric_json.get('essay_title', input_data['source_text_title']),
        'author': rubric_json.get('author', input_data['author']),
        'grade_level': int(rubric_json.get('grade_level', input_data['grade_level'])),
        'essay_question': rubric_json.get('essay_question', input_data['essay_prompt']),
        'score_range': rubric_json.get('score_range', input_data['score_range']),
        'created_timestamp': datetime.utcnow().isoformat() + 'Z',
        'rubric_version': '1.0',
        'generation_id': str(uuid.uuid4()),
        'source_files': {
            'pdf_rubric_url': input_data.get('original_rubric_guidelines_s3_url'),
            'csv_essays_url': input_data.get('sample_essays_csv_s3_url')
        },
        'rubrics': rubric_json.get('rubrics', {}),
        'scoring_guidance': rubric_json.get('scoring_guidance', {})
    }

    try:
        response = table.put_item(Item=item)
        logger.info("Successfully stored rubric in DynamoDB")
        return response

    except Exception as e:
        logger.error(f"Error storing rubric in DynamoDB: {str(e)}")
        raise

def get_rubric_from_dynamodb(essay_type: str, content_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a rubric from DynamoDB (utility function)"""

    try:
        response = table.get_item(
            Key={
                'essay_type': essay_type,
                'content_id': content_id
            }
        )

        return response.get('Item')

    except Exception as e:
        logger.error(f"Error retrieving rubric from DynamoDB: {str(e)}")
        return None

def list_rubrics_by_type(essay_type: str) -> list:
    """List all rubrics for a specific essay type (utility function)"""

    try:
        response = table.query(
            KeyConditionExpression='essay_type = :essay_type',
            ExpressionAttributeValues={
                ':essay_type': essay_type
            }
        )

        return response.get('Items', [])

    except Exception as e:
        logger.error(f"Error querying rubrics by type: {str(e)}")
        return []