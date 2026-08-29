# NCI Autopilot — Build Guide

A step-by-step walkthrough for building the agent that answers "give me
open NCIs" and "prepare the NCI report," so the manual copy-paste between
ServiceNow GRC, Excel, and email stops being a person's job.

Work through the parts **in order** — each one builds on the last.

```
ServiceNow GRC (APAC / USA / Europe)
        │
        ▼
   Flow 1 — Get Open NCIs  ◄──── Copilot Studio agent (chat)
        │
        ▼
   Flow 2 — Generate NCI Report  ◄──── Copilot Studio agent (chat)
        │
        ▼
   Flow 3 — Send NCI Email
        │
        ├──► Recipient tracker (lookup)
        └──► Team inbox
```

Everything below is built and tested against **sample data first**, not
live ServiceNow — so nothing is blocked on GRC API access until the very
last part (Part 6).

---

## Before you start

Confirm these with IT first — if any are missing, that's the real
blocker, not something to work around:

- [ ] **Power Automate access, with premium connectors.** The ServiceNow
      connector is a premium connector — a basic/free license won't
      include it.
- [ ] **Copilot Studio license.** Separate from Power Automate — check
      it's actually assigned.
- [ ] **A SharePoint site you can create a list in.** This replaces the
      email-tracker spreadsheet later (Part 6). Any site with edit access
      works.

---

## Part 1 — Get Open NCIs (Power Automate)

Answers one question: "which NCIs are open, for this account / region /
department?" The other two flows reuse this one.

- [ ] **Create the flow.** At make.powerautomate.com → **My flows → New
      flow → Instant cloud flow**. Name it `flow-get-open-ncis`.
- [ ] **Pick the trigger.** Search "Power Virtual Agents" or "Copilot
      Studio" and choose the option that lets a Copilot agent call this
      flow. (Exact wording varies by tenant version — pick the closest
      match.)
- [ ] **Add three input fields to the trigger** — all optional text:

  | Name | Type |
  |---|---|
  | `account` | Text |
  | `region` | Text |
  | `department` | Text |

- [ ] **Add a "Compose" action — stand-in data for now.** Rename it "Mock
      NCI Data" and paste this into its Inputs box:

  ```json
  {
    "result": [
      {"nci_id":"NCI-10001","account":"Contoso","region":"APAC","department":"Cloud","severity":"High","status":"Open","due_date":"2026-06-01","extension_count":0},
      {"nci_id":"NCI-10002","account":"Contoso","region":"APAC","department":"NMS","severity":"Medium","status":"Open","due_date":"2026-08-20","extension_count":1},
      {"nci_id":"NCI-10003","account":"Fabrikam","region":"USA","department":"Cloud","severity":"Critical","status":"Open","due_date":"2026-01-10","extension_count":3},
      {"nci_id":"NCI-10009","account":"Umbrella","region":"USA","department":"Cloud","severity":"Critical","status":"Open","due_date":"2025-07-15","extension_count":4}
    ]
  }
  ```

- [ ] **Add a "Filter array" action.** From: `outputs('Mock_NCI_Data')?['result']`.
      Switch the condition field to advanced mode and paste:

  ```
  @and(
    or(empty(triggerBody()?['account']), equals(item()?['account'], triggerBody()?['account'])),
    or(empty(triggerBody()?['department']), equals(item()?['department'], triggerBody()?['department'])),
    equals(item()?['status'], 'Open')
  )
  ```

- [ ] **Add a "Select" action.** From: the Filter array output. Map:
      `nci_id`, `account`, `region`, `severity`, `due_date`,
      `extension_count`.
- [ ] **Add the response action.** Search "Respond to the Copilot" (or
      "Respond to Power Virtual Agents"). Add two outputs:
      `matchCount` = `length(body('Select'))`, and `matches` = the Select
      output.
- [ ] **Save.** Don't test yet — that's Part 5, once everything's built.

---

## Part 2 — Generate NCI Report (Power Automate)

Reuses Flow 1 instead of fetching data twice, then works out the numbers
that matter — overdue count, excessive extensions, what's due soon — per
account.

