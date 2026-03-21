# 04 — Task Management System

## Overview

The task cog manages the full lifecycle of work assignments between employees. Key features:
- Multi-assignee task creation via Discord modals
- Private thread per task (inside the assigner's command channel)
- 5-field task detail modal with optional deadline
- Per-assignee pending channels and assigner dashboard channels
- Completion vectors to track individual progress
- Background engines for reminders, archiving, and cleanup

**File:** `cogs/task_cog.py` (single file, section-anchored for navigation)
**Database:** PostgreSQL via `Bots/db_managers/task_db_manager.py`

---

## Task Creation Flow

1. Assigner clicks **"Assign Task"** → `AssigneeSelect` (multi-user select, max 10 assignees)
   - Self-assignment and already-assigned users are rejected
2. `TaskDetailsModal` — **5 fields in one modal**:
   | Field | Required | Description |
   |---|---|---|
   | Priority | Yes | `High`, `Normal`, or `Low` |
   | Description | Yes | Task description text |
   | Note / Remark | No | Optional additional note |
   | Deadline Date | No | DD/MM/YYYY or DD.MM.YYYY or DD-MM-YYYY |
   | Deadline Time | No | HH:MM AM/PM or HH.MM AM/PM |

   Both deadline fields must be filled together or both left empty — one without the other is rejected.

3. On modal submit:
   - Deadline is validated: must be in the future (`dl_dt.replace(tzinfo=IST) <= now_ist()` → rejected)
   - Creates a **private thread** inside `COMMAND_CHANNEL_ID`:
     - Name: `task-{id} · {priority} Priority`
     - `invitable=False` (only explicitly added members can see it)
   - Posts main embed + assigner control view in the thread; stores `main_message_id`
   - Initializes per-assignee pending channels and assigner dashboard channel
   - Mid-submission crash recovery: task draft saved to `task_drafts` table; recoverable via `confirm_assign_` button

4. Each assignee is added to the private thread and receives a notification

---

## Assignee Acknowledgement Flow

After the task is posted:

1. Assignee presses **Acknowledge** button
2. **If task has a deadline:** `AcknowledgeDeadlineView` — assignee accepts the deadline or proposes a new one
3. **If no deadline:** `AssigneeDeadlineModal` — assignee sets their own deadline
4. Proposed deadline → accept/decline buttons sent to the task thread for the assigner

---

## Button Routing (`on_interaction`)

All Discord interactions route through a single `on_interaction` listener. `custom_id` prefix determines the handler:

| Prefix | Handler | Purpose |
|---|---|---|
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

---

## Task Lifecycle

```
1. Assign Task (AssigneeSelect)
         ↓
2. TaskDetailsModal (priority, description, note, deadline date, deadline time)
         ↓
3. Private thread created → main embed + assigner control view posted
         ↓
4. Per-assignee: pending channel + assigner dashboard initialized
         ↓
5. Assignee acknowledges (accepts/proposes deadline)
         ↓
6. Work in progress: assignee can mark done, flag blockers, reject, request update
         ↓
7. Assignee marks done → assigner reviews → approves or revises
         ↓
8. Assigner approves → mark_task_completed() → global_state = 'Finalized'
         ↓
9. Thread archived after 24 hours
```

---

## Completion Vector

Each task stores a `completion_vector` CSV string tracking per-assignee status:

```
assignees:     "Alice, Bob, Charlie"
assignee_ids:  "111, 222, 333"
completion_vector: "0, 1, 0"   ← Alice: pending, Bob: done, Charlie: pending
```

This allows the bot to track which specific assignees have completed their portion without separate rows.

---

## Sync Model

Every interaction that changes task state must call sync for the assigner **and all assignees**:

```python
await self.sync_user_pending_tasks(assigner_id, guild)
await self.sync_user_dashboard_tasks(assigner_id, guild)
for uid in assignee_ids:
    await self.sync_user_pending_tasks(uid, guild)
    await self.sync_user_dashboard_tasks(uid, guild)
```

- **`sync_user_pending_tasks`** — rebuilds the assignee's pending-tasks channel view
- **`sync_user_dashboard_tasks`** — rebuilds the assigner's dashboard channel view
- Both use `retrieve_tasks_for_sync()`: `WHERE global_state != 'Finalized'` (active + any non-final state)
- The reminder engine uses `retrieve_active_tasks_from_database()`: `WHERE global_state = 'Active'` only

---

## Deadline Validation

All 6 sites where `parse_datetime_flexible()` is called validate that the parsed datetime is in the future:

```python
try:
    dl_dt, deadline_val = parse_datetime_flexible(date_str, time_str)
except ValueError as e:
    await self._send_ephemeral(interaction, f"❌ {e}")
    return
if dl_dt.replace(tzinfo=IST) <= now_ist():
    await self._send_ephemeral(interaction, "❌ Deadline must be after the current date and time.")
    return
```

The 6 sites are: `TaskDetailsModal`, `AssigneeDeadlineModal`, `AcknowledgeDeadlineView` propose path, `approve_cb` in `handle_req_deadline`, `ModDeadlineModal`, and one additional deadline extension flow.

---

## Background Engines

All three engines are spawned in `on_ready` after discovery completes:

### `check_and_remove_invalid_tasks()` — Hourly Cleanup
- Scans all task records and verifies the corresponding Discord private thread still exists
- Removes orphaned records for threads that were manually deleted

### `task_reminder_engine()` — Hourly DM Reminders
- Fetches all Active tasks (`retrieve_active_tasks_from_database()`)
- DMs assignees whose tasks are pending or overdue
- Rate limit: one DM per second

### `task_archive_cleanup_engine()` — Archive and Delete
- Finds Finalized tasks that have been finalized for 24+ hours
- Archives the task thread: `chan.edit(archived=True, locked=True)` — never `chan.delete()`
- Updates DB records

---

## Private Threads

Task threads are **private threads** (`discord.ChannelType.private_thread`):
- Created inside `COMMAND_CHANNEL_ID` (the task-assigner channel)
- `invitable=False` — only the bot can add members; assignees cannot invite others
- Do **not** count against the Discord 500-channel limit
- Closure: `chan.edit(archived=True, locked=True)` — never delete the thread

---

## Activity Log

Each task has an `activity_log` JSON column recording all state transitions:

```json
[
  {"timestamp": "2026-03-17T10:00:00", "action": "assigned", "by": "Alice"},
  {"timestamp": "2026-03-17T10:05:00", "action": "acknowledged", "by": "Bob"},
  {"timestamp": "2026-03-17T14:30:00", "action": "marked_done", "by": "Bob"}
]
```

This is the audit trail for all task events.

---

## Notification Queue

Assignments made outside 9 AM–6 PM Mon–Fri IST are queued in the `notification_queue` table and delivered on the next active window instead of immediately.

---

## Task DB Key Functions

```python
db.create_task(...)                          # INSERT task record → returns task_id
db.retrieve_task(task_id)                    # Fetch single task by ID
db.retrieve_tasks_for_sync(user_id)          # WHERE global_state != 'Finalized'
db.retrieve_active_tasks_from_database()     # WHERE global_state = 'Active'
db.update_task_state(task_id, state)         # Change global_state
db.mark_task_completed(task_id)              # Set Finalized + completed_at
db.update_completion_vector(task_id, vector) # Update per-assignee progress
db.append_activity_log(task_id, entry)       # Append to JSON log
db.store_task_draft(modal_data)              # Save draft for crash recovery
db.get_task_draft(draft_id)                  # Retrieve crash-recovery draft
```
