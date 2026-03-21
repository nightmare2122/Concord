# 05 — DAR (Daily Activity Report) System

## Purpose

The DAR cog automates enforcement of daily activity reporting:
- Employees post their DARs directly in `#daily-activity-report` — no modal, no button, no setup step.
- Bot detects each post via `on_message`, assigns the `DAR Submitted` role, and creates a public discussion thread on the message.
- Removes the role from all members at 11:00 AM IST daily and logs who had submitted.
- Sends DM reminders to members who haven't submitted during evening hours (7–10 PM IST, Mon–Sat).

**File:** `cogs/dar_cog.py`

---

## Key Constants

| Constant | Description |
|---|---|
| `DAR_SUBMITTED_ROLE_ID` | Role assigned when a member submits a DAR |
| `ON_LEAVE_ROLE_ID` | Members on leave are excluded from reminders |
| `PA_ROLE_ID` | PA (Principal Architect) is excluded from reminders |
| `DAR_CHANNEL_ID` | `1281200069416321096` — the `#daily-activity-report` channel |
| `DAR_EXCLUDE_ROLE_ID` | Any additional role exempt from DAR reminders |
| `DAR_LOG_DIRECTORY` | `Database/DAR exports/` — where daily logs are saved |

---

## DAR Submission — Channel-Based Posting

The `#daily-activity-report` channel **is** the submission interface. Employees post any message there and the bot responds automatically:

1. `on_message` fires when a message is posted in `DAR_CHANNEL_ID`
2. Bot assigns the `DAR Submitted` role to the author (if not already held)
3. Bot creates a public discussion thread on the message (`auto_archive_duration=1440`)

There is no submission button, no modal, and no `ensure_dar_ui` setup — the channel itself is the interface.

---

## Background Loop — `check_role_expiry()`

Runs every 60 seconds after `bot.wait_until_ready()`. Checks the current IST time:

### 11:00 AM IST — Role Removal and Logging

- Iterates all guild members
- Removes the `DAR Submitted` role from everyone who has it
- Logs submitted members to `Database/DAR exports/dar_submissions_{YYYY-MM-DD}.txt`

### 7 PM – 10 PM IST (Mon–Sat) — Reminder DMs

- Checks `_last_reminder_hour` to avoid duplicate reminders within the same hour
- DMs every member who:
  - Is not the bot itself
  - Does NOT have `DAR_SUBMITTED_ROLE_ID`
  - Does NOT have `PA_ROLE_ID`
  - Does NOT have `ON_LEAVE_ROLE_ID`
  - Does NOT have `DAR_EXCLUDE_ROLE_ID`
- 1-second sleep between each DM to avoid rate limits

---

## Log Files

Stored in `Database/DAR exports/dar_submissions_{YYYY-MM-DD}.txt`.

Format:
```
DAR Submissions removed at 11:00 AM:
member1
member2
...
```

These are created daily when the 11:00 AM reset runs. They record which members had the `DAR Submitted` role at the time of reset (i.e. who DID submit before the cutoff).

---

## Cog Lifecycle

```python
async def cog_load(self):
    asyncio.ensure_future(self.check_role_expiry())
```

The background loop is started immediately when the cog loads. It internally waits with `await self.bot.wait_until_ready()` before doing any guild work.
