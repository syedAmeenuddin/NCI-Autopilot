# NCI Monitoring & Reporting Automation

Automates the manual parts of Issue Management process rows 2 ("Report
Extraction & Preparation") and part of row 3 ("Action Plan & SLA
Management") from the source process sheet: pulling NCIs from ServiceNow
GRC across regions, filtering/aggregating them, and emailing the right
people from the tracker — surfaced through a Copilot Studio agent.

Rows like quality checks, audits, and KT sessions stay manual by design —
they need judgment, not a query.

## What's in here

| Path | What it is | Status |
|---|---|---|
| `GUIDE.md` | Plain-language, click-by-click build guide (for a non-technical builder) | Ready to send as-is |
| `scripts/nci_engine.py` | Reference implementation of the filter/aggregate/report/recipient logic | Runs today against sample data |
| `scripts/test_nci_engine.py` | Automated tests locking down the business rules | 8/8 passing |
| `data/sample_nci_data.csv` | Mock NCI records shaped like the real GRC fields | Sample — swap for a real export |
| `data/sample_nci_data.json` | Same data as JSON, shaped like a ServiceNow API response | Use to mock the GRC connector in Power Automate testing |
| `config/tracker.csv` | Account → email recipient mapping | Sample — replace with the real tracker |
| `config/instances.csv` | Region → ServiceNow instance URL | Sample — fill in real instance URLs |
| `power-automate/*.json` | Three cloud flow definitions (Workflow Definition Language) | Blueprint — needs your tenant's connections wired in before import |
| `copilot-studio/topics/*.yml` | Two Copilot Studio topics (paste into the Code editor view) | Blueprint — needs the flow names matched after import |

## Try the logic right now (no Microsoft tooling needed)

```bash
cd nci-automation
python3 scripts/nci_engine.py query --department Cloud --account Contoso
python3 scripts/nci_engine.py report --period weekly --region APAC --send
```

This proves out the exact rules — what counts as overdue, what counts as
an excessive extension (>2), what's due in 7 days, who gets emailed — on
real (sample) data, before touching ServiceNow or Power Platform at all.
`--send` prints what would be emailed instead of actually sending, since
there's no live mailbox connection here.

## The three flows, and how they chain

```
Copilot Studio agent
   ├─ "give me open NCIs for X"  ──▶ flow-get-open-ncis.json
   └─ "prepare the NCI report"   ──▶ flow-generate-nci-report.json
                                        │
                                        ├─▶ calls flow-get-open-ncis.json (reuse, no duplicate fetch)
                                        └─▶ calls flow-send-nci-email.json once per account
                                                 └─▶ looks up recipients in the tracker, sends via Outlook
```

`flow-generate-nci-report.json` also has a Recurrence-trigger variant noted
in its `_deployment_notes` for the unattended daily/weekly scorecard (no
Copilot Studio involved — it just runs and emails on schedule).

## How to actually stand this up in your tenant

I can't do this part from here — it needs your Power Platform environment,
your ServiceNow GRC credentials, and your real tracker/instance data, none
of which this session has access to. Steps for whoever has that access:

1. **Get real inputs first**, don't skip to building:
   - Export a real (even scrubbed) sample of NCIs from ServiceNow GRC with actual column names — replace `data/sample_nci_data.csv`'s header to match, then re-run the script above to sanity-check the filter/metric logic against real fields.
   - Move `config/tracker.csv` and `config/instances.csv` into SharePoint lists or Dataverse tables (`RecipientTracker`, `InstanceConfig`) — Power Automate queries those directly; hand-maintained Excel is what caused the manual bottleneck in the first place.
2. **Create connections** in Power Automate for: ServiceNow (or HTTP + OAuth client-credentials per region if the managed connector doesn't expose the GRC issue table), SharePoint Online, Office 365 Outlook.
3. **Import the flows** in dependency order: `flow-get-open-ncis.json` first, then `flow-generate-nci-report.json` (references it as a child flow), then `flow-send-nci-email.json`. Each file's `_deployment_notes` lists what to rewire (site URLs, list names, connection references) — these are blueprints, not one-click imports, because they were written without access to your environment's actual connection IDs.
4. **In Copilot Studio**, create the agent, add a topic, switch to the Code editor (`</>`) view, and paste in each `.yml` file. Update the `flow:` name in each to match what the flow is actually called after import, then re-link via the "Add an action → Power Automate" picker so Copilot Studio binds it properly (the pasted YAML gets you 90% there, but the flow reference has to be re-selected through the UI once).
5. **Test with one account first** (e.g. Contoso/APAC) end-to-end before turning on the scheduled scorecard for everyone.

## How to test this

There are three layers here, and only the first one can be tested right
now — the other two need a Power Platform environment, which this session
doesn't have access to.

### 1. The logic itself — testable right now

```bash
cd nci-automation
python3 -m pytest scripts/test_nci_engine.py -v
```

8 tests, all passing. They lock down the actual rules from the process
sheet — overdue detection, the >2 excessive-extension threshold, the
due-in-7-days bucket, the >1-year aging flag, and recipient lookup —
against known values in the sample data. If someone edits
`nci_engine.py` later and breaks a rule, this catches it immediately
instead of it showing up wrong in a live email.

You can also just poke at it manually:
```bash
python3 scripts/nci_engine.py query --region USA --status Open
python3 scripts/nci_engine.py report --period weekly --account Umbrella --send
```

### 2. The Power Automate flows — needs a Power Platform environment, but not live ServiceNow access yet

Once the flows are built in the Power Automate designer (following the
`power-automate/*.json` blueprints), test them **without** waiting on real
GRC credentials:

- In `flow-get-open-ncis.json`'s "Get NCIs from ServiceNow GRC" step,
  temporarily swap the ServiceNow/HTTP action for a **Compose** action
  that returns the contents of `data/sample_nci_data.json` (copy-paste the
  JSON in as the static value). That gives every downstream step —
  filter, select, respond — real-shaped data to run against.
- Use Power Automate's **Test** button (top right of the designer) →
  "I'll perform the trigger action" → manually type in an account/region
  → run it → inspect each step's output in the run history. This is where
  you catch expression typos (the `@equals(...)`, `@filter(...)` bits)
  before they ever touch a live system.
- Once the ServiceNow connection is actually available, swap the Compose
  mock back out for the real connector action and re-run the same test —
  if the downstream steps still pass, the mock was faithful.

### 3. The Copilot Studio agent — needs the agent created and flows imported first

- Copilot Studio has a **Test copilot** panel on the right side of the
  authoring screen — type the exact trigger phrases from the `.yml`
  files ("Give me the latest open NCIs for cloud accounts") and confirm
  the right topic fires.
- Turn on **"Track between messages"** in that test panel to see the
  actual variable values (`Topic.NCIResult`, `Topic.Period`, etc.) at
  each step — this is how you debug a topic that fires but returns
  nothing, usually because the flow name in the YAML doesn't match the
  imported flow's display name yet.
- Test with one narrow case first (e.g. "show open NCIs for Contoso")
  before testing the no-filter "give me all open NCIs" case, since that
  one exercises every region in the loop.

## Known gaps to close with your friend before go-live

- Exact ServiceNow GRC table/field names for NCIs (the sample uses guessed names like `sn_grc_issue`).
- Whether Power BI needs a live feed (there's a hook point noted in `flow-generate-nci-report.json`) or if the emailed HTML table is enough for now.
- Who owns keeping the tracker list current once it moves off the macro file.
