from apify_client import ApifyClient
from dotenv import load_dotenv
import os
import json
from datetime import datetime

load_dotenv()
api = os.getenv("APIFY_API")
# Initialize the ApifyClient with your API token
client = ApifyClient(api)

# Prepare the Actor input
run_input = {
    "username": "https://www.linkedin.com/in/janmis/",
    "page_number": 1,
    "pagination_token": None,
    "limit": 100,
    "total_posts": 100,
}

# Run the Actor and wait for it to finish
run = client.actor("LQQIXN9Othf8f7R5n").call(run_input=run_input)

# Fetch Actor results from the run's dataset and filter required fields
filtered_results = []
for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    # Extract only the required fields
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

# Generate filename with timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"apify_filtered_output_{timestamp}.json"

# Save filtered results to JSON file
with open(filename, 'w', encoding='utf-8') as f:
    json.dump(filtered_results, f, indent=2, ensure_ascii=False)

print(f"Filtered results saved to {filename}")
print(f"Total items collected: {len(filtered_results)}")