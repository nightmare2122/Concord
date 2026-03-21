# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

ALWAYS before making any change: search the web for the newest documentation. Only implement if you are 100% sure it will work.

## Commands

```bash
# Start the bot (recommended — handles venv, deps, and process cleanup)
bash run.sh

# Start without the Rich TUI dashboard (plain stdout logging)
DISABLE_TUI=true python3 main.py

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_leave_bot.py

# Run a single test by name
pytest tests/test_db.py::test_function_name -v
```

Tests mock out the DB worker queue via `conftest.py` so they run without a live PostgreSQL connection.

## Architecture

### Entry Point & Bot Lifecycle

`main.py` boots a single `ConcordBot` (subclass of `commands.Bot`) with four cogs loaded in order:
1. `cogs/discovery_cog.py` — **must load first**; sets `bot.discovery_complete` (an `asyncio.Event`)
2. `cogs/task_cog.py`
3. `cogs/leave_cog.py`
4. `cogs/dar_cog.py`

The discovery cog's `on_ready` handler does a full guild sweep (categories → channels → roles → members → scheduled events), spawns `_sweep_messages()` in the background, then calls `bot.discovery_complete.set()`. Every other cog's `on_ready` **must** `await bot.discovery_complete.wait()` before calling its `resolve_*_config()` function.

`main.py` also contains a circuit breaker: 10 unhandled errors within 5 minutes triggers a pause to prevent error cascades.

### Database Layer

All DB access goes through `Bots/db_managers/base_db.py`:
- **`ConnectionPool`** (`psycopg-pool`) — global pool, initialized lazily on first `get_conn()` call.
- **`get_conn()` / `put_conn(conn)`** — manual acquire/release. Always use the `try/finally` pattern:
  ```python
  conn = get_conn()
  try:
      with conn.cursor() as cur:
          cur.execute(...)
      conn.commit()
  finally:
      put_conn(conn)
  ```
  **Never** use `with get_conn() as conn:` — psycopg's context manager manages the transaction but does **not** return the connection to the pool, causing a leak.
- **`db_execute(func)`** — schedules a sync function on the serial `db_queue` and awaits its result. Every sync DB closure must be dispatched via this before being called from async code.
- **`db_worker()`** — long-running coroutine consuming `db_queue`. Each cog creates its own `db_worker()` task in `cog_load`; all share the single `db_queue` from `base_db`.

Each domain has its own manager (`discovery_db_manager.py`, `leave_db_manager.py`, `task_db_manager.py`) that imports from `base_db` and owns its schema init + CRUD functions.

### Database Schemas

**`tasks`** — core task record:
- `channel_id BIGINT UNIQUE` — private Discord thread ID for this task
- `assignees TEXT` / `assignee_ids TEXT` — CSV strings (`"User1, User2"` / `"1234, 5678"`)
- `completion_vector TEXT` — CSV binary flags per assignee (`"0,1,0"`)
- `activity_log TEXT` — JSON audit trail of all state transitions
- `priority TEXT` — `"High"`, `"Normal"`, `"Low"`
- `checklist TEXT` — task notes/remarks
- `global_state TEXT` — `"Active"` or `"Finalized"`
- `created_at TIMESTAMP DEFAULT NOW()` / `completed_at TIMESTAMP`

**`pending_tasks_channels` / `assigner_dashboard_channels`** — per-user Discord channel + CSV task/message IDs for views.

**`notification_queue`** — tasks assigned outside 9 AM–6 PM (Mon–Fri IST) are queued here and delivered on the next active window.

**`task_drafts`** — `modal_data JSONB` for mid-submission crash recovery.

**`users`** (leave) — `total_sick_leave`, `total_casual_leave`, `total_c_off`, `off_duty_hours`, `last_leave_taken`.

**`leaves`** — `leave_type` (`FULL DAY`/`HALF DAY`/`OFF DUTY`), `leave_reason` (`sick`/`casual`/`c. off`), `leave_status` (see lifecycle below), `reason_for_decline`, `footer_text`, `cancelled_by`, `cancellation_reason`.

**`holidays`** — `date TEXT PRIMARY KEY` in `DD-MM-YYYY` format.

**Discovery DB** — `categories`, `channels`, `roles`, `members` (with `roles JSONB[]`), `messages`, `scheduled_events`. Members' `roles` field is a JSONB array; queried via `member_has_role()` and `get_members_with_role()`.

### Dynamic ID Resolution

Hardcoded Discord IDs in `Bots/config.py` are **fallbacks only**. At startup each cog calls `resolve_*_config()` which queries the discovery DB by channel/role **name** and overwrites module-level globals. This makes the bot resilient to server ID changes after DB resets.

The discovery DB in-memory cache (`_cache_channels`, `_cache_roles`, `_cache_categories`) is the hot path — `get_channel_id_by_name()` etc. hit it before touching PostgreSQL.

### Leave Module File Layout

The leave system is split across three files to separate concerns:

