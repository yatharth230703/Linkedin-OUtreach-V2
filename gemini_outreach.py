import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv
load_dotenv()
class GeminiLinkedInMessager:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = "gemini-3-flash-preview"
    
    def generate_outreach_message(self, profile_data_file):
        """
        Generate a personalized LinkedIn outreach message based on scraped profile data
        
        Args:
            profile_data_file (str): Path to JSON file containing scraped LinkedIn profile data
        
        Returns:
            str: Generated outreach message
        """
        # Read the profile data
        try:
            with open(profile_data_file, 'r', encoding='utf-8') as f:
                profile_data = f.read()
        except FileNotFoundError:
            return f"Error: Profile data file '{profile_data_file}' not found."
        except Exception as e:
            return f"Error reading profile data: {str(e)}"
        
        # Create the prompt for outreach message generation
        prompt = f"""You are an expert LinkedIn outreach specialist who writes highly personalized, human-like connection requests and messages. Your goal is to create authentic, engaging messages that feel personal and relevant.

GUIDELINES:
1. Keep messages concise (50-150 words for connection requests, 100-200 words for follow-up messages)
2. Reference specific details from their profile (current role, company, recent posts, shared connections, education, etc.)
3. Find genuine common ground or shared interests
4. Be professional but conversational and warm
5. Include a clear but soft call-to-action
6. Avoid generic templates or obvious sales language
7. Make it feel like a message from one professional to another
8. Use their name naturally in the message
9. Show genuine interest in their work or achievements

TONE:
- Friendly and approachable
- Professional but not overly formal
- Authentic and genuine
- Respectful of their time
- Confident but not pushy

Based on the following LinkedIn profile data, write a personalized outreach message:

{profile_data}

Create a connection request message that feels authentic and personal. Reference specific details from their profile to show you've actually looked at their background.

OUTPUT FORMAT:
Provide only the message text, no additional formatting or explanations."""

        try:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                ),
            ]
            
            tools = [
                types.Tool(url_context=types.UrlContext()),
                types.Tool(googleSearch=types.GoogleSearch()),
            ]
            
            generate_content_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
                tools=tools,
            )
            
            response_text = ""
            for chunk in self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            ):
                response_text += chunk.text
            
            return response_text.strip()
            
        except Exception as e:
            return f"Error generating message: {str(e)}"
    
    def generate_follow_up_message(self, profile_data_file, context=""):
        """
        Generate a follow-up message after initial connection
        
        Args:
            profile_data_file (str): Path to JSON file containing scraped LinkedIn profile data
            context (str): Additional context about previous interaction
        
        Returns:
            str: Generated follow-up message
        """
        try:
            with open(profile_data_file, 'r', encoding='utf-8') as f:
                profile_data = f.read()
        except FileNotFoundError:
            return f"Error: Profile data file '{profile_data_file}' not found."
        except Exception as e:
            return f"Error reading profile data: {str(e)}"
        
        prompt = f"""You are an expert LinkedIn outreach specialist writing follow-up messages after someone has accepted your connection request. Create engaging, value-driven messages that continue the conversation naturally.

GUIDELINES:
1. Thank them for connecting
2. Reference something specific from their profile or recent activity
3. Offer value (insight, resource, introduction, collaboration opportunity)
4. Keep it conversational and genuine
5. Include a soft call-to-action for further engagement
6. Avoid immediate sales pitches
7. Focus on building a relationship first
8. Be specific about how you might help or collaborate

TONE:
- Grateful and appreciative
- Professional but warm
- Value-focused
- Collaborative
- Genuine interest in their success

Based on the following LinkedIn profile data, write a follow-up message after they accepted your connection request:

{profile_data}

{f"Additional context: {context}" if context else ""}

Create a follow-up message that offers value and continues building the relationship.

OUTPUT FORMAT:
Provide only the message text, no additional formatting or explanations."""

        try:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                ),
            ]
            
            tools = [
                types.Tool(url_context=types.UrlContext()),
                types.Tool(googleSearch=types.GoogleSearch()),
            ]
            
            generate_content_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
                tools=tools,
            )
            
            response_text = ""
            for chunk in self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            ):
                response_text += chunk.text
            
            return response_text.strip()
            
        except Exception as e:
            return f"Error generating follow-up message: {str(e)}"

def main():
    """Example usage of the GeminiLinkedInMessager"""
    messager = GeminiLinkedInMessager()
    
    # Example: Generate outreach message for a profile
    profile_file = "leon_brunner_clean.json"  # Replace with actual profile data file
    
    print("Generating LinkedIn outreach message...")
    message = messager.generate_outreach_message(profile_file)
    print(f"\nGenerated Message:\n{message}")
    
    # Example: Generate follow-up message
    print("\n" + "="*50)
    print("Generating follow-up message...")
    follow_up = messager.generate_follow_up_message(profile_file, "They mentioned interest in AI/ML")
    print(f"\nGenerated Follow-up:\n{follow_up}")

if __name__ == "__main__":
    main()