#!/usr/bin/env python3
"""
Batch process LinkedIn leads to generate personalized outreach messages
"""

import json
import os
from messager import LinkedInMessager
from datetime import datetime

class BatchMessager:
    def __init__(self):
        self.messager = LinkedInMessager()
        self.results = []
    
    def process_leads_from_json(self, leads_file="leads.json", profile_data_dir="profile_data"):
        """
        Process multiple leads and generate messages for each
        
        Args:
            leads_file (str): Path to JSON file containing LinkedIn URLs
            profile_data_dir (str): Directory containing scraped profile data files
        
        Returns:
            list: Results with generated messages for each lead
        """
        try:
            with open(leads_file, 'r') as f:
                leads = json.load(f)
        except FileNotFoundError:
            print(f"Error: {leads_file} not found")
            return []
        
        print(f"Processing {len(leads)} leads...")
        
        for i, lead_url in enumerate(leads, 1):
            print(f"\nProcessing lead {i}/{len(leads)}: {lead_url}")
            
            # Extract profile identifier from URL (you may need to adjust this)
            profile_id = self.extract_profile_id(lead_url)
            profile_data_file = os.path.join(profile_data_dir, f"{profile_id}.json")
            
            if not os.path.exists(profile_data_file):
                print(f"  Warning: Profile data file not found: {profile_data_file}")
                self.results.append({
                    "lead_url": lead_url,
                    "profile_id": profile_id,
                    "status": "error",
                    "message": f"Profile data file not found: {profile_data_file}"
                })
                continue
            
            # Generate outreach message
            try:
                message = self.messager.generate_outreach_message(profile_data_file)
                
                result = {
                    "lead_url": lead_url,
                    "profile_id": profile_id,
                    "status": "success",
                    "outreach_message": message,
                    "generated_at": datetime.now().isoformat()
                }
                
                self.results.append(result)
                print(f"  ✓ Generated message for {profile_id}")
                
            except Exception as e:
                error_result = {
                    "lead_url": lead_url,
                    "profile_id": profile_id,
                    "status": "error",
                    "message": str(e),
                    "generated_at": datetime.now().isoformat()
                }
                
                self.results.append(error_result)
                print(f"  ✗ Error generating message for {profile_id}: {e}")
        
        return self.results
    
    def extract_profile_id(self, linkedin_url):
        """
        Extract profile identifier from LinkedIn URL
        
        Args:
            linkedin_url (str): LinkedIn profile URL
            
        Returns:
            str: Profile identifier
        """
        # Extract the profile name from URL like: https://www.linkedin.com/in/yatharth-bisht-8a559b241/
        if "/in/" in linkedin_url:
            profile_id = linkedin_url.split("/in/")[1].rstrip("/")
            return profile_id
        else:
            # Fallback: use the last part of the URL
            return linkedin_url.split("/")[-1] or linkedin_url.split("/")[-2]
    
    def save_results(self, output_file="outreach_messages.json"):
        """Save generated messages to a JSON file"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        print(f"\nResults saved to {output_file}")
        
        # Print summary
        successful = len([r for r in self.results if r["status"] == "success"])
        failed = len([r for r in self.results if r["status"] == "error"])
        
        print(f"\nSummary:")
        print(f"  ✓ Successful: {successful}")
        print(f"  ✗ Failed: {failed}")
        print(f"  Total: {len(self.results)}")
    
    def generate_csv_report(self, output_file="outreach_report.csv"):
        """Generate a CSV report of the results"""
        import csv
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow(['Profile ID', 'LinkedIn URL', 'Status', 'Outreach Message', 'Generated At'])
            
            # Data rows
            for result in self.results:
                writer.writerow([
                    result.get('profile_id', ''),
                    result.get('lead_url', ''),
                    result.get('status', ''),
                    result.get('outreach_message', result.get('message', '')),
                    result.get('generated_at', '')
                ])
        
        print(f"CSV report saved to {output_file}")

def main():
    """Main function to run batch processing"""
    batch_messager = BatchMessager()
    
    # Process all leads
    results = batch_messager.process_leads_from_json()
    
    # Save results
    batch_messager.save_results()
    batch_messager.generate_csv_report()
    
    # Display sample results
    print("\nSample Generated Messages:")
    print("=" * 60)
    
    for result in results[:3]:  # Show first 3 results
        if result["status"] == "success":
            print(f"\nProfile: {result['profile_id']}")
            print(f"Message: {result['outreach_message'][:200]}...")
            print("-" * 40)

if __name__ == "__main__":
    main()