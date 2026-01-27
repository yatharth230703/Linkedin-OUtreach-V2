"""Gemini LinkedIn Outreach Message Generator"""
import os
import json
from pathlib import Path
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
    def __init__(self, template_name="template_1"):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_TEST"))
        self.model = "gemini-3-flash-preview"
        self.template_name = template_name
        self.template_data = self._load_template(template_name)
    
    def _load_template(self, template_name):
        """Load prompt template from JSON file"""
        script_dir = Path(__file__).parent
        template_file = script_dir / f"prompt_{template_name}.json"
        
        try:
            with open(template_file, 'r', encoding='utf-8') as f:
                template_data = json.load(f)
            
            # Validate template has required fields
            if not template_data.get('outreach_prompt') or not template_data.get('followup_prompt'):
                if template_name != "template_1":
                    print(f"⚠️ Template {template_name} is empty or invalid, falling back to template_1")
                    return self._load_template("template_1")
                else:
                    raise ValueError("Template 1 must have valid prompts")
            
            print(f"✅ Loaded template: {template_name} - {template_data.get('description', 'No description')}")
            return template_data
            
        except FileNotFoundError:
            if template_name != "template_1":
                print(f"⚠️ Template file not found: {template_file}, falling back to template_1")
                return self._load_template("template_1")
            else:
                raise FileNotFoundError(f"Default template file not found: {template_file}")
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in template file {template_file}: {e}")
            if template_name != "template_1":
                return self._load_template("template_1")
            else:
                raise
        except Exception as e:
            print(f"❌ Error loading template {template_name}: {e}")
            if template_name != "template_1":
                return self._load_template("template_1")
            else:
                raise
    
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
    
    def generate_outreach_message(self, profile_data: dict, posts_data: list[dict] = None, debug: bool = False) -> str:
        """
        Generate a personalized LinkedIn outreach message using the loaded template.
        
        Args:
            profile_data: Dict with full_name, headline, about, experience
            posts_data: Optional list of recent posts
            debug: If True, print debug information about posts data
        
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
            
            if debug:
                print(f"   🔍 DEBUG: Posts data received: {len(posts_data)} posts")
                print(f"   🔍 DEBUG: Posts string length: {len(posts_str)} chars")
        else:
            if debug:
                print(f"   🔍 DEBUG: No posts data provided")
        
        # Use template prompt and format with data
        prompt = self.template_data['outreach_prompt'].format(
            profile_str=profile_str,
            posts_str=posts_str
        )
        
        if debug:
            print(f"   🔍 DEBUG: Final prompt length: {len(prompt)} chars")
            print(f"   🔍 DEBUG: Posts section in prompt: {'Recent Posts:' in prompt}")

        return self._generate_content(prompt)
    
    def generate_followup_message(self, profile_data: dict, posts_data: list[dict] = None, context: str = "", debug: bool = False) -> str:
        """
        Generate a follow-up message after connection acceptance using the loaded template.
        
        Args:
            profile_data: Dict with full_name, headline, about, experience
            posts_data: Optional list of recent posts
            context: Additional context about previous interaction
            debug: If True, print debug information about posts data
        
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
            
            if debug:
                print(f"   🔍 DEBUG: Posts data received: {len(posts_data)} posts")
                print(f"   🔍 DEBUG: Posts string length: {len(posts_str)} chars")
        else:
            if debug:
                print(f"   🔍 DEBUG: No posts data provided")
        
        context_str = f"\nAdditional context: {context}" if context else ""
        
        # Use template prompt and format with data
        prompt = self.template_data['followup_prompt'].format(
            profile_str=profile_str,
            posts_str=posts_str,
            context_str=context_str
        )
        
        if debug:
            print(f"   🔍 DEBUG: Final prompt length: {len(prompt)} chars")
            print(f"   🔍 DEBUG: Posts section in prompt: {'Recent Posts:' in prompt}")

        return self._generate_content(prompt)
    
    def generate_messages(self, profile_data: dict, posts_data: list[dict] = None, debug: bool = False) -> OutreachMessages:
        """
        Generate both outreach and followup messages.
        
        Args:
            profile_data: Dict with full_name, headline, about, experience
            posts_data: Optional list of recent posts
            debug: If True, print debug information about posts data
        
        Returns:
            OutreachMessages dataclass with both messages
        """
        outreach = self.generate_outreach_message(profile_data, posts_data, debug=debug)
        followup = self.generate_followup_message(profile_data, posts_data, debug=debug)
        
        return OutreachMessages(
            outreach_message=outreach,
            followup_message=followup
        )
