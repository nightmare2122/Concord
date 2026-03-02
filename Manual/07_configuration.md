# 07 — Configuration Reference

## Environment Variables

Stored in `.env` at the project root. Never commit this file.

```ini
BOT_TOKEN=your_discord_bot_token_here
```

`.env.example` is the safe template committed to version control.

---

## Channel and Role ID Resolution

Concord resolves almost all channel and role IDs **dynamically** from `discovery.db` at startup, so renaming channels in Discord is reflected without code changes.

### How it works — `resolve_leave_config()` in `leave_cog.py`

```python
def resolve_leave_config():
    import Bots.db_managers.discovery_db_manager as discovery

    # Submission channel
    SUBMIT_CHANNEL_ID = discovery.get_channel_id_by_name('leave-application') or FALLBACK

    # Employee role (all employees have this)
    EMP_ROLE_ID = discovery.get_role_id_by_name('emp') or FALLBACK

    # Approval channels
    APPROVAL_CHANNELS['hr'] = discovery.get_channel_id_by_name('leave-hr') or FALLBACK
    APPROVAL_CHANNELS['pa'] = discovery.get_channel_id_by_name('leave-pa') or FALLBACK

    # First-level channels by role name
    DIRECT_FIRST_APPROVAL_ROLE_NAMES = {
        'leave-administration': discovery.get_channel_id_by_name('leave-administration'),
        'leave-cad':            discovery.get_channel_id_by_name('leave-cad'),
        'leave-architects':     discovery.get_channel_id_by_name('leave-architects'),
        'leave-site':           discovery.get_channel_id_by_name('leave-site'),
    }
```

### Fallback behaviour

If `discovery.db` doesn't have a matching record (e.g. first run before any discovery sweep), the hardcoded IDs are used as fallbacks. These are defined as constants near the top of `leave_cog.py`. Update them if the server IDs ever change and you need an emergency bypass.

---

## Discord Server Requirements

For the bot to function correctly, the following channels must exist in the server:

| Channel Name | Purpose |
|---|---|
| `leave-application` | Employees submit leave requests here |
| `leave-hr` | HR receives and acts on leave approvals |
| `leave-pa` | PA receives notification-only embeds on HR denial |
| `leave-administration` | HOD channel for administration staff |
| `leave-cad` | HOD channel for CAD staff |
| `leave-architects` | HOD channel for architects |
| `leave-site` | HOD channel for site staff |

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
| Use Application Commands | Slash commands (future use) |

---

## `run.sh` — Launch Script

```bash
#!/bin/bash
cd "$(dirname "$0")"          # Ensures relative paths work from any location
source .venv/bin/activate     # Activates the virtual environment
python3 main.py               # Starts the bot
```

> **Why `cd "$(dirname "$0")`?** All database paths in the code are computed relative to the script files. Running from a different directory would break those paths. This one-liner normalises the working directory to the project root.

---

## Requirements

```
discord.py
python-dotenv
rich
```

Install with:
```bash
pip install -r requirements.txt
```

Python 3.11+ is recommended. The project has been tested on Python 3.14.
