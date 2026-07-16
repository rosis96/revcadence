"""CRM sync foundation. One provider interface; the Generic webhook/API provider
is fully implemented (outbound). Native HubSpot/Salesforce/GoHighLevel/Pipedrive/
Zoho adapters plug into the same interface later — they are represented in the UI
but NOT claimed as complete.

Outbound sync: RevCadence entities → provider.create_or_update_*; every synced
record gets a SyncMapping row (duplicate-safe, idempotent by mapping lookup)."""
import json
from datetime import datetime

import requests

from ..models.crm import Activity, Company, Contact, Deal, Stage
from ..models.devapi import SyncConnection, SyncMapping
from ..models.jobs import Job
from .security import decrypt_credentials, is_safe_webhook_url, sign_webhook

PROVIDERS = ["generic", "hubspot", "salesforce", "gohighlevel", "pipedrive", "zoho"]
NATIVE_READY = {"generic"}   # only providers with a real, tested implementation
CONFLICT_POLICIES = ["revcadence_wins", "external_wins", "newest_wins", "flag_review"]


class ProviderBase:
    """Shared CRM adapter interface."""

    def __init__(self, conn: SyncConnection, config: dict):
        self.conn = conn
        self.config = config

    def test_connection(self) -> tuple[bool, str]: raise NotImplementedError
    def create_or_update_company(self, data: dict, external_id: str | None) -> str: raise NotImplementedError
    def create_or_update_contact(self, data: dict, external_id: str | None) -> str: raise NotImplementedError
    def create_or_update_deal(self, data: dict, external_id: str | None) -> str: raise NotImplementedError
    def create_activity(self, data: dict) -> str: raise NotImplementedError
    def update_deal_stage(self, external_id: str, stage: str) -> None: raise NotImplementedError
    def fetch_changes(self, since: datetime | None) -> list: return []   # inbound (not for generic v1)


class GenericWebhookProvider(ProviderBase):
    """Pushes entity upserts to the client's endpoint as signed JSON. The client
    system replies {"external_id": "..."} (optional) to record its own id."""

    @property
    def url(self):
        return self.config.get("url", "")

    def _post(self, kind: str, payload: dict) -> dict:
        ok, why = is_safe_webhook_url(self.url)
        if not ok:
            raise RuntimeError(f"unsafe sync url: {why}")
        body = json.dumps({"type": kind, "data": payload}, separators=(",", ":")).encode()
        ts = str(int(datetime.utcnow().timestamp()))
        sig = sign_webhook(self.config.get("secret", ""), ts, body)
        r = requests.post(self.url, data=body, timeout=15, headers={
            "Content-Type": "application/json",
            "X-RevCadence-Signature": f"t={ts},v1={sig}",
        })
        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json() if r.content else {}
        except ValueError:
            return {}

    def test_connection(self):
        try:
            self._post("sync.test", {"ping": True})
            return True, ""
        except Exception as ex:
            return False, str(ex)

    def _upsert(self, kind, data, external_id):
        resp = self._post(kind, {**data, "external_id": external_id})
        return str(resp.get("external_id") or external_id or "")

    def create_or_update_company(self, data, external_id):
        return self._upsert("company.upsert", data, external_id)

    def create_or_update_contact(self, data, external_id):
        return self._upsert("contact.upsert", data, external_id)

    def create_or_update_deal(self, data, external_id):
        return self._upsert("deal.upsert", data, external_id)

    def create_activity(self, data):
        resp = self._post("activity.create", data)
        return str(resp.get("external_id") or "")

    def update_deal_stage(self, external_id, stage):
        self._post("deal.stage_changed", {"external_id": external_id, "stage": stage})


def get_provider(conn: SyncConnection) -> ProviderBase:
    cfg = {}
    try:
        cfg = json.loads(decrypt_credentials(conn.config_encrypted)) if conn.config_encrypted else {}
    except Exception:
        cfg = {}
    if conn.provider == "generic":
        return GenericWebhookProvider(conn, cfg)
    raise RuntimeError(
        f"The {conn.provider} adapter is not implemented yet. Use the Generic "
        "webhook/API provider, or wait for the native integration.")