| File | Contents |
|------|----------|
| `cogs/leave_config.py` | Config globals (`APPROVAL_CHANNELS`, `DEPARTMENT_ROLES`, etc.), fallback IDs, `resolve_leave_config()` |
| `cogs/leave_views.py` | All Discord UI classes (views, modals), embed helpers, routing functions |
| `cogs/leave_cog.py` | `LeaveCog` only — lifecycle (`on_ready`, `on_member_update`), `export_leave` command |

**Import pattern:** both `leave_views.py` and `leave_cog.py` import the config module as a whole:
```python
import cogs.leave_config as cfg
```
Then access live values via `cfg.APPROVAL_CHANNELS`, `cfg.EMP_ROLE_ID`, etc. This ensures values updated by `resolve_leave_config()` are always visible — dicts are mutated in-place, integers are read via module attribute access after startup.

### Interaction Handling in `task_cog.py`

All Discord interactions route through a single `on_interaction` listener. Button `custom_id` prefixes determine the handler:

| Prefix | Handler | Purpose |
|--------|---------|---------|
| `dash_mod_` | `handle_dash_mod` | Assigner edits task details |
| `dash_cancel_` | `handle_dash_cancel` | Assigner cancels task |
| `dash_done_` | `handle_dash_done` | Assignee marks pending review |
| `dash_block_` | `handle_dash_block` | Assignee flags blocker |
| `dash_reject_` | `handle_dash_reject` | Assignee rejects task (opens `RejectionModal`) |
| `dash_part_` | `handle_dash_part` | Assignee marks partial completion |
| `dash_upd_` | `handle_dash_upd` | Assignee requests update |
| `dash_resolve_block_` | `handle_resolve_block` | Resolve a blocker |
| `dash_req_deadline_` | `handle_req_deadline` | Request deadline extension |
| `approve_deadline_` / `deny_deadline_` | rehydrated | Assigner accepts/declines proposed deadline |
| `ack_{task_id}` | rehydrated | Assignee acknowledges task |
| `manage_` | `get_assigner_control_view` | Assigner control panel |
| `approve_panel_` / `revise_panel_` | rehydrated | Assigner approves/revises submission |
| `mark_complete_` | rehydrated | Final task closure |

**Zombie rehydration:** On button press after bot restart, task state is fetched from DB by task ID extracted from `custom_id`, the correct view is reconstructed, and the button's callback is invoked directly.

### Task Lifecycle

1. "Assign Task" → `AssigneeSelect` (multi-user, max 10; self and already-assigned users are rejected)
2. `TaskDetailsModal` — **5 fields in one modal**: priority, description, note/remark (optional), deadline date (optional), deadline time (optional). Both deadline fields must be filled together or both left empty.
3. Creates a **private thread** inside the task-assigner channel (`COMMAND_CHANNEL_ID`), posts main embed + assigner control view, stores `main_message_id`. Thread is named `task-{id} · {priority} Priority` with `invitable=False`.
4. Initializes per-assignee pending channels and assigner dashboard.
5. `completion_vector` tracks each assignee's completion status (CSV `"0,1"`).
6. Assignee acknowledges → if existing deadline: `AcknowledgeDeadlineView` (accept or propose new deadline); if no deadline: `AssigneeDeadlineModal`.
7. Proposed deadline → accept/decline buttons sent to task thread for assigner.
8. Final closure: assigner approves → `mark_task_completed()` → `global_state = 'Finalized'` → archived after 24h.

**Deadline validation:** All deadline inputs (6 sites) validate that the parsed datetime is in the future using `dl_dt.replace(tzinfo=IST) <= now_ist()`.

**Background engines** (spawned in `on_ready`):
- `check_and_remove_invalid_tasks()` — hourly cleanup of orphaned task channels
- `task_reminder_engine()` — hourly DM reminders for pending/overdue tasks
- `task_archive_cleanup_engine()` — archives finalized tasks after 24h, deletes thread

**Sync:** Every interaction that changes task state must call `sync_user_pending_tasks` and `sync_user_dashboard_tasks` for the assigner and all assignees. Dashboard and pending channels show all tasks with `global_state != 'Finalized'` (uses `retrieve_tasks_for_sync()`). The reminder engine uses `retrieve_active_tasks_from_database()` (Active only).

### Leave Workflow

**Application entry:** `LeaveApplicationView` in `#leave-application` — Full Day / Half Day / Off Duty modals, plus Leave Details button (shows balance).

**Routing:** Based on the applicant's Discord role, the leave embed is posted to the correct department channel. Roles with `_DIRECT_SECOND_APPROVAL_ROLE_NAMES` (Heads, Project Coordinator) skip department HOD and go straight to `#leave-hr`.

**Leave status lifecycle:**
```
PENDING → (HOD Accept) → PENDING HR → (HR Accept) → ACCEPTED
PENDING → (HOD/HR Decline) → DECLINED
ACCEPTED → (User: Request Cancellation) → Withdrawal Requested → (HR Approve) → Withdrawn by HR  [balance refunded]
ACCEPTED → (User: Request Cancellation) → Withdrawal Requested → (HR Reject) → ACCEPTED
PENDING → (User: Direct Cancel) → Withdrawn  [no balance change]
```