- [ ] **Create the flow.** Instant cloud flow, name it
      `flow-generate-nci-report`, same Copilot trigger, with inputs
      `period`, `account`, `region` (all optional text).
- [ ] **Call Flow 1 as a child.** Add action → search
      "flow-get-open-ncis" (shows up as an action once saved) → pass
      through `account` and `region` from the trigger.
- [ ] **Get the distinct list of accounts.** Add a Compose action:

  ```
  @union(body('flow-get-open-ncis')?['matches'], body('flow-get-open-ncis')?['matches'])
  ```

  (This `union(x, x)` trick de-duplicates a list.)

- [ ] **Loop over each account** — add an "Apply to each" over that
      list. Inside the loop, add four actions:

  | Action | What it does |
  |---|---|
  | Filter array | Keep only this loop's account from the Flow 1 results |
  | Compose (metrics) | Counts overdue / excessive-extension / due-soon |
  | Create HTML table | Turns the filtered rows into a table for the email |
  | flow-send-nci-email | Calls Flow 3, passing account, period, metrics, table |

- [ ] **The metrics formula** — paste into the Compose (metrics) action:

  ```
  {
    "totalOpen": @{length(body('Filter_array'))},
    "overdueCount": @{length(filter(body('Filter_array'), item => less(item()?['due_date'], utcNow())))},
    "excessiveExtensionCount": @{length(filter(body('Filter_array'), item => greater(item()?['extension_count'], 2)))}
  }
  ```

- [ ] **Respond to the Copilot.** One output: `status` = a plain text
      confirmation, e.g. "Report generated and sent to tracked
      recipients."

> **Later:** clone this flow with a **Recurrence** trigger (e.g. daily at
> 7am) instead of the Copilot trigger, and it becomes the unattended
> daily/weekly scorecard — no chat request needed.

---

## Part 3 — Send NCI Email (Power Automate)

Looks up who should get the report for one account, and sends it. Called
by Flow 2 — you won't run this one directly.

- [ ] **Create the flow.** Instant cloud flow, name it
      `flow-send-nci-email`. Trigger: **Manually trigger a flow** (this is
      what lets another flow call it).
- [ ] **Add trigger inputs:**

  | Name | Type |
  |---|---|
  | `account` | Text |
  | `period` | Text |
  | `totalOpen` | Number |
  | `overdueCount` | Number |
  | `excessiveExtensionCount` | Number |
  | `htmlTable` | Text |

- [ ] **Add a "Compose" with the tracker data (stand-in for now)**, then a
      Filter array on `account` equal to the trigger's account:

  ```json
  [
    {"account":"Contoso","to_emails":"contoso.lead@example.com;contoso.pm@example.com","cc_emails":"issuemgmt.apac@example.com"},
    {"account":"Fabrikam","to_emails":"fabrikam.lead@example.com","cc_emails":"issuemgmt.usa@example.com"},
    {"account":"Umbrella","to_emails":"umbrella.lead@example.com","cc_emails":"issuemgmt.usa@example.com"}
  ]
  ```

- [ ] **Add a "Condition" — recipients found?**
      **If yes:** add "Send an email (V2)" (Outlook) — To/Cc from the
      filtered recipient row, subject `NCI [period] Report — [account]`,
      body combining the metrics and the HTML table.
      **If no:** add a Compose logging "No tracker entry for this
      account."

---

## Part 4 — Build the Copilot Agent (Copilot Studio)

This is the chat window people actually type into. It doesn't do any
work itself — it just calls the flows above and shows what comes back.

- [ ] **Create the agent.** At copilotstudio.microsoft.com → **Create →
      New agent**. Name it, e.g. "NCI Assistant".
