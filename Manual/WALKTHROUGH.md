# WALKTHROUGH — Implementation History

This document chronicles every significant change made to the Concord Unified Engine across the engineering sessions, in chronological order.

---

## Phase 1 — Server Discovery System

**Goal:** Replace all hardcoded Discord IDs with a self-updating database mirror of the server's structure.

### What was built

**`Bots/db_managers/discovery_db_manager.py`** (new file)
- SQLite database `discovery.db` with four tables: `categories`, `channels`, `roles`, `members`
- Async queue pattern (`db_queue`, `db_worker`, `db_execute`) to serialise all SQLite writes safely with discord.py's asyncio loop
- `upsert_*` and `delete_*` functions for every entity
- Synchronous query helpers: `get_channel_id_by_name`, `get_role_id_by_name`, `get_member_roles`, `get_members_with_role`, `is_on_leave`, `has_submitted_dar`

**`cogs/discovery_cog.py`** (new file)
- `on_ready` full sweep: categories → channels → roles → members (with role list)
- Real-time event listeners for every create/update/delete event on channels, roles, and members
- `on_member_update` detects role changes and syncs the `roles` JSON column

**`main.py`**
- Added `cogs.discovery_cog` to the `setup_hook` cog list

### Schema migration — `member_roles` → `roles` column

An earlier iteration used a separate `member_roles` junction table. This was replaced with a JSON array column `roles TEXT DEFAULT '[]'` directly on the `members` table for simplicity. The migration code drops the `member_roles` table if it still exists and runs `ALTER TABLE members ADD COLUMN roles ...` safely if the column is absent.

---

## Phase 2 — Dynamic Leave Configuration

**Goal:** `leave_cog.py` was using hardcoded Discord IDs. Switch to dynamic lookup from `discovery.db`.

### Changes in `cogs/leave_cog.py`

- Created `resolve_leave_config()` called at cog load
- Channel name updated: `'submit-leave'` → `'leave-application'`
- Role name updated: `'Employee'` → `'emp'`
- All channel/role globals now resolved via `discovery.get_channel_id_by_name()` / `discovery.get_role_id_by_name()` with hardcoded fallbacks
- Fixed typo: loop variable `_DIRECT_SECOND_APPROVAL_ROLES` → `_DIRECT_SECOND_APPROVAL_ROLE_NAMES`

---

## Phase 3 — Correcting the Approval Workflow

**Goal:** The bot had a 3-stage workflow (HOD → HR → PA). The correct workflow is 2-stage (HOD → HR), with PA receiving a notification-only embed on HR rejection.

### Changes in `LeaveApprovalView.handle_approval`

- **Stage `'second'` (HR) is now the final approver** — calls `db.confirm_leave_acceptance()` and marks leave as fully approved
- **Removed** the incorrect third-stage send to PA for approval
- **HR rejection path** now:
  1. Calls `db.deny_leave()`
  2. Updates user DM
  3. Sends a **notification-only** embed (no view, no buttons) to `leave-pa`

### Changes in `DeclineReasonModal.on_submit`

- Correctly formats the PA notification embed for HR rejections
- PA embed is plain (no interactive elements)

---

## Phase 4 — Fixing "Already Responded" Error

**Goal:** Clicking any approval button caused `InteractionAlreadyResponded`.

### Root cause

`interaction_check` was calling `handle_approval()` **and** the button's `callback` was also calling `handle_approval()` — double dispatch.

### Fix in `LeaveApprovalView`

- **Removed** all dispatch logic from `interaction_check` — it now only returns `True` (validation pass-through)
- `_ensure_buttons_attached()` binds the correct `accept_callback` / `decline_callback` to each button
- `handle_approval()` now starts with `await interaction.response.defer(ephemeral=True)` to claim the interaction token immediately
- All response calls changed from `response.send_message` → `followup.send` (since the interaction is already deferred)

---

## Phase 5 — Cancellation Logic and DM Updates

**Goal:** Implement two distinct cancellation paths and ensure DMs are always up to date.

### Problem: DM ID was being lost between stages

When `handle_approval` built `new_footer` for stage 1 → 2 and stage 2 → final, `DM ID` was not carried forward from the old footer. This caused `update_persistent_dm` to silently bail out because `"DM ID: "` wasn't in `footer_text`.

**Fix:** In both transitions, the existing footer is read and `DM ID` is explicitly extracted and appended to `new_footer`.

### `DMLeaveActionView` — corrected button logic

| Stage | Before | After |
|---|---|---|
| `first` | Cancel Leave | Cancel Leave ✓ |
| `second` | Request Withdraw (wrong!) | Cancel Leave ✓ |
| `final` (approved) | Cancel Leave (wrong!) | Request Cancellation ✓ |
| `final` (declined) | *(various)* | no buttons ✓ |

### `update_persistent_dm` — rewritten

