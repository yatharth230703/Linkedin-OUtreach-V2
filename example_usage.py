#!/usr/bin/env python3
"""
Example usage of the Perplexity InfoGen tool for LinkedIn profile research.
"""

from perplexity_infogen import PerplexityInfoGen
import os

def example_single_profile():
    """Example: Research a single LinkedIn profile."""
    # Initialize the tool (make sure PERPLEXITY_API_KEY is set in your .env file)
    infogen = PerplexityInfoGen()
    
    # Research a single profile
    linkedin_url = "https://www.linkedin.com/in/example-profile/"
    result = infogen.extract_profile_info(linkedin_url)
    
    print("Single Profile Research Result:")
    print(f"URL: {result['linkedin_url']}")
    if 'error' in result:
        print(f"Error: {result['error']}")
    else:
        print(f"Research completed at: {result['research_timestamp']}")
        print("Research content preview:")
        print(result['research_content'][:500] + "..." if len(result['research_content']) > 500 else result['research_content'])

def example_multiple_profiles():
    """Example: Research multiple LinkedIn profiles."""
    infogen = PerplexityInfoGen()
    
    # List of LinkedIn URLs to research
    linkedin_urls = [
        "https://www.linkedin.com/in/example-profile-1/",
        "https://www.linkedin.com/in/example-profile-2/",
        "https://www.linkedin.com/in/example-profile-3/"
    ]
    
    # Process all profiles and save to JSON
    results = infogen.process_multiple_profiles(
        linkedin_urls=linkedin_urls,
        output_file="example_research_results.json",
        delay=2.0  # 2 second delay between requests
    )
    
    print(f"Processed {len(results['profiles'])} profiles")

def example_from_existing_leads_file():
    """Example: Research profiles from existing leads.json file."""
    infogen = PerplexityInfoGen()
    
    # Load URLs from your existing leads file
    urls = infogen.load_urls_from_file("leads.json")
    
    if urls:
        print(f"Found {len(urls)} LinkedIn URLs in leads.json")
        
        # Process all profiles
        results = infogen.process_multiple_profiles(
            linkedin_urls=urls,
            output_file="leads_research_results.json",
            delay=3.0  # 3 second delay to be respectful to API limits
        )
        
        print(f"Research completed for {len(results['profiles'])} profiles")
    else:
        print("No LinkedIn URLs found in leads.json")

if __name__ == "__main__":
    print("Perplexity InfoGen Examples")
    print("=" * 40)
    
    # Make sure API key is available
    if not os.getenv('PERPLEXITY_API_KEY'):
        print("Error: Please set PERPLEXITY_API_KEY in your .env file")
        exit(1)
    
    print("\n1. Single Profile Example:")
    try:
        example_single_profile()
    except Exception as e:
        print(f"Error in single profile example: {e}")
    
    print("\n2. Multiple Profiles Example:")
    try:
        example_multiple_profiles()
    except Exception as e:
        print(f"Error in multiple profiles example: {e}")
    
    print("\n3. From Existing Leads File Example:")
    try:
        example_from_existing_leads_file()
    except Exception as e:
        print(f"Error in leads file example: {e}")