**Persistent DM footer encoding:** Every leave approval message encodes state in its footer text:
```
Stage: {stage} | User ID: {uid} | Nickname: {nick} | Channel ID: {ch_id} | Message ID: {msg_id} | DM ID: {dm_id}
```
This is parsed during withdrawal/cancellation flows to locate and update the original HR approval message across Discord channels.

**Balance tracking:** `confirm_leave_acceptance()` increments `total_sick_leave`/`total_casual_leave`/`total_c_off` and sets `last_leave_taken`. `refund_leave_balance()` decrements on withdrawal. Balances are shown in the approval embed and in the Leave Details button.

**Approval notes:** Both HOD and HR acceptance open `ApproveWithNotesModal` (optional notes field). Notes are stored in `leave_details['approval_notes']` and shown in the embed.

**Persistent view registration:** `LeaveApplicationView` is registered globally with `self.bot.add_view(LeaveApplicationView())` in `on_ready` before any message editing. `LeaveApprovalView` instances are registered per-message with `self.bot.add_view(view, message_id=message_id)`.

### DAR (Daily Activity Report) Cog

- Employees post their DARs directly in channel ID `1281200069416321096` (`#daily-activity-report`)
- On each post: bot assigns "DAR Submitted" role to the author (if not already held), then creates a public discussion thread on the message (`auto_archive_duration=1440`)
- **11:00 AM IST daily:** Removes "DAR Submitted" role from all members, logs submitted members to `Database/DAR exports/dar_submissions_{YYYY-MM-DD}.txt`
- **7–10 PM IST (Mon–Sat), hourly:** DMs members without "DAR Submitted" role (skips PA, On Leave, DAR Exclude roles)
- No modal, no submission button, no `ensure_dar_ui` — the channel itself is the submission interface

### Timezone

All timestamps use **IST (UTC+5:30)**. Import `IST` or `now_ist()` from `Bots/utils/timezone.py` — never use `datetime.now()` without a timezone argument. Discord embed `timestamp` fields must use `datetime.now(datetime.timezone.utc)` (Discord requires UTC).

### Flexible Date/Time Parsing

`Bots/utils/timezone.py` provides three parsers used everywhere deadlines or leave dates are entered:

| Function | Accepts | Returns canonical |
|----------|---------|-------------------|
| `parse_datetime_flexible(date_str, time_str)` | DD/MM/YYYY, DD.MM.YY, DD-MM-YYYY etc. + HH:MM AM/PM or HH.MM AM/PM | `DD/MM/YYYY HH:MM AM/PM` |
| `parse_date_flexible(date_str)` | same date formats | `DD-MM-YYYY` |
| `parse_time_flexible(time_str)` | HH:MM AM/PM or HH.MM AM/PM | `HH:MM AM/PM` |

All three raise `ValueError` with a user-friendly message on failure.

### Error Code Convention

Errors follow `[ERR-XXX-NNN]` pattern logged to "Concord" logger and shown in ephemeral messages:
- `[ERR-TSK-*]` — task cog
- `[ERR-LV-*]` — leave cog
- `[ERR-DAR-*]` — DAR cog
- `[ERR-DSC-*]` — discovery cog
- `[ERR-COR-*]` — main.py / core

Always use `logger = logging.getLogger("Concord")` — never `logging.info()` directly.

### Non-Obvious Patterns

- **CSV string storage:** Assignees, assignee IDs, completion vectors, reminders, and acknowledged_by lists are stored as CSV strings (not JSON/arrays) in task DB columns. Split with `", "` on retrieval.
- **Activity log:** JSON log in `tasks.activity_log` records all state transitions for audit.
- **Ephemeral auto-delete:** Ephemeral messages are auto-deleted after 10s via `interaction.followup.delete_message(msg.id)`.
- **Rate limiting:** DAR DMs — 1/sec; discovery member sweep — 0.1s; role removal — 0.5s per member.
- **Task drafts:** In-flight modal submissions saved to `task_drafts` table; recoverable via `confirm_assign_` button if bot crashes mid-flow.
- **Notification queue:** Assignments outside 9 AM–6 PM Mon–Fri IST queue in `notification_queue`; delivered on next active window.
- **Private threads:** Task threads use `discord.ChannelType.private_thread` with `invitable=False` inside `COMMAND_CHANNEL_ID`. Archive/lock via `chan.edit(archived=True, locked=True)` — never `chan.delete()`.
- **Config module import:** `leave_views.py` and `leave_cog.py` both import `import cogs.leave_config as cfg` to access live globals. Never do `from cogs.leave_config import EMP_ROLE_ID` for rebindable integers — use `cfg.EMP_ROLE_ID`.

### Environment

Copy `.env.example` to `.env` and set: `BOT_TOKEN`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`. Optional: `DB_POOL_MIN` (default 2), `DB_POOL_MAX` (default 20), `DB_POOL_TIMEOUT` (default 30), `ARCHIVE_PATH`, `DISABLE_TUI`.

`Logs/` and `Archives/` directories must exist before starting. Logs rotate at `Logs/concord_runtime.log` (10 MB × 5 backups).
