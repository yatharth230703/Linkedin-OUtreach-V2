"""Gemini LinkedIn Outreach Message Generator"""
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv
from dataclasses import dataclass

load_dotenv()


@dataclass
class OutreachMessages:
    """Container for generated outreach messages"""
    outreach_message: str
    followup_message: str


class GeminiLinkedInMessager:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = "gemini-3-flash-preview"
    
    def _generate_content(self, prompt: str) -> str:
        """Internal method to generate content using Gemini"""
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        
        response_text = ""
        for chunk in self.client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                response_text += chunk.text
        
        return response_text.strip()
    
    def generate_outreach_message(self, profile_data: dict, posts_data: list[dict] = None) -> str:
        """
        Generate a personalized LinkedIn outreach message.
        
        Args:
            profile_data: Dict with full_name, headline, about, experience
            posts_data: Optional list of recent posts
        
        Returns:
            Generated outreach message string
        """
        profile_str = f"""
Full Name: {profile_data.get('full_name', 'Unknown')}
Headline: {profile_data.get('headline', '')}
About: {profile_data.get('about', '')}
Experience: {profile_data.get('experience', '')}
"""
        
        posts_str = ""
        if posts_data:
            posts_str = "\n\nRecent Posts:\n"
            for i, post in enumerate(posts_data[:5], 1):
                posts_str += f"\n--- Post {i} ---\n"
                posts_str += f"Date: {post.get('posted_at', {}).get('date', 'Unknown')}\n"
                posts_str += f"Content: {post.get('text', '')[:500]}...\n"
        
        prompt = f"""You are an expert LinkedIn outreach specialist. Write a highly personalized connection request.

GUIDELINES:
1. Keep messages concise (50-150 words)
2. Reference specific details from their profile or recent posts
3. Find genuine common ground
4. Be professional but conversational
5. Include a soft call-to-action
6. Avoid generic templates or sales language
7. Use their first name naturally

PROFILE DATA:
{profile_str}
{posts_str}

Create a connection request message that feels authentic. Reference specific details from their profile/posts.

OUTPUT: Provide only the message text, no formatting or explanations."""

        return self._generate_content(prompt)
    
    def generate_followup_message(self, profile_data: dict, posts_data: list[dict] = None, context: str = "") -> str:
        """
        Generate a follow-up message after connection acceptance.
        
        Args:
            profile_data: Dict with full_name, headline, about, experience
            posts_data: Optional list of recent posts
            context: Additional context about previous interaction
        
        Returns:
            Generated follow-up message string
        """
        profile_str = f"""
Full Name: {profile_data.get('full_name', 'Unknown')}
Headline: {profile_data.get('headline', '')}
About: {profile_data.get('about', '')}
Experience: {profile_data.get('experience', '')}
"""
        
        posts_str = ""
        if posts_data:
            posts_str = "\n\nRecent Posts:\n"
            for i, post in enumerate(posts_data[:5], 1):
                posts_str += f"\n--- Post {i} ---\n"
                posts_str += f"Date: {post.get('posted_at', {}).get('date', 'Unknown')}\n"
                posts_str += f"Content: {post.get('text', '')[:500]}...\n"
        
        prompt = f"""You are an expert LinkedIn outreach specialist writing follow-up messages.

GUIDELINES:
1. Thank them for connecting
2. Reference something specific from their profile or recent activity
3. Offer value (insight, resource, collaboration opportunity)
4. Keep it conversational and genuine (100-200 words)
5. Include a soft call-to-action
6. Avoid immediate sales pitches
7. Focus on building relationship first

PROFILE DATA:
{profile_str}
{posts_str}
{f"Additional context: {context}" if context else ""}

Create a follow-up message that offers value and continues building the relationship.

OUTPUT: Provide only the message text, no formatting or explanations."""

        return self._generate_content(prompt)
    
    def generate_messages(self, profile_data: dict, posts_data: list[dict] = None) -> OutreachMessages:
        """
        Generate both outreach and followup messages.
        
        Args:
            profile_data: Dict with full_name, headline, about, experience
            posts_data: Optional list of recent posts
        
        Returns:
            OutreachMessages dataclass with both messages
        """
        outreach = self.generate_outreach_message(profile_data, posts_data)
        followup = self.generate_followup_message(profile_data, posts_data)
        
        return OutreachMessages(
            outreach_message=outreach,
            followup_message=followup
        )
