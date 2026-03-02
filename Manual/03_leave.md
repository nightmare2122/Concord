# 03 — Leave Management System

## Overview

The leave system is the most complex module in Concord. It handles:
- Leave submission via Discord modals
- A **2-stage approval workflow** (HOD → HR)
- Real-time DM status updates to the applicant
- Two distinct cancellation paths (direct cancel vs. cancellation request)
- Persistent views that survive bot restarts

**File:** `cogs/leave_cog.py`  
**Database:** `Database/leave.db` (via `Bots/db_managers/leave_db_manager.py`)

---

## Channel & Role Configuration

At startup, `resolve_leave_config()` populates these globals using `discovery.db`:

| Global | Resolved From | Fallback |
|---|---|---|
| `SUBMIT_CHANNEL_ID` | channel name `leave-application` | hardcoded ID |
| `EMP_ROLE_ID` | role name `emp` | hardcoded ID |
| `APPROVAL_CHANNELS['first'][role]` | role → channel mapping | hardcoded IDs |
| `APPROVAL_CHANNELS['hr']` | channel name `leave-hr` | hardcoded ID |
| `APPROVAL_CHANNELS['pa']` | channel name `leave-pa` | hardcoded ID |

**First-approval channels by employee role:**

| Employee Role | Approval Channel |
|---|---|
| leave-administration | leave-administration |
| leave-cad | leave-cad |
| leave-architects | leave-architects |
| leave-site | leave-site |

---

## Leave Submission Flow

### Entry Points
Three modal types are available as buttons in `leave-application`:

| Button | Modal | Leave Type |
|---|---|---|
| Full Day | `FullDayLeaveModal` | Date range, reason |
| Half Day | `HalfDayLeaveModal` | Date, session (FN/AN), reason |
| Off Duty | `OffDutyLeaveModal` | Date, hours, cumulated hours |

### On Modal Submit
1. Modal `on_submit` validates all fields
2. `db.submit_leave_application()` inserts the leave record → returns `leave_id`
3. `send_leave_application_to_approval_channel()` is called:
   - Determines the correct first-approval channel from the employee's roles
   - Creates `LeaveApprovalView` (Approve / Decline buttons)
   - Posts embed to approval channel
   - **Stores footer metadata** on the embed: `Stage | User ID | Nickname | Channel ID | Message ID`
   - Sends a **DM** to the applicant with `DMLeaveActionView` (Cancel Leave button)
   - **Appends `DM ID` to the footer** so the DM can be found later

---

## Approval Workflow

```
┌─────────────────────┐
│  leave-application  │  Employee submits via modal
└────────┬────────────┘
         │ Status: "Pending First Approval"
         ▼
┌─────────────────────┐
│  HOD Channel        │  LeaveApprovalView (Accept / Decline)
│  (role-specific)    │
└────────┬────────────┘
    Accept │     │ Decline
           │     └──→ db.deny_leave() · DM updated · Process ends
           │ Status: "Pending Second Approval"
           ▼
┌─────────────────────┐
│  leave-hr           │  LeaveApprovalView (Accept / Decline)
└────────┬────────────┘
    Accept │     │ Decline
           │     └──→ db.deny_leave() · DM updated
           │          Notification embed (no buttons) → leave-pa
           │ Status: "Accepted"
           ▼
      Leave fully approved · DM updated · Stage: final
```

### `LeaveApprovalView`

Class: `LeaveApprovalView(View)`

| Attribute | Description |
|---|---|
| `user_id` | Applicant's Discord user ID |
| `leave_details` | Dict of leave fields |
| `current_stage` | `'first'` or `'second'` |
| `nickname` | Applicant display name |

**Button setup** is done in `_ensure_buttons_attached(interaction)` which runs DB checks and dynamically binds callbacks. This is needed because `View` classes are reconstructed on bot restart without state.

### `handle_approval(interaction, approved: bool)`

The central approval dispatcher:

1. `await interaction.response.defer(ephemeral=True)` — prevents "already responded" errors
2. Reads the embed footer to extract `Stage | User ID | Nickname | Channel ID | Message ID`
3. If `approved=True`:
   - **Stage `'first'`** → sends leave to HR (`leave-hr`), updates embed, calls `update_persistent_dm` with `next_stage='second'`
   - **Stage `'second'`** → finalises leave (`db.confirm_leave_acceptance`), updates embed, calls `update_persistent_dm` with `next_stage='final'`
4. If `approved=False` → opens `DeclineReasonModal`

### `DeclineReasonModal`