- [ ] **Add the first topic.** **Topics → Add a topic → From blank**.
      Find the code-view toggle (usually `</>` near the top of the topic
      editor) and paste this in, replacing whatever's there:

  ```yaml
  kind: AdaptiveDialog
  beginDialog:
    kind: OnRecognizedIntent
    id: main
    intent:
      triggerQueries:
        - "Give me the latest open NCIs for cloud accounts"
        - "Show open NCIs for {account}"
        - "What NCIs are open in {region}"
    actions:
      - kind: InvokeFlowAction
        id: callGetOpenNCIs
        flow: flow-get-open-ncis
        input:
          account: =System.Recognizer.entities.account
          region: =System.Recognizer.entities.region
        output:
          binding: Topic.NCIResult
      - kind: SendActivity
        id: sendMatches
        activity: "Found {Topic.NCIResult.matchCount} open NCI(s): {Topic.NCIResult.matches}"
  ```

- [ ] **Reconnect the flow reference.** The pasted YAML will likely show
      the flow step as unresolved. Switch back to canvas view, open that
      action, and re-pick it via **Add an action → Power Automate flow →
      flow-get-open-ncis**.
- [ ] **Confirm the entities.** When Copilot Studio sees `{account}` or
      `{region}` in a trigger phrase, it'll offer to create an entity for
      it — accept that; it's what lets people fill in "Contoso" or
      "APAC" in a real sentence.
- [ ] **Add the second topic the same way** — new topic, code view, paste
      this, then reconnect its flow reference to
      `flow-generate-nci-report`:

  ```yaml
  kind: AdaptiveDialog
  beginDialog:
    kind: OnRecognizedIntent
    id: main
    intent:
      triggerQueries:
        - "Prepare the NCI report for this period"
        - "Generate the weekly NCI scorecard"
        - "Send the NCI report for {account}"
    actions:
      - kind: InvokeFlowAction
        id: callGenerateReport
        flow: flow-generate-nci-report
        input:
          account: =System.Recognizer.entities.account
          region: =System.Recognizer.entities.region
        output:
          binding: Topic.ReportResult
      - kind: SendActivity
        id: confirmSent
        activity: "{Topic.ReportResult.status}"
  ```

---

## Part 5 — Test It

Test one layer at a time — a flow that fails silently inside a chat is
much harder to debug than one tested on its own first.

- [ ] **Test Flow 1 alone.** Open it → **Test** (top right) → "I'll
      perform the trigger action" → type a sample account → Run. Click
      into the run and check each step for a green check. A red X means
      click that step to see exactly which input was wrong.
- [ ] **Test Flow 2, then Flow 3** the same way. Flow 2's own test trace
      should show Flow 1 and Flow 3 both running inside it — expand them
      to check.
- [ ] **Test the agent in chat.** Use the **Test agent** panel on the
      right of the Copilot Studio screen. Type "Give me the latest open
      NCIs for cloud accounts" and confirm the topic fires and shows data
      back.
- [ ] **Turn on message tracking if something's silent.** If a topic
      fires but nothing useful comes back, enable "Track between
      messages" in the test panel — it shows the actual variable values
      at each step, which is usually where a mismatched flow name shows
      up.

---

## Part 6 — Go Live

Only after everything above works against sample data — swap the
stand-ins for the real things, one at a time, and re-run the same tests.

- [ ] **Replace the Mock NCI Data step** with the real ServiceNow
      connector (or an HTTP + OAuth call). You'll need from your
      ServiceNow/GRC admin: the instance URL per region, the exact GRC
      issue table name, and the auth method.
- [ ] **Move the tracker into a real SharePoint list.** Columns:
      `Account`, `Region`, `ToEmails`, `CcEmails`. Swap Flow 3's mock
      Compose for a "Get items" action against that list.
- [ ] **Re-run the Part 5 tests against real data.** Field names from
      the real GRC table almost never match the guessed ones here
      exactly — expect to adjust the Filter/Select field names once, then
      re-test.
- [ ] **Publish the agent.** Copilot Studio → Publish. Then share it with
      the team through a Teams channel or the direct agent link.

---

Built alongside a tested Python reference implementation of this same
logic (filtering, overdue/extension rules, recipient lookup) — see
`scripts/nci_engine.py` and `scripts/test_nci_engine.py` in this project,
useful if a developer wants to double-check the rules independently
before they go into these flows.