- Added a warning log when `DM ID` is missing (previously silent)
- Status labels dict: `first` → "Pending HOD Approval", `second` → "Pending HR Approval", `final` → `status_msg`
- Improved embed layout with inline fields and a spacer
- Button logic: `first`/`second` → `DMLeaveActionView(stage)`, `final` + green → `DMLeaveActionView('final')`, otherwise `None`

---

## Phase 6 — Post-Approval Cancellation Request

**Goal:** After HR approval, user's "Request Cancellation" button was not notifying the HR channel.

### Root cause

`request_withdraw` tried to parse `Channel ID` from the final-stage footer, but the final footer format is:
```
Stage: final | User ID: ... | Nickname: ... | Message ID: ... | DM ID: ...
```
No `Channel ID` field — so the parse grabbed the wrong value and silently failed.

### Fix

- `request_withdraw` now sends a **new message** directly to `APPROVAL_CHANNELS['hr']` using the known constant
- Added `CancellationRequestView` class:
  - **Approve Cancellation** → withdraws leave, reduces balance, updates original HR approval card (red colour, "❌ Cancelled by HR" status), notifies user via DM, deletes the cancellation request card
  - **Reject Cancellation** → reverts DB to `'Accepted'`, notifies user via DM, deletes the cancellation request card

### New DB function
`revert_cancellation_request(nickname, leave_id)` — sets `leave_status = 'Accepted'` when HR rejects a cancellation request.

---

## Phase 7 — Richer Cancellation Embed

**Goal:** The cancellation request embed in HR channel only showed Leave ID and Member name. It should show full details.

### New DB function
`get_leave_full_details(nickname, leave_id)` — returns all columns of a leave row as a `dict`, regardless of status.

### Updated `request_withdraw` embed
Now includes:
- Leave ID, Member (inline row)
- Leave Type, Dates (`from → to`), Days Off (inline row)
- Reason (full width)

---

## Phase 8 — Removing "Withdraw Leave" from Command Channel

**Goal:** The `leave-application` channel had a "Withdraw Leave" button that used a modal to accept a leave ID for withdrawal. This is now superseded by the DM-based cancellation flow.

### Changes

- Removed `withdraw_leave_button` (FormID5) from `LeaveApplicationView`
- Removed the corresponding "Withdraw Leave" embed field from the channel description embed

---

## Phase 9 — Ephemeral Message Auto-Delete

**Goal:** All ephemeral messages should disappear after 10 seconds.

### Problem

`interaction.followup.send(delete_after=N)` is not supported by `Webhook.send()` (raises `TypeError`). `interaction.response.send_message(delete_after=N)` works for non-deferred interactions.

### Solution

Added `_send_ephemeral(interaction, content, delay=10)` at module level:

```python
async def _send_ephemeral(interaction, content, delay=10):
    msg = await interaction.followup.send(content, ephemeral=True)
    async def _del():
        await asyncio.sleep(delay)
        try:
            await interaction.followup.delete_message(msg.id)
        except Exception:
            pass
    asyncio.create_task(_del())
```

**20 `followup.send(..., ephemeral=True)` call sites** across `leave_cog.py` replaced with `await _send_ephemeral(interaction, "...")`.

`response.send_message` calls retain `delete_after=10` which works natively.

---

## Phase 10 — Cancellation Card Auto-Delete

**Goal:** The cancellation request card in the HR channel should be deleted once HR acts on it (since the original approval card is already updated).

### Changes in `CancellationRequestView`

- Both `approve` and `reject` buttons now call `await interaction.message.delete()` after processing
- A brief ephemeral confirmation is sent to the HR member via `_send_ephemeral` before deletion
- Added `_auto_delete_ephemeral(interaction, delay=10)` static method for deleting the ephemeral confirmation response via `interaction.delete_original_response()`

---

## Summary of New Files Created

| File | Purpose |
|---|---|
| `Bots/db_managers/discovery_db_manager.py` | New — discovery DB access layer |
| `cogs/discovery_cog.py` | New — server structure sync cog |
| `Manual/README.md` | New — this manual's index |
| `Manual/01_architecture.md` | New — system architecture overview |
| `Manual/02_discovery.md` | New — discovery system deep-dive |
| `Manual/03_leave.md` | New — leave system deep-dive |
| `Manual/05_DAR.md` | New — DAR cog documentation |
| `Manual/06_databases.md` | New — full database reference |
| `Manual/07_configuration.md` | New — configuration and setup guide |
| `Manual/WALKTHROUGH.md` | New — this document |

## Summary of Modified Files

| File | Key Changes |
|---|---|
| `main.py` | Added `cogs.discovery_cog` to setup_hook |
| `cogs/leave_cog.py` | Dynamic config, 2-stage workflow, DM updates, cancellation paths, ephemeral helper |
| `Bots/db_managers/leave_db_manager.py` | Added `get_leave_full_details`, `revert_cancellation_request` |
