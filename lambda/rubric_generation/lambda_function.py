import json
import boto3
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from boto3.dynamodb.conditions import Key
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
bedrock_client = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')

# Configuration
RUBRICS_TABLE = 'ku_rubrics'
S3_BUCKET = 'ku-output-grading-bucket'
rubrics_table = dynamodb.Table(RUBRICS_TABLE)

# Cache for rubrics to avoid repeated DynamoDB calls
rubric_cache = {}

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Unified Lambda function to grade student essays (single or bulk) using Bedrock and stored rubrics

    Input formats:

    Single Essay:
    {
        "student_id": "student123",
        "item_id": "1",
        "essay_type": "Source Dependent Responses",
        "essay_response": "Student essay text here..."
    }

    Bulk Essays:
    {
        "essays": [
            {
                "student_id": "student123",
                "item_id": "1",
                "essay_type": "Source Dependent Responses",
                "essay_response": "Student essay text here..."
            },
            {
                "student_id": "student456",
                "item_id": "2",
                "essay_type": "Argumentative Writing",
                "essay_response": "Another student essay text here..."
            }
        ],
        "batch_id": "optional_batch_id",
        "s3_output_prefix": "optional/s3/prefix/",
        "store_in_s3": true  // Optional, defaults to true for bulk
    }
    """

    # Handle CORS preflight requests
    if event.get('httpMethod') == 'OPTIONS':
        return create_cors_response({'message': 'CORS preflight'})

    try:
        start_time = time.time()
        logger.info(f"Received grading request: {json.dumps(event, default=str)}")

        # Extract request body for API Gateway integration
        request_data = extract_request_data(event)

        # Determine processing mode and execute
        if 'essays' in request_data:
            # Bulk processing mode
            result = process_bulk_essays(request_data, context)
        else:
            # Single essay processing mode
            result = process_single_essay(request_data)

        processing_time = time.time() - start_time
        result['processing_time_seconds'] = round(processing_time, 2)

        return create_cors_response(result)

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return create_cors_response({
            'error': 'Internal server error',
            'message': str(e)
        }, status_code=500)

def extract_request_data(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract request data from event (handles API Gateway and direct invocation)"""

    if 'body' in event:
        if isinstance(event['body'], str):
            return json.loads(event['body'])
        else:
            return event['body']
    else:
        # Direct Lambda invocation
        return event

def create_cors_response(body: Dict[str, Any], status_code: int = 200) -> Dict[str, Any]:
    """Create standardized CORS response"""

    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
            'Access-Control-Allow-Methods': 'POST,OPTIONS'
        },
        'body': json.dumps(body, default=str)
    }

