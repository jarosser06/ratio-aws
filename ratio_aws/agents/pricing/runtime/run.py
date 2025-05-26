"""
AWS Pricing Agent

This agent queries the AWS Price List API to retrieve pricing information for various AWS services.
"""
import boto3
import json
import logging
import os
import uuid

from typing import Dict

from da_vinci.core.logging import Logger

from da_vinci.core.immutable_object import ObjectBody

from da_vinci.event_bus.client import fn_event_response

from da_vinci.exception_trap.client import ExceptionReporter

from ratio.agents.agent_lib import RatioSystem


# Region mapping: AWS API region codes to Pricing API display names
REGION_MAPPING = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)", 
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "Europe (Ireland)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-central-1": "Europe (Frankfurt)",
    "eu-north-1": "Europe (Stockholm)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (Sao Paulo)",
}


class PricingError(Exception):
    """Exception raised for errors during pricing queries"""
    pass


def _snake_to_camel(snake_str: str) -> str:
    """
    Convert snake_case to camelCase
    
    Keyword arguments:
    snake_str -- The snake_case string to convert

    Returns:
        The converted camelCase string
    """
    if "_" not in snake_str:
        return snake_str  # Already camelCase or single word

    components = snake_str.split("_")

    return components[0] + "".join(word.capitalize() for word in components[1:])


def normalize_filters_for_service(filters: Dict) -> Dict:
    """
    Convert snake_case filter names to camelCase AWS API field names

    Keyword arguments:
    service_code -- The AWS service being queried (not used but kept for compatibility)
    filters -- User-provided filters (may use snake_case names)

    Returns:
        Dictionary with normalized camelCase API field names
    """
    if not filters:
        return {}

    normalized = {}

    for key, value in filters.items():
        api_key = _snake_to_camel(key)

        normalized[api_key] = value

    return normalized


_FN_NAME = "ratio.agents.aws_pricing"


@fn_event_response(exception_reporter=ExceptionReporter(), function_name=_FN_NAME, logger=Logger(_FN_NAME))
def handler(event: Dict, context: Dict):
    """
    Execute the AWS Pricing agent
    """
    logging.debug(f"Received request: {event}")

    # Initialize the Ratio system from the event
    system = RatioSystem.from_da_vinci_event(event)

    system.raise_on_failure = True

    logging.debug(f"Initialized Ratio system")

    with system:
        logging.debug("Loading variables from system arguments")

        service_code = system.arguments["service_code"]

        regions = system.arguments.get("regions", default_return=["us-east-1"])

        user_filters = system.arguments.get("filters", default_return={})

        max_records = system.arguments.get("max_records", default_return=50)

        result_file_path = system.arguments.get("result_file_path")

        logging.debug(f"Initializing AWS Pricing client in US East 1")

        pricing_client = boto3.client("pricing", region_name="us-east-1")

        if isinstance(user_filters, ObjectBody):
            # Convert ObjectBody to a regular dictionary
            user_filters = user_filters.to_dict()

        logging.debug(f"Normalizing filters {user_filters}")

        # Normalize filters based on service (convert friendly names to API field names)
        final_filters = normalize_filters_for_service(user_filters)

        logging.debug(f"Normalized filters for service {service_code}: {final_filters}")

        # Convert regions to display names for API
        region_display_names = []

        for region in regions:
            if region in REGION_MAPPING:
                region_display_names.append(REGION_MAPPING[region])

            else:
                raise PricingError(f"Unknown region: {region}")

        # Add region filter
        if len(region_display_names) == 1:
            final_filters["location"] = region_display_names[0]

        logging.debug(f"Querying pricing for service {service_code} with normalized filters: {final_filters}")

        all_pricing_records = []

        # Handle multi-region queries by making separate API calls
        regions_to_query = region_display_names if len(region_display_names) > 1 else [region_display_names[0]]

        for region_name in regions_to_query:
            query_filters = final_filters.copy()

            query_filters["location"] = region_name

            # Build API filters list
            api_filters = []

            for key, value in query_filters.items():
                api_filters.append({
                    "Type": "TERM_MATCH",
                    "Field": key,
                    "Value": value
                })

            # Query pricing API with pagination
            paginator = pricing_client.get_paginator("get_products")

            page_iterator = paginator.paginate(
                ServiceCode=service_code,
                Filters=api_filters,
                MaxResults=max_records
            )

            region_records = []

            for page in page_iterator:
                for price_list_str in page["PriceList"]:
                    try:
                        price_data = json.loads(price_list_str)

                        # Add region info for clarity
                        price_data["queryRegion"] = region_name

                        region_records.append(price_data)

                    except json.JSONDecodeError as e:

                        logging.warning(f"Failed to parse pricing data: {e}")

                        continue

            all_pricing_records.extend(region_records)

            logging.debug(f"Found {len(region_records)} pricing records for {region_name}")

        # Create result file path if not provided
        if not result_file_path:
            result_file_path = os.path.join(
                system.working_directory, 
                f"aws_pricing_{service_code}_{uuid.uuid4()}.json"
            )

        # Prepare detailed results for file
        detailed_results = {
            "service_code": service_code,
            "regions_queried": regions,
            "filters_applied": final_filters,
            "record_count": len(all_pricing_records),
            "pricing_records": all_pricing_records,
        }

        # Save detailed results to file
        system.put_file(
            file_path=result_file_path,
            file_type="ratio::file",
            data=json.dumps(detailed_results, indent=2),
            metadata={
                "service_code": service_code,
                "regions": regions,
                "record_count": len(all_pricing_records)
            }
        )

        # Prepare summary records for response (first 10 for immediate viewing)
        summary_records = all_pricing_records[:10] if len(all_pricing_records) > 10 else all_pricing_records

        # Return success with summary
        system.success(
            response_body={
                "pricing_records": summary_records,
                "result_file_path": result_file_path,
                "service_code": service_code,
                "regions_queried": regions,
                "record_count": len(all_pricing_records),
                "filters_applied": final_filters
            }
        )