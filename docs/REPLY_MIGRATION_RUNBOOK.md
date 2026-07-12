# Reply Management — Migration Runbook

_Everything needed to move your live Reply Manager (reply.ascendly.one) into
RevCadence: the config (client profiles, reply formats, rules, keys, Calendly),
the global settings, and all the historical replies — with each reply synced
into the CRM. Enrichment is **not** part of this; import that manually/later._

Read top to bottom. Nothing here writes to your legacy system — every step is
read-only on the old database and reversible on the new one (dry-run first).

---

## 0. The picture (what we're doing and why)

Your legacy Reply Manager has two things worth moving:

1. **Config** — per-client reply spaces (platform, API key, Bison base URL,
   follow-up campaign id, Calendly, AI provider, **client profile**, **reply
   format** = response types + FUP1–6) and **global settings** (OpenAI/Gemini
   keys + models, human-review webhook, reply delay, trigger tags) and your
   **AI rules**.
2. **Data** — every processed reply (intent, decision, drafted reply, follow-
   ups, full thread, raw platform lead_data, stage).

We move config first (so the engine behaves identically), then the data (so
history shows up), then repoint the webhooks (so new replies flow into
RevCadence). During the transition the legacy system keeps running untouched.

Two scripts do the heavy lifting, both read-only on legacy + idempotent:
- `scripts/import_reply_config.py` — the config + global settings.
- `scripts/import_reply_leads.py` — the historical replies (+ CRM sync).

Both map each legacy `workspace_name` to a RevCadence client workspace through a
**WorkspaceAlias** (source `reply_manager`) — the same mapping the CRM import used.

---

## 1. Get the legacy database URL (2 min)

1. Open the **OLD Reply Manager** Railway project.
2. Its **Postgres** service → **Connect** tab.
3. Copy the **Public Network** connection string. It looks like:
   `postgresql://postgres:PASSWORD@HOST.proxy.rlwy.net:PORT/railway`

⚠ Use the **public** (`proxy.rlwy.net`) URL, not the private
`postgres.railway.internal` one — the RevCadence project cannot reach the old
project's private network.

You'll paste this *real* string wherever this doc shows `"<LEGACY_URL>"`. Do not
paste the literal text `<LEGACY_URL>` — that's a placeholder.

---

## 2. Make sure each client workspace exists in RevCadence (2 min)

In RevCadence (as owner): top-left workspace switcher. If **Ascendly** (and any
other client) isn't there, create it in **Admin → Workspaces → + Workspace**.
Creating a workspace auto-provisions its CRM pipeline, enrichment config, and a
default reply space — no extra steps.

---

## 3. Create the reply_manager aliases (3 min) — THE mapping

The importers need to know that the legacy name `Ascendly: mainreplybison`
belongs to the RevCadence **Ascendly** workspace.

For **each** legacy reply workspace name:
Admin → **Workspace aliases** → **+ Alias**
- Canonical workspace: **Ascendly** (the RevCadence client)
- Source system: **reply_manager**
- Exact legacy name: `Ascendly: mainreplybison` (must match exactly, including
  the colon and spacing)

Repeat for every legacy workspace name (e.g. a follow-up space, other clients).
Don't know all the names? The dry runs in steps 4–5 print any `unmapped` names —
add aliases for those and re-run.

---

## 4. Import the CONFIG + settings (5 min)

Open the RevCadence **web** service → **Console** (the shell in your screenshot).

**Dry run** (writes nothing, shows what it would do):
```bash
/opt/venv/bin/python -m scripts.import_reply_config --legacy-db-url "<LEGACY_URL>"
```
Read the JSON:
- `reply_spaces_created` / `reply_spaces_updated` — how many spaces it will set up.
- `global_settings` — how many global settings (keys/model/webhook/…) it found.
- `unmapped` — legacy names with no alias yet. **If non-empty, go back to step 3**,
  add those aliases, and re-run the dry run until `unmapped` is `[]`.