def process_single_essay(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single essay and return result directly"""

    logger.info("Processing single essay")

    try:
        # Extract and validate input parameters
        input_data = extract_and_validate_input(request_data)

        # Retrieve rubric from DynamoDB (with caching)
        rubric_data = get_cached_rubric(input_data['essay_type'])

        # Grade the essay using Bedrock
        grading_result = grade_essay_with_bedrock(input_data, rubric_data)

        # Prepare output response
        essay_result = prepare_grading_response(input_data, rubric_data, grading_result)

        return {
            'processing_mode': 'single',
            'processing_status': 'completed',
            'student_id': input_data['student_id'],
            'essay_type': input_data['essay_type'],
            'result': essay_result
        }

    except Exception as e:
        logger.error(f"Error processing single essay: {str(e)}")
        return {
            'processing_mode': 'single',
            'processing_status': 'failed',
            'error': str(e)
        }

def process_bulk_essays(request_data: Dict[str, Any], context) -> Dict[str, Any]:
    """Process multiple essays in bulk"""

    essays = request_data.get('essays', [])
    batch_id = request_data.get('batch_id', f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}")
    s3_output_prefix = request_data.get('s3_output_prefix', f"grading_results/{datetime.utcnow().strftime('%Y/%m/%d')}/")
    store_in_s3 = request_data.get('store_in_s3', True)

    logger.info(f"Processing bulk batch: {batch_id} with {len(essays)} essays")

    if not essays:
        raise ValueError("No essays provided in bulk request")

    # Validate all essays first
    validated_essays = []
    validation_errors = []

    for i, essay_data in enumerate(essays):
        try:
            validated_essay = extract_and_validate_input(essay_data)
            validated_essays.append((i, validated_essay))
        except Exception as e:
            validation_errors.append({
                'essay_index': i,
                'error': str(e),
                'student_id': essay_data.get('student_id', 'unknown')
            })

    logger.info(f"Validated {len(validated_essays)} essays, {len(validation_errors)} validation errors")

    # Pre-load rubrics for all unique essay types
    unique_essay_types = set(essay[1]['essay_type'] for essay in validated_essays)
    logger.info(f"Unique essay types in batch: {list(unique_essay_types)}")

    rubric_load_errors = []
    for essay_type in unique_essay_types:
        try:
            get_cached_rubric(essay_type)
            logger.info(f"Successfully cached rubric for: {essay_type}")
        except Exception as e:
            rubric_load_errors.append({
                'essay_type': essay_type,
                'error': str(e)
            })
            logger.error(f"Failed to load rubric for {essay_type}: {str(e)}")

    # Process essays in parallel with controlled concurrency
    max_concurrent_requests = min(5, len(validated_essays))
    grading_results = []
    grading_errors = []

    logger.info(f"Processing {len(validated_essays)} essays with max {max_concurrent_requests} concurrent requests")

    # Check remaining execution time and adjust concurrency
    remaining_time = context.get_remaining_time_in_millis() if context else 300000
    if remaining_time < 30000:  # Less than 30 seconds remaining
        logger.warning(f"Limited execution time remaining: {remaining_time}ms. Processing sequentially.")
        max_concurrent_requests = 1

    with ThreadPoolExecutor(max_workers=max_concurrent_requests) as executor:
        # Submit grading tasks for essays with valid rubrics
        future_to_essay = {}
        for essay_index, essay_data in validated_essays:
            if essay_data['essay_type'] not in [error['essay_type'] for error in rubric_load_errors]:
                future = executor.submit(grade_single_essay_safe, essay_index, essay_data)
                future_to_essay[future] = (essay_index, essay_data)

        # Collect results as they complete
        for future in as_completed(future_to_essay):
            essay_index, essay_data = future_to_essay[future]
            try:
                result = future.result(timeout=120)  # 2 minute timeout per essay
                if result['success']:
                    grading_results.append(result['data'])
                    logger.info(f"Successfully graded essay {essay_index} for student {essay_data['student_id']}")
                else:
                    grading_errors.append({
                        'essay_index': essay_index,
                        'student_id': essay_data['student_id'],
                        'error': result['error']
                    })
                    logger.error(f"Failed to grade essay {essay_index}: {result['error']}")
            except Exception as e:
                grading_errors.append({
                    'essay_index': essay_index,
                    'student_id': essay_data.get('student_id', 'unknown'),
                    'error': f"Processing timeout or error: {str(e)}"
                })
                logger.error(f"Essay {essay_index} processing failed: {str(e)}")

    # Prepare batch response
    batch_response = {
        'processing_mode': 'bulk',
        'batch_id': batch_id,
        'processing_status': 'completed',
        'summary': {
            'total_essays_submitted': len(essays),
            'total_essays_validated': len(validated_essays),
            'total_essays_graded': len(grading_results),
            'total_validation_errors': len(validation_errors),
            'total_rubric_load_errors': len(rubric_load_errors),
            'total_grading_errors': len(grading_errors)
        },
        'unique_essay_types': list(unique_essay_types),
        'results': grading_results,  # Include results in response
        'errors': {
            'validation_errors': validation_errors,
            'rubric_load_errors': rubric_load_errors,
            'grading_errors': grading_errors
        }
    }

    # Store results in S3 if requested
    if store_in_s3 and grading_results:
        try:
            s3_results = store_results_in_s3(batch_id, grading_results, s3_output_prefix, batch_response)
            batch_response['s3_storage'] = s3_results
            logger.info(f"Successfully stored batch results in S3")
        except Exception as e:
            logger.error(f"Failed to store results in S3: {str(e)}")
            batch_response['s3_storage'] = {
                'success': False,
                'error': str(e)
            }
    elif store_in_s3:
        batch_response['s3_storage'] = {
            'success': False,
            'message': 'No results to store'
        }

    logger.info(f"Bulk processing completed for batch {batch_id}")
    return batch_response

def grade_single_essay_safe(essay_index: int, essay_data: Dict[str, str]) -> Dict[str, Any]:
    """Grade a single essay with error handling for parallel processing"""

    try:
        logger.info(f"Starting to grade essay {essay_index} for student {essay_data['student_id']}")

        # Get rubric (should be cached)
        rubric_data = get_cached_rubric(essay_data['essay_type'])

        # Grade the essay
        grading_result = grade_essay_with_bedrock(essay_data, rubric_data)

        # Prepare response
        response = prepare_grading_response(essay_data, rubric_data, grading_result)
        response['essay_index'] = essay_index

        return {
            'success': True,
            'data': response
        }

    except Exception as e:
        logger.error(f"Error grading essay {essay_index}: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'essay_index': essay_index,
            'student_id': essay_data.get('student_id', 'unknown')
        }

def get_cached_rubric(essay_type: str) -> Dict[str, Any]:
    """Get rubric with caching to avoid repeated DynamoDB calls"""

    if essay_type in rubric_cache:
        logger.info(f"Using cached rubric for essay type: {essay_type}")
        return rubric_cache[essay_type]

    logger.info(f"Loading rubric from DynamoDB for essay type: {essay_type}")
    rubric_data = get_rubric_for_essay_type(essay_type)
    rubric_cache[essay_type] = rubric_data

    return rubric_data

def store_results_in_s3(batch_id: str, grading_results: List[Dict[str, Any]], s3_output_prefix: str, batch_response: Dict[str, Any]) -> Dict[str, Any]:
    """Store grading results in S3"""

    try:
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')

        # Store complete batch results (includes results + metadata)
        batch_results_key = f"{s3_output_prefix}batch_results/{timestamp}_{batch_id}_complete.json"
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=batch_results_key,
            Body=json.dumps(batch_response, default=str, indent=2),
            ContentType='application/json'
        )

        # Store just the grading results array for easier processing
        results_only_key = f"{s3_output_prefix}results_only/{timestamp}_{batch_id}_results.json"
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=results_only_key,
            Body=json.dumps(grading_results, default=str, indent=2),
            ContentType='application/json'
        )

        # Store aggregated results by essay type
        aggregated_results = aggregate_results_by_essay_type(grading_results)
        aggregated_results_key = f"{s3_output_prefix}aggregated/{timestamp}_{batch_id}_aggregated.json"
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=aggregated_results_key,
            Body=json.dumps(aggregated_results, default=str, indent=2),
            ContentType='application/json'
        )

        logger.info(f"Successfully stored {len(grading_results)} results in S3")

        return {
            'success': True,
            'total_results_stored': len(grading_results),
            's3_locations': {
                'complete_batch': f"s3://{S3_BUCKET}/{batch_results_key}",
                'results_only': f"s3://{S3_BUCKET}/{results_only_key}",
                'aggregated_results': f"s3://{S3_BUCKET}/{aggregated_results_key}"
            }
        }

    except Exception as e:
        logger.error(f"Error storing results in S3: {str(e)}")
        raise

def aggregate_results_by_essay_type(grading_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate grading results by essay type for analysis"""

    aggregated = {}

    for result in grading_results:
        essay_type = result.get('essay_type', 'unknown')

        if essay_type not in aggregated:
            aggregated[essay_type] = {
                'essay_type': essay_type,
                'total_essays': 0,
                'average_score': 0,
                'score_distribution': {},
                'average_confidence': 0,
                'flagged_essays': 0
            }

        agg = aggregated[essay_type]
        agg['total_essays'] += 1

        # Score aggregation
        essay_score = result.get('essay_score', 0)
        current_avg = agg['average_score']
        agg['average_score'] = (current_avg * (agg['total_essays'] - 1) + essay_score) / agg['total_essays']

        # Score distribution
        score_str = str(essay_score)
        agg['score_distribution'][score_str] = agg['score_distribution'].get(score_str, 0) + 1

        # Confidence aggregation
        ai_confidence = result.get('ai_confidence', 0)
        current_conf_avg = agg['average_confidence']
        agg['average_confidence'] = (current_conf_avg * (agg['total_essays'] - 1) + ai_confidence) / agg['total_essays']

        # Flagged essays
        if result.get('essay_flagged', '').lower() == 'yes':
            agg['flagged_essays'] += 1

    # Round averages
    for essay_type in aggregated:
        aggregated[essay_type]['average_score'] = round(aggregated[essay_type]['average_score'], 2)
        aggregated[essay_type]['average_confidence'] = round(aggregated[essay_type]['average_confidence'], 1)

    return aggregated

def extract_and_validate_input(event: Dict[str, Any]) -> Dict[str, str]:
    """Extract and validate input parameters"""

    required_params = ['student_id', 'item_id', 'essay_type', 'essay_response']

    for param in required_params:
        if param not in event:
            raise ValueError(f"Missing required parameter: {param}")

    # Validate essay_response is not empty
    if not event['essay_response'].strip():
        raise ValueError("essay_response cannot be empty")

    return {
        'student_id': str(event['student_id']),
        'item_id': str(event['item_id']),
        'essay_type': event['essay_type'],
        'essay_response': event['essay_response'].strip()
    }

def get_rubric_for_essay_type(essay_type: str) -> Dict[str, Any]:
    """Retrieve the most recent rubric for the given essay type"""

    try:
        logger.info(f"Querying rubrics for essay type: {essay_type}")

        # Query DynamoDB for rubrics of this essay type
        response = rubrics_table.query(
            KeyConditionExpression=Key('essay_type').eq(essay_type),
            ScanIndexForward=False,  # Get newest first
            Limit=1
        )

        # LOG THE RAW DYNAMODB RESPONSE
        logger.info("=== RAW DYNAMODB RESPONSE ===")
        logger.info(f"DynamoDB response: {json.dumps(response, default=str, indent=2)}")
        logger.info(f"Items count: {len(response.get('Items', []))}")

        if not response['Items']:
            raise ValueError(f"No rubric found for essay type: {essay_type}")

        rubric = response['Items'][0]

        # LOG THE RETRIEVED RUBRIC IN DETAIL
        logger.info("=== RETRIEVED RUBRIC DETAILED ANALYSIS ===")
        logger.info(f"Rubric essay_id: {rubric.get('essay_id', 'NOT_FOUND')}")
        logger.info(f"Rubric keys: {list(rubric.keys())}")

        # Log each top-level key and its type/structure
        for key, value in rubric.items():
            logger.info(f"Key '{key}': type={type(value)}, value_preview={str(value)[:200]}...")

        return rubric

    except Exception as e:
        logger.error(f"Error retrieving rubric: {str(e)}")
        raise ValueError(f"Failed to retrieve rubric for essay type '{essay_type}': {str(e)}")

def grade_essay_with_bedrock(input_data: Dict[str, str], rubric_data: Dict[str, Any]) -> Dict[str, Any]:
    """Use Bedrock to grade the essay based on the rubric"""

    # Construct grading prompt
    prompt = construct_grading_prompt(input_data, rubric_data)

    logger.info("Calling Bedrock to grade essay")

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
                "maxTokens": 3000,
                "temperature": 0.1,
                "topP": 0.9
            }
        )

        # Extract text from Nova Pro response
        grading_text = response['output']['message']['content'][0]['text']

        logger.info(f"Received grading response: {len(grading_text)} characters")

        # Parse the JSON response from Bedrock
        try:
            grading_result = json.loads(grading_text)
            logger.info("Successfully parsed Bedrock grading response as JSON")
            return grading_result
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Bedrock response as JSON: {str(e)}")
            logger.error(f"Bedrock response: {grading_text[:500]}...")
            raise ValueError(f"Bedrock did not return valid JSON: {str(e)}")

    except Exception as e:
        logger.error(f"Error calling Bedrock for grading: {str(e)}")
        raise

