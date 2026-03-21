# 07 — Configuration Reference

## Environment Variables

Stored in `.env` at the project root. Never commit this file. `.env.example` is the safe template.

```ini
# Required
BOT_TOKEN=your_discord_bot_token_here
DB_HOST=localhost
DB_PORT=5432
DB_NAME=concord
DB_USER=concord_user
DB_PASSWORD=your_password_here

# Optional
DB_POOL_MIN=2          # Minimum pool connections (default: 2)
DB_POOL_MAX=20         # Maximum pool connections (default: 20)
DB_POOL_TIMEOUT=30     # Pool acquire timeout in seconds (default: 30)
ARCHIVE_PATH=          # Path for task archives (defaults to Archives/)
DISABLE_TUI=           # Set to "true" for plain stdout logging (no Rich TUI)
```

---

## Channel and Role ID Resolution

Concord resolves almost all channel and role IDs **dynamically** from the discovery DB at startup, so renaming channels in Discord is reflected without code changes.

### How it works — `resolve_leave_config()` in `cogs/leave_config.py`

```python
async def resolve_leave_config():
    global SUBMIT_CHANNEL_ID, EMP_ROLE_ID, APPROVAL_CHANNELS, ...

    ch = await db_execute(lambda: discovery.get_channel_id_by_name('leave-application'))
    if ch:
        SUBMIT_CHANNEL_ID = ch

    role = await db_execute(lambda: discovery.get_role_id_by_name('emp'))
    if role:
        EMP_ROLE_ID = role

    hr = await db_execute(lambda: discovery.get_channel_id_by_name('leave-hr'))
    if hr:
        APPROVAL_CHANNELS['hr'] = hr
    ...
```

### How to access resolved globals

Always import the config module as a whole and access values via `cfg.*`:

```python
import cogs.leave_config as cfg

# Correct — reads the live post-resolution value
channel = bot.get_channel(cfg.SUBMIT_CHANNEL_ID)
role = guild.get_role(cfg.EMP_ROLE_ID)

# WRONG — captures the stale pre-resolution value at import time
from cogs.leave_config import SUBMIT_CHANNEL_ID  # do not do this for integers
```

Dict globals like `APPROVAL_CHANNELS` are mutated in-place and are safe to import directly. Integer globals (`SUBMIT_CHANNEL_ID`, `EMP_ROLE_ID`) are rebound by `resolve_leave_config()`, so they must be accessed via `cfg.SUBMIT_CHANNEL_ID` after startup.

### Fallback behaviour

If the discovery DB doesn't have a matching record (e.g. first run before any discovery sweep), hardcoded fallback IDs from `Bots/config.py` are used. Update those if the server IDs ever change and you need an emergency bypass.

---

## Discord Server Requirements

The following channels must exist in the server:

| Channel Name | Purpose |
|---|---|
| `leave-application` | Employees submit leave requests here |
| `leave-hr` | HR receives and acts on leave approvals |
| `leave-pa` | PA receives notification-only embeds on HR denial |
| `leave-administration` | HOD channel for administration staff |
| `leave-cad` | HOD channel for CAD staff |
| `leave-architects` | HOD channel for architects |
| `leave-site` | HOD channel for site staff |
| `daily-activity-report` | Employees post their DARs here (channel = submission interface) |

The following roles must exist:

| Role Name | Purpose |
|---|---|
| `emp` | Assigned to all employees (used to differentiate from bots) |
| `leave-administration` | Identifies an employee's department (admin) |
| `leave-cad` | Identifies an employee's department (CAD) |
| `leave-architects` | Identifies an employee's department (architects) |
| `leave-site` | Identifies an employee's department (site) |
| `On Leave` | Assigned when leave is active (used by DAR exclusion) |
| `D.A.R Submitted` | Assigned when a DAR is submitted |

---

## Bot Permissions Required

| Permission | Reason |
|---|---|
| Read Messages / View Channels | Listen for events |
| Send Messages | Post embeds and DMs |
| Manage Roles | Assign/remove DAR Submitted and On Leave roles |
| Read Message History | Fetch existing messages for editing |
| Embed Links | Required to send embeds |
| Create Private Threads | Task threads are private threads |
| Manage Threads | Archive and lock finalized task threads |

---

## `run.sh` — Launch Script

```bash
#!/bin/bash
cd "$(dirname "$0")"          # Ensures relative paths work from any location
source .venv/bin/activate     # Activates the virtual environment
python3 main.py               # Starts the bot
```

> **Why `cd "$(dirname "$0")`?** All database paths in the code are computed relative to the script files. Running from a different directory would break those paths. This one-liner normalises the working directory to the project root.

Use `DISABLE_TUI=true python3 main.py` to skip the Rich TUI and get plain stdout logging.

---

## Requirements

Key dependencies:

```
discord.py
python-dotenv
rich
psycopg[binary]
psycopg-pool
openpyxl
```

Install with:
```bash
pip install -r requirements.txt
```

Python 3.11+ is required. The project has been tested on Python 3.14.

---

## Pre-Start Checklist

1. `Logs/` directory must exist (log rotation writes here)
2. `Archives/` directory must exist (task archive writes here)
3. PostgreSQL server must be running and accessible with the credentials in `.env`
4. Bot token must be valid and the bot must be added to the server with required permissions
5. All required channels and roles (listed above) must exist in the Discord server