**Apply:**
```bash
/opt/venv/bin/python -m scripts.import_reply_config --legacy-db-url "<LEGACY_URL>" --apply
```
This creates/updates each reply space with the platform, API key (encrypted),
base URL, campaign id, Calendly, AI provider, **client profile**, **reply
format** (response types + follow-ups, normalized to the structured editor), and
seeds your global **AI rules** onto each space. It also imports the global
**Reply Settings** (keys, models, webhook, delay, trigger tags).

**Verify:** Reply Management → pick Ascendly → **Setup**. The connection fields,
client profile, response types, and follow-ups should all be filled in. Reply
Management → **Reply Settings** should show your models + "key · set".

---

## 5. Import the historical REPLIES (5 min)

Still in the web Console.

**Dry run:**
```bash
/opt/venv/bin/python -m scripts.import_reply_leads --legacy-db-url "<LEGACY_URL>"
```
Read the JSON:
- `seen` / `imported` — total legacy replies and how many will import.
- `crm_contacts` / `deals` — CRM contacts and pipeline deals it will create.
- `unmapped` — same alias check as before; fix in step 3 if non-empty.

**Apply:**
```bash
/opt/venv/bin/python -m scripts.import_reply_leads --legacy-db-url "<LEGACY_URL>" --apply
```
Every legacy reply lands in RevCadence exactly as it was (intent, confidence,
action, drafted reply, follow-ups, full thread, raw lead_data, stage) AND each
one syncs into the CRM: a contact + company, and a **deal** — booked leads go to
the *Meeting Booked* stage, every other interested reply to *Opportunity*.

**Verify:** Reply Management → **Dashboard** (counts populate) and **Inbox**
(replies listed; open one — lead details + full conversation show). CRM →
**Pipeline** (Opportunity + Meeting Booked columns fill from the imports).

Both scripts are idempotent — safe to re-run; already-imported rows are skipped
by `dedupe_key`.

---

## 6. Point the webhooks at RevCadence (5 min) — go live

Only after steps 4–5 look right. This is what makes NEW replies flow into
RevCadence. Do it per platform; the legacy system keeps receiving too until you
turn its webhooks off (parallel run — recommended for a few days).

- **Bison**: set the webhook to
  `https://<revcadence-domain>/api/reply/webhooks/bison?reply_workspace=<name>&fup_workspace=<name>`
  where `<name>` is the reply-space name (e.g. `Ascendly: mainreplybison`).
- **Instantly** (per sending account): set the webhook to
  `https://<revcadence-domain>/api/reply/webhooks/instantly?workspace_name=<name>`

Then in Setup, make sure each reply space is **Active**.

### Safety: auto-send is OFF by default
Until you set the env var `AUTO_SEND_ENABLED=1` on both the web and worker
services, every reply that *would* auto-send instead lands in **Needs Review**
as `would_send`. So you can point real webhooks at RevCadence and watch it make
the exact right decisions with zero risk of a wrong email going out. Use **Test
Thread** (Reply Management → Test Thread) to validate on real threads first,
then flip the switch when you trust it.

---

## 7. Parallel run → cutover

1. Keep the legacy system receiving webhooks for a few days alongside RevCadence.
2. Compare: same replies, same decisions (Test Thread helps).
3. When confident: remove the webhooks from the legacy system (or set its
   workspaces inactive) so RevCadence is the sole receiver.
4. `proposed_slots` (Calendly reservations) are ephemeral — not migrated; they
   rebuild themselves as new replies come in.

---

## What we are NOT doing here
- **Enrichment import** — skipped on purpose; import lists/leads manually or
  later (the enrichment engine is already live in Outbound).
- **Ascendly Studio / proposals** (blueprints/agreements) — separate module,
  separate migration (portals Service API), tracked in REPLY_PORT_SPEC.md.

---

## Quick reference

| Task | Command (web Console) |
|---|---|
| Config dry run | `/opt/venv/bin/python -m scripts.import_reply_config --legacy-db-url "<LEGACY_URL>"` |
| Config apply | `… import_reply_config … --apply` |
| Replies dry run | `/opt/venv/bin/python -m scripts.import_reply_leads --legacy-db-url "<LEGACY_URL>"` |
| Replies apply | `… import_reply_leads … --apply` |

Order: aliases (step 3) → config apply (4) → replies apply (5) → webhooks (6).
