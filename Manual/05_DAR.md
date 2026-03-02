# 05 — DAR (Daily Activity Report) System

## Purpose

The DAR cog automates enforcement of daily activity reporting:
- Detects DAR submissions (embed posted in the DAR channel) and assigns a role
- Removes the role each day at 11:00 AM (reset)
- Sends DM reminders to members who haven't submitted during evening hours
- Logs daily DAR compliance to flat files

**File:** `cogs/dar_cog.py`

---

## Key Constants

| Constant | Description |
|---|---|
| `DAR_SUBMITTED_ROLE_ID` | Role assigned when a member submits a DAR |
| `ON_LEAVE_ROLE_ID` | Members on leave are excluded from reminders |
| `PA_ROLE_ID` | PA (Principal Architect) is excluded from reminders |
| `DAR_CHANNEL_ID` | Channel where DAR embeds are posted |
| `DAR_EXCLUDE_ROLE_ID` | Any additional role exempt from DAR reminders |
| `DAR_LOG_DIRECTORY` | `Database/DAR exports/` — where daily logs are saved |

---

## Background Loop — `check_role_expiry()`

Runs every 60 seconds after `bot.wait_until_ready()`. Checks the current time:

### 11:00 AM — Role Removal
- Calls `handle_role_removal()`
- Iterates all members across all guilds
- Removes the `DAR Submitted` role from anyone who has it
- Calls `log_dar_submissions()` to write a dated `.txt` file

### 7 PM – 10 PM (Mon–Sat) — Reminder DMs
- Checks `_last_reminder_hour` to avoid sending duplicate reminders within the same hour
- Calls `send_dar_reminders()` which DMs every member who:
  - Is not the bot itself
  - Does NOT have `DAR_SUBMITTED_ROLE_ID`
  - Does NOT have `PA_ROLE_ID`
  - Does NOT have `ON_LEAVE_ROLE_ID`
  - Does NOT have `DAR_EXCLUDE_ROLE_ID`
- 1-second sleep between each DM to avoid rate limits

---

## DAR Detection — `on_message`

Fires for every message in the server.

1. Filters to only `DAR_CHANNEL_ID`
2. Checks the message has embeds
3. Reads `embed.author.name` to identify who posted
4. Looks up the member by display name with `guild.get_member_named()`
5. Assigns `DAR_SUBMITTED_ROLE_ID` to the member

> **Assumption:** The embed's `author.name` must exactly match the member's display name.

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

These are created daily when the 11:00 AM reset runs. They record which members had the DAR Submitted role (i.e. who DID submit) at the time of reset.

---

## Cog Lifecycle

```python
async def cog_load(self):
    asyncio.ensure_future(self.check_role_expiry())
```

The background loop is started immediately when the cog loads, without waiting for `on_ready`. It internally waits with `await self.bot.wait_until_ready()`.
