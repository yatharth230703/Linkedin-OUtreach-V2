"""
Shared Attio CRM client for LinkedIn automation bots.

Provides a singleton AttioClient with methods for querying bot_inputs,
saving/updating leads_sources records, and managing lead lifecycle.
"""

import os
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Key selection helpers
# ---------------------------------------------------------------------------

YATHARTH_SLUGS = {"yatharth_bisht", "yatharth bisht", "yatharth"}

# Module-level active account — set once per process via set_active_account()
_active_account: str = ""


def set_active_account(account_name: str):
    """Set the active account for this process. Call once at bot startup."""
    global _active_account, _client_instances
    _active_account = account_name.strip()
    # Clear cache so next get_attio_client() picks the right key
    _client_instances.clear()


def _is_yatharth(account_name: str) -> bool:
    return account_name.strip().lower() in YATHARTH_SLUGS


def _pick_attio_key(account_name: str) -> str:
    if _is_yatharth(account_name):
        return os.getenv("ATTIO_API", "")
    return os.getenv("ATTIO_API_ALT", "") or os.getenv("ATTIO_API", "")


# ---------------------------------------------------------------------------
# Per-account singleton cache
# ---------------------------------------------------------------------------
_client_instances: dict[str, "AttioClient"] = {}


def get_attio_client(account_name: str = ""):
    """Return an AttioClient for the given account (cached per key).
    Falls back to _active_account if no account_name provided."""
    global _client_instances
    effective_account = account_name or _active_account
    api_key = _pick_attio_key(effective_account)
    if not api_key:
        raise RuntimeError("No ATTIO_API key available")
    if api_key not in _client_instances:
        _client_instances[api_key] = AttioClient(api_key=api_key)
    return _client_instances[api_key]