Collects a decline reason text. On submit:
- Calls `db.deny_leave()`
- Updates the approval channel embed to show the reason and disabled buttons
- Calls `update_persistent_dm` with a declined status
- If stage was `'second'` (HR decline): sends a **notification-only embed** to `leave-pa` (no interactive buttons)

---

## Footer Metadata Format

The embed footer is used as a portable state carrier. It is always in this form:

```
Stage: {stage} | User ID: {uid} | Nickname: {nick} | Channel ID: {ch_id} | Message ID: {msg_id} | DM ID: {dm_id}
```

- `Channel ID` is present for `first` and `second` stages (points to the approval channel)
- `DM ID` is appended once the DM is sent
- When advancing from stage 1 → 2, the `DM ID` is explicitly read from the old footer and written into the new footer to preserve it

---

## DM Update System

### `update_persistent_dm(bot, user_id, leave_details, next_stage, footer_text, status_msg, color)`

1. Parses `DM ID` from `footer_text`
2. `bot.fetch_user(user_id)` → creates DM channel if needed
3. `dm_channel.fetch_message(dm_id)` → retrieves the original DM
4. Builds a new embed with status label from `stage_labels` dict
5. Attaches the appropriate `DMLeaveActionView` based on `next_stage`
6. Edits the DM message in-place

### `DMLeaveActionView` — Button Logic

| Stage | Button Shown | Action |
|---|---|---|
| `first` | Cancel Leave (red) | Direct cancellation |
| `second` | Cancel Leave (red) | Direct cancellation |
| `final` (green/approved) | Request Cancellation (grey) | Sends to HR for approval |
| `final` (red/declined or withdrawn) | *(no buttons)* | — |

---

## Cancellation System

### Path 1 — Direct Cancellation (stages `first` / `second`)

Triggered by: "Cancel Leave" button in the DM

1. `db.get_pending_leave_status()` — verifies leave is still pending
2. `db.withdraw_leave()` + `db.reduce_leave_balance()` + `db.update_last_leave_date_after_withdrawal()`
3. DM embed updated: "Cancelled", buttons disabled
4. Leave is immediately withdrawn, no HR involvement

### Path 2 — Cancellation Request (stage `final`)

Triggered by: "Request Cancellation" button in the DM

1. `db.request_withdraw_leave()` — sets status to `'Withdrawal Requested'`
2. DM updated: "⏳ Cancellation Requested — awaiting HR approval" (button disabled)
3. `get_leave_full_details()` fetches full leave row for enriched embed
4. New embed sent to `leave-hr` with `CancellationRequestView`:

```
📥 Cancellation Request
[nickname] has requested cancellation of an approved leave.

Leave ID  | Member   | (spacer)
Leave Type | Dates    | Days Off
Reason
```

### `CancellationRequestView` — HR Actions

| Button | Action |
|---|---|
| Approve Cancellation | Withdraws leave, reduces balance, updates original HR card, notifies user via DM, deletes this card |
| Reject Cancellation | Reverts DB to `'Accepted'`, notifies user via DM, deletes this card |

After either action, the **original HR approval card** (from when the leave was first approved) is also edited: colour turns red, status field set to "❌ Cancelled by HR".

---

## Ephemeral Message Handling

All ephemeral messages use `_send_ephemeral(interaction, content, delay=10)`:

```python
async def _send_ephemeral(interaction, content, delay=10):
    msg = await interaction.followup.send(content, ephemeral=True)
    # Schedule deletion using the only supported Discord API method
    asyncio.create_task(_delete_after_delay(msg.id, interaction, delay))
```

`response.send_message(ephemeral=True, delete_after=10)` is used for non-deferred interactions (e.g. validation errors).

> **Why not `followup.send(delete_after=N)`?** — `Webhook.send()` does not support `delete_after`. The only way to delete an ephemeral followup is `interaction.followup.delete_message(msg.id)`.

---

## Leave Database Functions (Key)

See `06_databases.md` for the full list. Frequently used:

```python
db.submit_leave_application(nickname, leave_details)   # INSERT → returns leave_id
db.confirm_leave_acceptance(...)                       # Marks as Accepted
db.deny_leave(nickname, leave_id)                      # Marks as Denied
db.withdraw_leave(nickname, leave_id)                  # Marks as Withdrawn
db.request_withdraw_leave(nickname, leave_id)          # Marks as Withdrawal Requested
db.revert_cancellation_request(nickname, leave_id)     # Reverts to Accepted
db.reduce_leave_balance(user_id, leave_reason, days)   # Deducts from balance
db.get_leave_full_details(nickname, leave_id)          # Full row as dict
db.get_footer_text(nickname, leave_id)                 # Reads stored footer string
db.update_footer_text(nickname, leave_id, footer)      # Writes new footer string
```
