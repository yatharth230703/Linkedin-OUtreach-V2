# LinkedIn Outreach Automation V2 - Engineering Briefing

## Project Summary

Rebuild the LinkedIn outreach automation system with **Attio CRM** as the central data store (replacing Supabase), supporting **two LinkedIn accounts** (Maurice & Leon), with **independently runnable bots** and easy template management. 

---

## System Architecture

```
+-------------------------------------------+
|   Import leads data ( Linkedin URL from )  |
|    Bots input record in Attio CRM 
+--------+-----+---------------+------------+
    |                   |                   |
    v                   v                   v
+---+-------+   +-------+-------+   +------+--------+
| Connection|   |  Message Bot  |   | Follow-up Bot |
|    Bot    |   |               |   |               |
+---+-------+   +-------+-------+   +------+--------+
    |                   |                   |
    +-------------------+-------------------+
                        |
                +------------------------------+
                | Leads sources                |
                |  record ,stores              |
                | a history of all
                | bot runs and leads status     |
                +------------------------------+
```

**External Services:**
- **Attio** - CRM, replaces Supabase entirely (via API)
- **Gemini** - AI message generation
- **Apify** - LinkedIn post scraping

---

## Data Model (Attio)

## defined in bots_input record and leads_sources record in Attio CRM 


### Status flow 
User clicks on extension run bot button --> cron job starts running bot orchestrator on a per day basis --> the limitations (max per day) metadata remains same as defined at start of run bot --> first msg_draft_connection bot runs --> second the send message bot runs -->third the send followup bot runs --> This keeps happening everyday until the user manually stops the bot or an error is encountered that is not solveable or for that particular user (lead_manager), there are no more leads in the bots input record. 



### Shared Workspace : 
Whichever user runs the extension and the bot, the name is already being captured right now .The name captured will be of the lead_manager as defined in the bots input reconrd and leads_sources records. It will take all the prompt templates and linkedin URLs defined within this record ONLY FOR THAT PARTICULAR USER (Lead manager) who ran the bot , and running 3 campaigns side by side shouldn't be an issue ,figure this out with deployment setup. All can run together but remain isolated . 

## Bots

All three bots are **independently startable**. They can run standalone or as a sequence via the orchestrator/cron. This is already implemented , on cloud we're only concerned with the orchestrator 

The bots will be run on the cloud using xvfb and proxies enabled 
---

## Execution Model

All three bots run **automatically every day** until stopped or reconfigured. Technical implementation details (cron, scheduling, orchestration) are up to the you.
---

## Template Management

### Template Structure
Each template must define prompts for:
- 1 outreach message
- 4 follow-up messages
- A description

A good example can be prompt_template_1.json. In the beginning 4 such templates will be uploaded in the cloud for the VM based bots to access ,but within the extension itself there should be a facillity to upload a jsonfile (that strictly complies with the format described in sample ) and the bot should be able to access it and run the campaign based on that 
Keep in mind that bots_input recieves the prompt template in attio. We can add new name of template to the column easily (prompt template column in attio in bot inputs column ) . After uploading the extension should simply change name of uploaded json to something like "template_6" complying with ordering of templates ,and at the same time letting user know what the bots expect as inputs from the bot inputs table . 

### Testing New Templates

As soon as a new template is uploaded via the extension , the user should be able to see a sample generated message , that is generated using data of any random lead from leads_sources column (the way it is generated in gemini_outreach.py) and all 5 messages (outreach + 4 followup) should be shown to the user so they can see how the message is , and re-upload changed json if they're unsatisfied. Only after they're satisfied they hit save and then go on about uploading the new prompt template 

## LinkedIn Account Management

### Three Accounts
| Account   | Chrome Profile Dir     | |
|-----------|------------------------|-------------------------|
| Maurice   | `user_data_maurice/`   | 
| Leon      | `user_data_leon/`      |    
| Yatharth  | `user_data_yatharth/`  |    

The above is the way user data must be stored for the bots in storage . 

### Rules
- Each lead is assigned to ONE account (stored in Attio)
- That account handles the entire lifecycle: connect --> message --> all follow-ups
- All accounts share the same Attio workspace

---

## Operational Control

### Configuration Model
Each LinkedIn account has its own **persistent configuration**:
- Assigned Leads
- Assigned prompt template
- Bot sequence to run

Configuration is **set once and runs daily** until changed. No daily input needed from the user. When the user wants to switch to a new campaign or test a new template, they update the config and it takes effect on the next run.

The interface for changing config (config file, CLI, Attio metadata, etc.) is up to the engineer.

### Template & Campaign Cadence
- Templates change roughly **weekly** or **per campaign**
- When a new lead list is imported into Attio, it typically gets a new or existing template assigned. It is stored in bots_input record in attio.
- Each account can run a **different template and list** independently. Relationship is seen in bots_input 


### Notifications (Low Priority - implement if easy)
- **List exhausted:** Notify the user when a list has no more NEW leads to process
- **Daily summary:** After each bot run, send a summary report to the user (connections sent, messages sent, follow-ups, replies detected, errors, remaining leads)

Use resend API to send emails to the user

---
### VERY IMPORTANT : For lead_manager : yatharth : proxy password to be used is : aFCTd3w0bSimAaEp_country-in_city-delhi and for maurice and leon , proxy password to be used is aFCTd3w0bSimAaEp_country-de_city-hamburg