def _mapping(db, conn, etype, local_id) -> SyncMapping:
    m = (db.query(SyncMapping)
         .filter(SyncMapping.workspace_id == conn.workspace_id,
                 SyncMapping.provider == conn.provider,
                 SyncMapping.local_entity_type == etype,
                 SyncMapping.local_entity_id == local_id).first())
    if not m:
        m = SyncMapping(workspace_id=conn.workspace_id, provider=conn.provider,
                        local_entity_type=etype, local_entity_id=local_id)
        db.add(m)
        db.flush()
    return m


def _apply_field_map(data: dict, mapping: dict) -> dict:
    if not mapping:
        return data
    return {mapping.get(k, k): v for k, v in data.items()}


def run_sync(db, connection_id: int, entity_ids: dict | None = None, progress=None) -> dict:
    """Outbound sync for one connection. entity_ids optionally restricts to
    {"companies": [...], "contacts": [...], "deals": [...]} (event-triggered sync)."""
    conn = db.get(SyncConnection, connection_id)
    if not conn or not conn.active:
        return {"skipped": "connection missing or inactive"}
    if conn.direction == "inbound":
        return {"skipped": "connection is inbound-only"}
    provider = get_provider(conn)
    fm = conn.field_mappings or {}
    stages = {s.id: s.name for s in db.query(Stage).filter(Stage.workspace_id == conn.workspace_id)}
    counts = {"synced": 0, "failed": 0}
    entities = conn.entities or ["companies", "contacts", "deals"]

    def sync_rows(etype, rows, serialize, push):
        for row in rows:
            m = _mapping(db, conn, etype, row.id)
            try:
                data = _apply_field_map(serialize(row), fm.get(etype, {}))
                ext = push(data, m.external_entity_id or None)
                m.external_entity_id = ext or m.external_entity_id
                m.sync_status = "synced"
                m.last_error = ""
                m.last_synced_at = datetime.utcnow()
                counts["synced"] += 1
            except Exception as ex:
                m.sync_status = "failed"
                m.last_error = str(ex)[:500]
                counts["failed"] += 1
            db.commit()

    if "companies" in entities:
        q = db.query(Company).filter(Company.workspace_id == conn.workspace_id)
        if entity_ids and entity_ids.get("companies"):
            q = q.filter(Company.id.in_(entity_ids["companies"]))
        sync_rows("company", q.all(),
                  lambda c: {"name": c.name, "domain": c.domain, "website": c.website,
                             "industry": c.industry, "location": c.location},
                  provider.create_or_update_company)
    if "contacts" in entities:
        q = db.query(Contact).filter(Contact.workspace_id == conn.workspace_id)
        if entity_ids and entity_ids.get("contacts"):
            q = q.filter(Contact.id.in_(entity_ids["contacts"]))
        sync_rows("contact", q.all(),
                  lambda c: {"email": c.email, "first_name": c.first_name,
                             "last_name": c.last_name, "title": c.title,
                             "company_id": c.company_id},
                  provider.create_or_update_contact)
    if "deals" in entities:
        sm = conn.stage_mappings or {}
        q = db.query(Deal).filter(Deal.workspace_id == conn.workspace_id)
        if entity_ids and entity_ids.get("deals"):
            q = q.filter(Deal.id.in_(entity_ids["deals"]))
        sync_rows("deal", q.all(),
                  lambda d: {"name": d.name, "value": d.value,
                             "stage": sm.get(stages.get(d.stage_id, ""), stages.get(d.stage_id, "")),
                             "company_id": d.company_id, "contact_id": d.contact_id},
                  provider.create_or_update_deal)

    conn.last_sync_at = datetime.utcnow()
    conn.last_error = "" if counts["failed"] == 0 else f"{counts['failed']} record(s) failed"
    db.commit()
    return counts


def queue_sync(db, connection_id: int, workspace_id: int, entity_ids: dict | None = None):
    db.add(Job(workspace_id=workspace_id, kind="crm_sync",
               payload={"connection_id": connection_id, "entity_ids": entity_ids or {}},
               max_attempts=3))
    db.commit()
