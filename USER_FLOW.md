# LinkedIn Outreach Automation V2 - Engineering Briefing

## Project Summary

Rebuild the LinkedIn outreach automation system with **Attio CRM** as the central data store (replacing Supabase), supporting **two LinkedIn accounts** (Maurice & Leon), with **independently runnable bots** and easy template management. 

---

## System Architecture

```
+------------------+     +-------------------+
|   CSV Import     |     |  Prompt Templates  |
|  (Lead URLs)     |     |  (JSON files)      |
+--------+---------+     +---------+---------+
         |                          |
         v                          v
+--------+----------------------------+--------+
|                  Attio CRM                    |
|                                               |
|  Lists (campaigns/segments)                   |
|  Contact Records (profile data, messages,     |
|    statuses, assigned LinkedIn account)        |
+---+-------------------+-------------------+--+
    |                   |                   |
    v                   v                   v
+---+-------+   +-------+-------+   +------+--------+
| Connection|   |  Message Bot  |   | Follow-up Bot |
|    Bot    |   |               |   |               |
+---+-------+   +-------+-------+   +------+--------+
    |                   |                   |
    +-------------------+-------------------+
                        |
            +-----------+-----------+
            |                       |
    +-------v-------+       +-------v-------+
    | Maurice's      |       | Leon's        |
    | LinkedIn Acct  |       | LinkedIn Acct |
    | (Chrome session)|      | (Chrome session)|
    +----------------+       +----------------+
```

**External Services:**
- **Attio** - CRM, replaces Supabase entirely (via API)
- **Gemini** - AI message generation
- **Apify** - LinkedIn post scraping
- **OpenClaw** (VM) - Nice-to-have: remote trigger from phone (low priority)

---

## Data Model (Attio)

### Lead Lists
Leads are organized into lists in Attio. The structure of lists (campaign-based vs segment-based) is left to the engineer's discretion based on Attio's capabilities.

### Lead Source
Leads enter the system via **CSV import** into Attio lists. Each row contains at minimum a LinkedIn URL.

### Contact Record Fields

| Field                    | Type       | Description                                        |
|--------------------------|------------|----------------------------------------------------|
| `linkedin_url`           | URL        | LinkedIn profile URL (primary identifier)          |
| `full_name`              | Text       | Scraped from LinkedIn profile                      |
| `headline`               | Text       | Scraped from LinkedIn profile                      |
| `about`                  | Text       | Scraped from LinkedIn about section                |
| `experience`             | Text       | Scraped from LinkedIn experience section           |
| `profile_posts`          | Text/JSON  | Recent posts fetched via Apify                     |
| `message_1` (Outreach)   | Text       | AI-generated outreach message                      |
| `message_2` (Follow-up 1)| Text      | AI-generated follow-up 1                           |
| `message_3` (Follow-up 2)| Text      | AI-generated follow-up 2                           |
| `message_4` (Follow-up 3)| Text      | AI-generated follow-up 3                           |
| `message_5` (Follow-up 4)| Text      | AI-generated follow-up 4                           |
| `status`                 | Select     | Pipeline status (see Status Flow below)            |
| `connection_status`      | Select     | LinkedIn connection state                          |
| `last_contacted`         | DateTime   | Timestamp of last message sent                     |
| `last_scraped`           | DateTime   | Timestamp of last profile scrape                   |
| `linkedin_account`       | Select     | Which account handles this lead (Maurice / Leon)   |
| `template_used`          | Text       | Which prompt template was used for message gen     |

### Status Flow

```
NEW ──> SCRAPED ──> PENDING ──> first message sent ──> follow-up 1 sent
                                                           |
                                                    follow-up 2 sent
                                                           |
                                                    follow-up 3 sent
                                                           |
                                                    follow-up 4 sent
                                                           |
                                                    SEQUENCE COMPLETE

At any point: ──> LEAD REPLIED   (detected reply, end state)
              ──> FAULTY_URL     (404 / inaccessible profile)
```

### Shared Workspace
Maurice and Leon share the same Attio workspace. Both can see all leads. Leads are filtered by the `linkedin_account` field so each bot instance only processes its own assigned leads.

---

## Bots

All three bots are **independently startable**. They can run standalone or as a sequence via the orchestrator/cron.

---

## Execution Model

All three bots run **automatically every day** until stopped or reconfigured. Technical implementation details (cron, scheduling, orchestration) are up to the engineer.

### OpenClaw (Low Priority / Nice-to-Have)
Remote trigger from phone with full parameter selection (account, list, template, bot type). Implementation deferred.

---

## Template Management

### Template Structure
Each template must define prompts for:
- 1 outreach message
- 4 follow-up messages
- A description

How templates are stored and ingested (JSON files, Attio, database, etc.) is up to the engineer. The key requirement is that adding or changing a template should be easy and not require code changes.

### Testing New Templates
When a new template is created or an existing one is modified, the generated messages need to be tested before running at scale. The engineer should design a workflow that allows verifying message quality against real profile data without polluting the live pipeline.

---

## LinkedIn Account Management

### Two Accounts
| Account   | Chrome Profile Dir     | |
|-----------|------------------------|-------------------------|
| Maurice   | `user_data_maurice/`   | 
| Leon      | `user_data_leon/`      |    |

### Rules
- Each lead is assigned to ONE account (stored in Attio)
- That account handles the entire lifecycle: connect --> message --> all follow-ups
- Both accounts share the same Attio workspace

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
- When a new lead list is imported into Attio, it typically gets a new or existing template assigned
- Each account can run a **different template and list** independently

### List Processing
The Connection Bot **auto-continues** through a list day by day:
- Processes ~10-20 leads per day
- Picks up where it left off (filter: status = NEW)
- Continues until all leads in the list are processed

### Notifications (Low Priority - implement if easy)
- **List exhausted:** Notify the user when a list has no more NEW leads to process
- **Daily summary:** After each bot run, send a summary report to the user (connections sent, messages sent, follow-ups, replies detected, errors, remaining leads)

Not critical. If easy to implement, do it. If not, skip.

---

## Key Engineering Decisions for Yatharth

1. **Attio data model:** How to best structure lists, fields, and views in Attio given its API capabilities
2. **Attio API integration:** Replace all Supabase read/write calls with Attio API equivalents
3. **Template testing workflow:** Design a clean way to test new prompts before going live
4. **Cron scheduling:** Best schedule for running 3 bots x 2 accounts daily without overlap