def construct_grading_prompt(input_data: Dict[str, str], rubric_data: Dict[str, Any]) -> str:
    """Construct the grading prompt for Bedrock"""

    # Enhanced logging for rubric data debugging
    logger.info("=== ENHANCED RUBRIC DATA DEBUGGING ===")
    logger.info(f"Complete rubric data keys: {list(rubric_data.keys())}")
    logger.info(f"Complete rubric data: {json.dumps(rubric_data, default=str, indent=2)}")

    # Extract rubrics section with detailed logging
    rubrics = rubric_data.get('rubrics', {})
    logger.info(f"=== RUBRICS SECTION ANALYSIS ===")
    logger.info(f"Rubrics exists: {rubrics is not None}")
    logger.info(f"Rubrics type: {type(rubrics)}")
    logger.info(f"Rubrics keys: {list(rubrics.keys()) if isinstance(rubrics, dict) else 'NOT_A_DICT'}")

    if isinstance(rubrics, dict):
        for rubric_key, rubric_value in rubrics.items():
            logger.info(f"Rubric '{rubric_key}': type={type(rubric_value)}")
            if isinstance(rubric_value, dict):
                logger.info(f"  Keys in '{rubric_key}': {list(rubric_value.keys())}")
                # If it's DynamoDB format, log the 'M' section
                if 'M' in rubric_value:
                    logger.info(f"  DynamoDB 'M' keys in '{rubric_key}': {list(rubric_value['M'].keys())}")

    scoring_guidance = rubric_data.get('scoring_guidance', {})
    logger.info(f"Scoring guidance type: {type(scoring_guidance)}")
    logger.info(f"Scoring guidance: {json.dumps(scoring_guidance, default=str, indent=2)}")

    # Handle essay_question and score_range with detailed logging
    essay_question = rubric_data.get('essay_question', 'Not specified')
    logger.info(f"Raw essay_question: {essay_question} (type: {type(essay_question)})")

    if isinstance(essay_question, dict) and 'S' in essay_question:
        essay_question = essay_question['S']
        logger.info(f"Extracted essay_question from DynamoDB format: {essay_question}")

    score_range = rubric_data.get('score_range', '0-3')
    logger.info(f"Raw score_range: {score_range} (type: {type(score_range)})")

    if isinstance(score_range, dict) and 'S' in score_range:
        score_range = score_range['S']
        logger.info(f"Extracted score_range from DynamoDB format: {score_range}")

    # Extract metrics with ENHANCED debugging
    metrics = []
    if rubrics:
        logger.info("=== ENHANCED METRICS EXTRACTION ===")
        logger.info(f"Available rubric score keys: {list(rubrics.keys())}")

        # Try to get a sample score to extract metrics from
        sample_score_key = None
        sample_score = None

        # Try different score keys in order of preference
        for potential_key in ['score_3', 'score_2', 'score_1', 'score_0']:
            if potential_key in rubrics:
                sample_score_key = potential_key
                sample_score = rubrics[potential_key]
                logger.info(f"Using '{potential_key}' as sample for metric extraction")
                break

        if sample_score is None and rubrics:
            # If no standard score keys found, use the first available
            sample_score_key = next(iter(rubrics.keys()))
            sample_score = rubrics[sample_score_key]
            logger.info(f"No standard score keys found, using first available: '{sample_score_key}'")

        if sample_score is not None:
            logger.info(f"Sample score key: {sample_score_key}")
            logger.info(f"Sample score type: {type(sample_score)}")
            logger.info(f"Sample score content: {json.dumps(sample_score, default=str, indent=2)}")

            # Handle DynamoDB format
            if isinstance(sample_score, dict) and 'M' in sample_score:
                logger.info("Processing DynamoDB format for metrics extraction")
                sample_data = sample_score['M']
                logger.info(f"DynamoDB 'M' section keys: {list(sample_data.keys())}")

                # Log each key and its structure
                for key, value in sample_data.items():
                    logger.info(f"  Key '{key}': type={type(value)}, structure={value}")

                # Extract metrics (exclude metadata fields)
                excluded_keys = ['score_label', 'avoid_confusing_with', 'look_for', 'specific_examples']
                logger.info(f"Excluded keys: {excluded_keys}")

                metrics = [key for key in sample_data.keys() if key not in excluded_keys]
                logger.info(f"Extracted metrics (DynamoDB format): {metrics}")

            elif isinstance(sample_score, dict):
                logger.info("Processing regular dict format for metrics extraction")
                logger.info(f"Regular dict keys: {list(sample_score.keys())}")

                # Log each key and its value
                for key, value in sample_score.items():
                    logger.info(f"  Key '{key}': type={type(value)}, value_preview={str(value)[:100]}...")

                # Extract metrics (exclude metadata fields)
                excluded_keys = ['score_label', 'avoid_confusing_with', 'look_for', 'specific_examples']
                logger.info(f"Excluded keys: {excluded_keys}")

                metrics = [key for key in sample_score.keys() if key not in excluded_keys]
                logger.info(f"Extracted metrics (regular format): {metrics}")

            else:
                logger.error(f"Unexpected sample_score format: {type(sample_score)}")
                logger.error(f"Sample score content: {sample_score}")
        else:
            logger.error("No sample score found for metrics extraction")
    else:
        logger.error("No rubrics section found in rubric_data")

    # FINAL METRICS VALIDATION
    logger.info("=== FINAL METRICS VALIDATION ===")
    logger.info(f"Final extracted metrics: {metrics}")
    logger.info(f"Total metrics count: {len(metrics)}")
    logger.info(f"Metrics list: {json.dumps(metrics, indent=2)}")

    if not metrics:
        logger.error("ERROR: No metrics were extracted from the rubric!")
        logger.error("This will cause issues with grading prompt construction")

        # Try alternative extraction method
        logger.info("=== ATTEMPTING ALTERNATIVE METRIC EXTRACTION ===")
        if rubrics:
            for score_key, score_data in rubrics.items():
                logger.info(f"Analyzing {score_key} for alternative extraction...")
                if isinstance(score_data, dict):
                    if 'M' in score_data:
                        all_keys = list(score_data['M'].keys())
                    else:
                        all_keys = list(score_data.keys())
                    logger.info(f"All keys in {score_key}: {all_keys}")

    # Extract scoring guidance with DynamoDB format handling
    borderline_cases = scoring_guidance.get('borderline_cases', {})
    if isinstance(borderline_cases, dict) and 'M' in borderline_cases:
        borderline_cases = borderline_cases['M']
        between_2_3 = borderline_cases.get('between_2_3', {}).get('S', '') if 'between_2_3' in borderline_cases else ''
        between_1_2 = borderline_cases.get('between_1_2', {}).get('S', '') if 'between_1_2' in borderline_cases else ''
        between_0_1 = borderline_cases.get('between_0_1', {}).get('S', '') if 'between_0_1' in borderline_cases else ''
    else:
        between_2_3 = borderline_cases.get('between_2_3', '')
        between_1_2 = borderline_cases.get('between_1_2', '')
        between_0_1 = borderline_cases.get('between_0_1', '')

    common_pitfalls = scoring_guidance.get('common_pitfalls', '')
    if isinstance(common_pitfalls, dict) and 'S' in common_pitfalls:
        common_pitfalls = common_pitfalls['S']

    # Build detailed rubric description with enhanced logging
    rubric_details = ""
    logger.info("=== BUILDING RUBRIC DETAILS ===")

    for score_key in ['score_3', 'score_2', 'score_1', 'score_0']:
        if score_key in rubrics:
            logger.info(f"Processing {score_key} for rubric details...")
            score_num = score_key.split('_')[1]
            score_data = rubrics[score_key]

            # Log the processing of each score level
            logger.info(f"Score {score_num} data type: {type(score_data)}")

            # Handle DynamoDB format
            if isinstance(score_data, dict) and 'M' in score_data:
                score_data = score_data['M']
                score_label = score_data.get('score_label', {}).get('S', f'Score {score_num}')
                logger.info(f"Score {score_num} label: {score_label}")

                rubric_details += f"\n## SCORE {score_num} - {score_label}\n"

                for metric in metrics:
                    if metric in score_data:
                        metric_value = score_data[metric].get('S', '') if isinstance(score_data[metric], dict) else score_data[metric]
                        logger.info(f"Score {score_num}, Metric '{metric}': {len(str(metric_value))} chars")
                        rubric_details += f"{metric.replace('_', ' ').title()}: {metric_value}\n"
                    else:
                        logger.warning(f"Metric '{metric}' not found in {score_key}")
            else:
                # Handle regular dict format
                score_label = score_data.get('score_label', f'Score {score_num}')
                logger.info(f"Score {score_num} label: {score_label}")

                rubric_details += f"\n## SCORE {score_num} - {score_label}\n"

                for metric in metrics:
                    if metric in score_data:
                        logger.info(f"Score {score_num}, Metric '{metric}': {len(str(score_data[metric]))} chars")
                        rubric_details += f"{metric.replace('_', ' ').title()}: {score_data[metric]}\n"
                    else:
                        logger.warning(f"Metric '{metric}' not found in {score_key}")

            rubric_details += "\n"
        else:
            logger.warning(f"Score key '{score_key}' not found in rubrics")

    logger.info(f"Final rubric details length: {len(rubric_details)} characters")
    logger.info(f"First 500 chars of rubric details: {rubric_details[:500]}")

    # Build metric scores JSON dynamically
    metric_scores_json = "{\n"
    metric_justifications_json = "{\n"

    for i, metric in enumerate(metrics):
        comma = "," if i < len(metrics) - 1 else ""
        metric_scores_json += f'    "{metric}": [1-4]{comma}\n'
        metric_justifications_json += f'    "{metric}": "[Brief explanation for this score]"{comma}\n'

    metric_scores_json += "  }"
    metric_justifications_json += "  }"

    logger.info(f"Generated metric_scores_json: {metric_scores_json}")
    logger.info(f"Generated metric_justifications_json: {metric_justifications_json}")

    prompt = f"""You are an expert essay grader. Grade the following student essay based on the provided rubric. You must return a JSON response with detailed scoring and justification.

## Essay Information
**Essay Type:** {input_data['essay_type']}
**Essay Question:** {essay_question}
**Score Range:** {score_range}

## Student Essay to Grade:
{input_data['essay_response']}

## Detailed Rubric Criteria:
{rubric_details}

## Scoring Guidance:
**Borderline Cases:** 
- Between 2-3: {between_2_3}
- Between 1-2: {between_1_2}
- Between 0-1: {between_0_1}

**Common Pitfalls:** {common_pitfalls}

## Grading Instructions:
1. Carefully read and analyze the student essay
2. Evaluate it against each score level in the rubric
3. Assign individual metric scores (1-4 scale for each criterion)
4. Determine the overall essay score ({score_range})
5. Provide detailed justification for your scoring decision
6. Assess your confidence level (0-100%)
7. Flag any concerning content if present

## Required JSON Response Format:
{{
  "overall_essay_score": [score from {score_range}],
  "score_justification": "[Detailed explanation of why this score was assigned, referencing specific rubric criteria and essay content]",
  "rubric_metric_scores": {metric_scores_json},
  "metric_justifications": {metric_justifications_json},
  "ai_confidence": [0-100],
  "confidence_explanation": "[Why this confidence level]",
  "essay_flagged": "[Yes/No]",
  "flagged_content": "[Specific text that triggered flag, or empty string if not flagged]",
  "flag_reason": "[Reason for flagging: inappropriate_content, plagiarism_suspected, off_topic, incoherent, or empty string if not flagged]",
  "strengths": "[2-3 specific strengths of the essay]",
  "areas_for_improvement": "[2-3 specific areas where the student could improve]"
}}

**CRITICAL:** Return ONLY the JSON object, no additional text before or after. Ensure all text is properly escaped for JSON format. Do NOT include the essay text in your response."""

    logger.info("=== PROMPT CONSTRUCTION COMPLETE ===")
    logger.info(f"Final prompt length: {len(prompt)} characters")

    return prompt

