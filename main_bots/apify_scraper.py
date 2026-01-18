"""Apify LinkedIn Posts Scraper Module"""
import os
import json
from datetime import datetime, timedelta
from apify_client import ApifyClient
from dotenv import load_dotenv

load_dotenv()

def is_within_one_month(posted_date: str) -> bool:
    """
    Check if a post date is within the last month.
    
    Args:
        posted_date: Date string in format 'YYYY-MM-DD'
    
    Returns:
        True if within last month, False otherwise
    """
    if not posted_date:
        return False
    
    try:
        post_date = datetime.strptime(posted_date, '%Y-%m-%d')
        one_month_ago = datetime.now() - timedelta(days=30)
        return post_date >= one_month_ago
    except (ValueError, TypeError):
        return False

def scrape_linkedin_posts(linkedin_url: str, limit: int = 100) -> list[dict]:
    """
    Scrape LinkedIn posts for a given profile URL using Apify.
    
    Args:
        linkedin_url: LinkedIn profile URL
        limit: Max number of posts to fetch
    
    Returns:
        List of filtered post dictionaries
    """
    api_key = os.getenv("APIFY_API")
    if not api_key:
        raise ValueError("APIFY_API not found in environment")
    
    client = ApifyClient(api_key)
    
    run_input = {
        "username": linkedin_url,
        "page_number": 1,
        "pagination_token": None,
        "limit": limit,
        "total_posts": limit,
    }
    
    run = client.actor("LQQIXN9Othf8f7R5n").call(run_input=run_input)
    
    filtered_results = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        # Filter for regular posts only
        post_type = item.get("post_type")
        if post_type != "regular":
            continue
        
        # Filter for posts within the last month
        posted_date = item.get("posted_at", {}).get("date")
        if not is_within_one_month(posted_date):
            continue
        
        filtered_item = {
            "posted_at": {
                "date": item.get("posted_at", {}).get("date"),
                "relative": item.get("posted_at", {}).get("relative")
            },
            "text": item.get("text"),
            "post_type": item.get("post_type"),
            "author": {
                "first_name": item.get("author", {}).get("first_name"),
                "last_name": item.get("author", {}).get("last_name"),
                "headline": item.get("author", {}).get("headline")
            }
        }
        filtered_results.append(filtered_item)
    
    return filtered_results
