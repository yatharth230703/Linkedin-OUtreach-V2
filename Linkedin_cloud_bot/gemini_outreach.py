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
    followup_message_1: str
    followup_message_2: str
    followup_message_3: str
    followup_message_4: str


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
            required_fields = ['outreach_prompt', 'followup_1_prompt', 'followup_2_prompt', 'followup_3_prompt', 'followup_4_prompt']
            missing_fields = [field for field in required_fields if not template_data.get(field)]
            
            if missing_fields:
                if template_name != "template_1":
                    print(f"⚠️ Template {template_name} is missing fields: {missing_fields}, falling back to template_1")
                    return self._load_template("template_1")
                else:
                    raise ValueError(f"Template 1 must have all required prompts. Missing: {missing_fields}")
            
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
    
    def generate_followup_message(self, profile_data: dict, posts_data: list[dict] = None, context: str = "", followup_number: int = 1, debug: bool = False) -> str:
        """
        Generate a follow-up message after connection acceptance using the loaded template.
        
        Args:
            profile_data: Dict with full_name, headline, about, experience
            posts_data: Optional list of recent posts
            context: Additional context about previous interaction
            followup_number: Which follow-up this is (1-4)
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
        
        # Select the appropriate prompt based on follow-up number
        prompt_key = f'followup_{followup_number}_prompt'
        
        if prompt_key not in self.template_data:
            print(f"⚠️ Warning: {prompt_key} not found in template, using followup_1_prompt as fallback")
            prompt_key = 'followup_1_prompt'
        
        # Use template prompt and format with data
        prompt = self.template_data[prompt_key].format(
            profile_str=profile_str,
            posts_str=posts_str,
            context_str=context_str
        )
        
        if debug:
            print(f"   🔍 DEBUG: Using prompt: {prompt_key}")
            print(f"   🔍 DEBUG: Final prompt length: {len(prompt)} chars")
            print(f"   🔍 DEBUG: Posts section in prompt: {'Recent Posts:' in prompt}")
            print(f"   🔍 DEBUG: Follow-up number: {followup_number}")

        return self._generate_content(prompt)
    
    def generate_messages(self, profile_data: dict, posts_data: list[dict] = None, debug: bool = False) -> OutreachMessages:
        """
        Generate outreach and 4 follow-up messages.
        
        Args:
            profile_data: Dict with full_name, headline, about, experience
            posts_data: Optional list of recent posts
            debug: If True, print debug information about posts data
        
        Returns:
            OutreachMessages dataclass with outreach and 4 follow-up messages
        """
        print("   🤖 Generating initial outreach message...")
        outreach = self.generate_outreach_message(profile_data, posts_data, debug=debug)
        
        print("   🤖 Generating follow-up message 1...")
        followup_1 = self.generate_followup_message(profile_data, posts_data, followup_number=1, debug=debug)
        
        print("   🤖 Generating follow-up message 2...")
        followup_2 = self.generate_followup_message(profile_data, posts_data, followup_number=2, debug=debug)
        
        print("   🤖 Generating follow-up message 3...")
        followup_3 = self.generate_followup_message(profile_data, posts_data, followup_number=3, debug=debug)
        
        print("   🤖 Generating follow-up message 4...")
        followup_4 = self.generate_followup_message(profile_data, posts_data, followup_number=4, debug=debug)
        
        return OutreachMessages(
            outreach_message=outreach,
            followup_message_1=followup_1,
            followup_message_2=followup_2,
            followup_message_3=followup_3,
            followup_message_4=followup_4
        )