def prepare_grading_response(input_data: Dict[str, str], rubric_data: Dict[str, Any], grading_result: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare the final grading response"""

    # Generate unique IDs
    essay_id = f"{input_data['essay_type'].replace(' ', '_')}_{input_data['student_id']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    # Extract rubric metric scores
    metric_scores = grading_result.get('rubric_metric_scores', {})

    # Extract metric names dynamically from the rubric (using the same logic as construct_grading_prompt)
    rubrics = rubric_data.get('rubrics', {})
    metrics = []
    if rubrics:
        # Get metrics from any score level (they should be consistent)
        sample_score = next(iter(rubrics.values()))
        if isinstance(sample_score, dict) and 'M' in sample_score:
            # For DynamoDB format with 'M' wrapper
            metrics = [key for key in sample_score['M'].keys()
                      if key not in ['score_label', 'avoid_confusing_with', 'look_for', 'specific_examples']]
        elif isinstance(sample_score, dict):
            # For regular dict format
            metrics = [key for key in sample_score.keys()
                      if key not in ['score_label', 'avoid_confusing_with', 'look_for', 'specific_examples']]

    logger.info(f"=== PREPARE GRADING RESPONSE ===")
    logger.info(f"Extracted metrics for response: {metrics}")
    logger.info(f"Metric scores from grading result: {metric_scores}")

    # Extract essay question with DynamoDB format handling
    essay_question = rubric_data.get('essay_question', '')
    if isinstance(essay_question, dict) and 'S' in essay_question:
        essay_question = essay_question['S']

    response = {
        # Required output fields
        'student_id': input_data['student_id'],
        'item_id': input_data['item_id'],
        'essay_id': essay_id,
        'essay_type': input_data['essay_type'],
        'essay_question': essay_question,
        # essay_response removed to save tokens
        'essay_score': grading_result.get('overall_essay_score', 0),
        'score_description': grading_result.get('score_justification', ''),

        # AI assessment fields
        'ai_confidence': grading_result.get('ai_confidence', 0),
        'confidence_explanation': grading_result.get('confidence_explanation', ''),

        # Manual override fields (default values)
        'manual_override': 'No',
        'manual_essay_score': None,

        # Flagging fields
        'essay_flagged': grading_result.get('essay_flagged', 'No'),
        'flagged_content': grading_result.get('flagged_content', ''),
        'flag_reason': grading_result.get('flag_reason', ''),

        # Additional feedback
        'strengths': grading_result.get('strengths', ''),
        'areas_for_improvement': grading_result.get('areas_for_improvement', ''),

        # Detailed metric justifications
        'metric_justifications': grading_result.get('metric_justifications', {}),
    }

    # Dynamically map individual metric scores (up to 10 metrics supported)
    for i, metric in enumerate(metrics[:10], 1):  # Limit to 10 metrics
        response[f'rubric_metric{i}_score'] = metric_scores.get(metric, 0)
        response[f'rubric_metric{i}_name'] = metric  # Include metric name for reference
        logger.info(f"Mapped metric {i}: {metric} = {metric_scores.get(metric, 0)}")

    # Fill remaining metric slots with 0 if fewer than 10 metrics
    for i in range(len(metrics) + 1, 11):
        response[f'rubric_metric{i}_score'] = 0
        response[f'rubric_metric{i}_name'] = ''

    # Extract metadata with DynamoDB format handling
    rubric_used = rubric_data.get('essay_id', '')
    if isinstance(rubric_used, dict) and 'S' in rubric_used:
        rubric_used = rubric_used['S']

    rubric_version = rubric_data.get('rubric_version', '')
    if isinstance(rubric_version, dict) and 'S' in rubric_version:
        rubric_version = rubric_version['S']

    # Add metadata to response
    response.update({
        'grading_timestamp': datetime.utcnow().isoformat() + 'Z',
        'rubric_used': rubric_used,
        'rubric_version': rubric_version,
        'grader_model': 'amazon.nova-pro-v1:0'
    })

    logger.info(f"Prepared grading response for student {input_data['student_id']} with score {response['essay_score']}")
    logger.info(f"Rubric metrics used: {metrics}")

    return response