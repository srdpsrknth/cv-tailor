#!/usr/bin/env python3
"""Test script for tailor endpoint with detailed error handling."""

import json
import sys
import logging
import requests
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test job description (trivago data analyst role)
TEST_JOB_DESCRIPTION = """
Data Analyst, Marketing Strategy & Intelligence

About the role:
We are looking for a Data Analyst to join our Marketing Strategy & Intelligence team. 
You will analyze complex datasets to drive marketing strategy and provide actionable insights.

Key Responsibilities:
- Analyze customer behavior and marketing campaign performance
- Create dashboards and visualizations in Tableau or Looker
- Work with SQL to extract and prepare data
- Provide statistical analysis and forecasting
- Collaborate with marketing, product, and engineering teams
- Track and report on key performance indicators (KPIs)

Required Skills:
- Advanced SQL and Python/R
- Data visualization (Tableau, Looker, or similar)
- Statistical analysis and A/B testing
- Experience with data warehouses (BigQuery, Snowflake, Redshift)
- Strong communication and presentation skills
- Google Analytics and marketing analytics experience

Preferred:
- Experience with dbt or data modeling
- Machine learning basics
- ETL tools knowledge
"""

def test_tailor_endpoint():
    """Test the /api/tailor endpoint."""
    url = "http://localhost:8000/api/tailor"
    
    payload = {
        "job_description": TEST_JOB_DESCRIPTION,
        "company_name": "Trivago",
        "role_title": "Data Analyst, Marketing Strategy & Intelligence"
    }
    
    logger.info(f"Testing endpoint: POST {url}")
    logger.info(f"Payload: {json.dumps({k: len(v) if isinstance(v, str) else v for k, v in payload.items()}, indent=2)}")
    
    try:
        response = requests.post(
            url,
            json=payload,
            timeout=120  # 2 minutes timeout
        )
        
        logger.info(f"Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ SUCCESS!")
            logger.info(f"Job ID: {data.get('job_id')}")
            logger.info(f"CV Path: {data.get('cv_path')}")
            logger.info(f"Cover Letter Path: {data.get('cover_letter_path')}")
            
            token_usage = data.get('token_usage', {})
            logger.info(f"Token Usage: {json.dumps(token_usage, indent=2)}")
            
            return True
        else:
            logger.error(f"❌ FAILED with status {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error("❌ Request timed out after 120 seconds")
        return False
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ Connection error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting test of tailor endpoint...")
    success = test_tailor_endpoint()
    sys.exit(0 if success else 1)
