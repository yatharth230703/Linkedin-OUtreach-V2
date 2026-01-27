# LinkedIn Outreach Template System

## Overview
The LinkedIn outreach system now supports multiple prompt templates for different outreach strategies. This allows you to customize the AI-generated messages based on your specific needs or target audience.

## Template Files
- `prompt_template_1.json` - Default professional outreach template (active)
- `prompt_template_2.json` - Reserved for future use (empty)
- `prompt_template_3.json` - Reserved for future use (empty)
- `prompt_template_4.json` - Reserved for future use (empty)

## Template Structure
Each template file contains:
```json
{
  "outreach_prompt": "Prompt for connection request messages",
  "followup_prompt": "Prompt for follow-up messages",
  "description": "Description of the template's purpose"
}
```

## Usage

### Running the Connection Bot with Templates
```bash
# Use default template (template_1)
python msg_draft_connection_bot1.py

# Use specific template
python msg_draft_connection_bot1.py --template_1
python msg_draft_connection_bot1.py --template_2
python msg_draft_connection_bot1.py --template_3
python msg_draft_connection_bot1.py --template_4
```

### Running the Orchestrator with Templates
```bash
# Use default template (template_1)
python orchestrator.py

# Use specific template
python orchestrator.py --template_1
python orchestrator.py --template_2
python orchestrator.py --template_3
python orchestrator.py --template_4

# Combine with test mode
python orchestrator.py --test --template_2
```

## Fallback Behavior
- If a template file is missing or empty, the system automatically falls back to `template_1`
- If `template_1` is missing or invalid, the system will throw an error
- Empty templates (2, 3, 4) will show a warning and use template_1 instead

## Adding New Templates
To create a new template:

1. Edit one of the empty template files (template_2.json, template_3.json, or template_4.json)
2. Add your custom prompts for both outreach and followup messages
3. Include placeholders: `{profile_str}`, `{posts_str}`, `{context_str}`
4. Add a descriptive description

Example:
```json
{
  "outreach_prompt": "Your custom outreach prompt with {profile_str} and {posts_str}",
  "followup_prompt": "Your custom followup prompt with {profile_str}, {posts_str}, and {context_str}",
  "description": "Custom template for specific industry outreach"
}
```

## Current Template 1 (Default)
The default template focuses on:
- Professional but conversational tone
- Genuine connection building
- Value-driven messaging
- Specific profile/post references
- Soft call-to-actions
- Relationship-first approach