class AttioClient:
    BASE_URL = "https://api.attio.com/v2"
    BOT_INPUTS_SLUG = "bot_inputs"
    LEADS_SOURCES_SLUG = "leads_sources"
    MATCHING_ATTRIBUTE = "linkedin_url"

    def __init__(self, api_key: str = ""):
        if not api_key:
            api_key = os.getenv("ATTIO_API", "")
        if not api_key:
            raise RuntimeError("ATTIO_API environment variable is not set")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Low-level HTTP helpers with rate-limit handling
    # ------------------------------------------------------------------

    def _request(self, method, path, **kwargs):
        url = f"{self.BASE_URL}{path}"
        resp = requests.request(method, url, headers=self.headers, **kwargs)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            print(f"   Attio rate-limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            resp = requests.request(method, url, headers=self.headers, **kwargs)
        return resp

    def _get(self, path):
        return self._request("GET", path)

    def _post(self, path, payload):
        return self._request("POST", path, json=payload)

    def _put(self, path, payload, params=None):
        return self._request("PUT", path, json=payload, params=params)

    def _patch(self, path, payload):
        return self._request("PATCH", path, json=payload)

    def _delete(self, path):
        return self._request("DELETE", path)

    # ------------------------------------------------------------------
    # Value extraction helper
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_value(values, slug):
        """
        Parse Attio's nested value format:
          { "slug": [ { "value": "..." } ] }
        Returns the first value string, or "" if missing.
        """
        entries = values.get(slug, [])
        if not entries:
            return ""
        entry = entries[0]
        # Text attributes store value directly
        if isinstance(entry, dict):
            return entry.get("value", "")
        return str(entry)

    # ------------------------------------------------------------------
    # bot_inputs operations
    # ------------------------------------------------------------------

    def query_bot_inputs(self, lead_manager, limit=25):
        """
        Fetch bot_input records for a specific lead_manager.
        Returns list of dicts: {record_id, linkedin_url, lead_manager, prompt_template}
        """
        payload = {
            "filter": {
                "lead_manager": {"$eq": lead_manager}
            },
            "limit": limit,
        }
        resp = self._post(
            f"/objects/{self.BOT_INPUTS_SLUG}/records/query",
            payload,
        )
        resp.raise_for_status()

        results = []
        for record in resp.json().get("data", []):
            record_id = record["id"]["record_id"]
            values = record.get("values", {})
            results.append({
                "record_id": record_id,
                "linkedin_url": self._extract_value(values, "linkedin_url"),
                "lead_manager": self._extract_value(values, "lead_manager"),
                "prompt_template": self._extract_value(values, "prompt_template"),
            })
        return results


    def delete_bot_input(self, record_id):
        """Hard-delete a bot_input record after processing."""
        resp = self._delete(
            f"/objects/{self.BOT_INPUTS_SLUG}/records/{record_id}"
        )
        if resp.status_code in (200, 204):
            print(f"      Deleted bot_input record {record_id}")
            return True
        else:
            print(f"      Failed to delete bot_input {record_id}: {resp.status_code}")
            return False

    # ------------------------------------------------------------------
    # leads_sources operations
    # ------------------------------------------------------------------

    def check_lead_exists(self, linkedin_url):
        """
        Check if a lead already exists in leads_sources by linkedin_url.
        Returns (exists: bool, record_dict or None).
        """
        payload = {
            "filter": {
                "linkedin_url": {"$eq": linkedin_url}
            },
            "limit": 1,
        }
        try:
            resp = self._post(
                f"/objects/{self.LEADS_SOURCES_SLUG}/records/query",
                payload,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                record = data[0]
                values = record.get("values", {})
                return True, {
                    "record_id": record["id"]["record_id"],
                    "lead_status": self._extract_value(values, "lead_status"),
                }
            return False, None
        except Exception as e:
            print(f"   Attio check_lead_exists error: {e}")
            return False, None

    def save_lead(self, values_dict):
        """
        Upsert a lead into leads_sources using PUT with matching_attribute=linkedin_url.
        values_dict should map Attio slug -> value (plain strings).
        """
        payload = {"data": {"values": values_dict}}
        resp = self._put(
            f"/objects/{self.LEADS_SOURCES_SLUG}/records",
            payload,
            params={"matching_attribute": self.MATCHING_ATTRIBUTE},
        )
        resp.raise_for_status()
        record_id = resp.json()["data"]["id"]["record_id"]
        print(f"   Saved lead to Attio: {values_dict.get('full_name', 'unknown')} ({record_id})")
        return record_id

    def update_lead_status(self, full_name, new_status, last_contacted_at=None):
        """
        Find a lead by full_name, then PATCH its status and last_contacted_at.
        """
        # Query by full_name
        payload = {
            "filter": {
                "full_name": {"$eq": full_name}
            },
            "limit": 1,
        }
        resp = self._post(
            f"/objects/{self.LEADS_SOURCES_SLUG}/records/query",
            payload,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            print(f"   No lead found for '{full_name}' in Attio")
            return False

        record_id = data[0]["id"]["record_id"]
        update_values = {"lead_status": new_status}
        if last_contacted_at:
            update_values["lead_last_contacted_at"] = last_contacted_at

        patch_payload = {"data": {"values": update_values}}
        patch_resp = self._patch(
            f"/objects/{self.LEADS_SOURCES_SLUG}/records/{record_id}",
            patch_payload,
        )
        if patch_resp.status_code in (200, 201):
            print(f"   Updated {full_name} -> '{new_status}'")
            return True
        else:
            print(f"   Failed to update {full_name}: {patch_resp.status_code}")
            return False

    def get_all_leads_for_manager(self, lead_manager):
        """
        Get all leads_sources records for a given lead_manager.
        Returns dict keyed by full_name with lead data.
        """
        all_records = []
        offset = None

        while True:
            payload = {
                "filter": {
                    "lead_manager": {"$eq": lead_manager}
                },
                "limit": 50,
            }
            if offset:
                payload["offset"] = offset

            resp = self._post(
                f"/objects/{self.LEADS_SOURCES_SLUG}/records/query",
                payload,
            )
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", [])
            all_records.extend(data)

            # Check for pagination
            offset = body.get("next_cursor")
            if not offset or len(data) == 0:
                break

        leads_data = {}
        contacted_leads = set()

        for record in all_records:
            values = record.get("values", {})
            full_name = self._extract_value(values, "full_name").strip()
            if not full_name:
                continue

            status = self._extract_value(values, "lead_status").strip()
            leads_data[full_name] = {
                "full_name": full_name,
                "headline": self._extract_value(values, "headline").strip(),
                "status": status,
                "message_1_draft": self._extract_value(values, "message_1_draft").strip(),
            }

            if status == "first message sent":
                contacted_leads.add(full_name)

        return leads_data, contacted_leads

    def get_leads_for_followup(self, lead_manager):
        """
        Get leads_sources records eligible for follow-up.
        Fetches by lead_manager with eligible statuses, then applies
        client-side 3-day gap filter.
        """
        eligible_statuses = [
            "first message sent",
            "follow-up 1 sent",
            "follow-up 2 sent",
            "follow-up 3 sent",
        ]

        all_records = []
        offset = None

        while True:
            payload = {
                "filter": {
                    "lead_manager": {"$eq": lead_manager}
                },
                "limit": 50,
            }
            if offset:
                payload["offset"] = offset

            resp = self._post(
                f"/objects/{self.LEADS_SOURCES_SLUG}/records/query",
                payload,
            )
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", [])
            all_records.extend(data)

            offset = body.get("next_cursor")
            if not offset or len(data) == 0:
                break

        three_days_ago = datetime.now() - timedelta(days=3)
        leads_data = {}

        for record in all_records:
            values = record.get("values", {})
            full_name = self._extract_value(values, "full_name").strip()
            status = self._extract_value(values, "lead_status").strip()

            if not full_name or status not in eligible_statuses:
                continue

            last_contacted = self._extract_value(values, "lead_last_contacted_at").strip()

            # Client-side 3-day gap filter
            if last_contacted:
                try:
                    contacted_dt = datetime.fromisoformat(last_contacted.replace("Z", "+00:00")).replace(tzinfo=None)
                    if contacted_dt > three_days_ago:
                        continue  # Too recent
                except (ValueError, TypeError):
                    pass  # If we can't parse, include it

            leads_data[full_name] = {
                "full_name": full_name,
                "headline": self._extract_value(values, "headline").strip(),
                "status": status,
                "message_2_draft": self._extract_value(values, "message_2_draft").strip(),
                "message_3_draft": self._extract_value(values, "message_3_draft").strip(),
                "message_4_draft": self._extract_value(values, "message_4_draft").strip(),
                "message_5_draft": self._extract_value(values, "message_5_draft").strip(),
                "last_contacted_at": last_contacted,
            }

        return leads_data

    def mark_lead_replied(self, full_name):
        """Convenience: mark a lead as 'LEAD REPLIED'."""
        return self.update_lead_status(full_name, "LEAD REPLIED")
