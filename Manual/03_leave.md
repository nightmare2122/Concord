# 03 — Leave Management System

## Overview

The leave system is the most complex module in Concord. It handles:
- Leave submission via Discord modals
- A **2-stage approval workflow** (HOD → HR)
- Real-time DM status updates to the applicant
- Two distinct cancellation paths (direct cancel vs. cancellation request)
- Persistent views that survive bot restarts

---

## File Layout (3-File Split)

The leave system is split across three files to separate concerns:

| File | Contents |
|---|---|
| `cogs/leave_config.py` | Config globals (`APPROVAL_CHANNELS`, `DEPARTMENT_ROLES`, etc.), fallback IDs, `resolve_leave_config()` |
| `cogs/leave_views.py` | All Discord UI classes (views, modals), embed helpers, routing functions |
| `cogs/leave_cog.py` | `LeaveCog` only — lifecycle (`on_ready`, `on_member_update`), `export_leave` command |

**Import pattern:** both `leave_views.py` and `leave_cog.py` import the config module as a whole:

```python
import cogs.leave_config as cfg
```

Then access live values via `cfg.APPROVAL_CHANNELS`, `cfg.EMP_ROLE_ID`, etc. This is required because `resolve_leave_config()` rebinds integer globals (like `SUBMIT_CHANNEL_ID`) — a `from X import` would capture the stale pre-resolution value.

**Database:** PostgreSQL via `Bots/db_managers/leave_db_manager.py`

---

## Channel & Role Configuration

At startup, `resolve_leave_config()` (in `leave_config.py`) populates these globals using the discovery DB:

| Global | Resolved From | Fallback |
|---|---|---|
| `SUBMIT_CHANNEL_ID` | channel name `leave-application` | hardcoded ID |
| `EMP_ROLE_ID` | role name `emp` | hardcoded ID |
| `APPROVAL_CHANNELS['first'][role]` | role → channel mapping | hardcoded IDs |
| `APPROVAL_CHANNELS['hr']` | channel name `leave-hr` | hardcoded ID |
| `APPROVAL_CHANNELS['pa']` | channel name `leave-pa` | hardcoded ID |

Roles in `_DIRECT_SECOND_APPROVAL_ROLE_NAMES` (Heads, Project Coordinator) skip the HOD stage and go straight to `leave-hr`.

---

## Leave Submission Flow

### Entry Points
Three modal types are available as buttons in `#leave-application`:

| Button | Modal | Leave Type |
|---|---|---|
| Full Day | `FullDayLeaveModal` | Date range, reason |
| Half Day | `HalfDayLeaveModal` | Date, session (FN/AN), reason |
| Off Duty | `OffDutyLeaveModal` | Date, hours, cumulated hours |

There is also a **Leave Details** button that shows the user's current leave balance without opening a modal.

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
         │ Status: PENDING
         ▼
┌─────────────────────┐
│  HOD Channel        │  LeaveApprovalView (Accept / Decline)
│  (role-specific)    │
└────────┬────────────┘
    Accept │     │ Decline
           │     └──→ db.deny_leave() · DM updated · DECLINED
           │ Status: PENDING HR
           ▼
┌─────────────────────┐
│  leave-hr           │  LeaveApprovalView (Accept / Decline)
└────────┬────────────┘
    Accept │     │ Decline
           │     └──→ db.deny_leave() · DM updated · DECLINED
           │          Notification embed (no buttons) → leave-pa
           │ Status: ACCEPTED
           ▼
      Leave fully approved · DM updated
```

### Leave Status Lifecycle

```
PENDING → (HOD Accept) → PENDING HR → (HR Accept) → ACCEPTED
PENDING → (HOD/HR Decline) → DECLINED
ACCEPTED → (User: Request Cancellation) → Withdrawal Requested → (HR Approve) → Withdrawn by HR  [balance refunded]
ACCEPTED → (User: Request Cancellation) → Withdrawal Requested → (HR Reject) → ACCEPTED
PENDING → (User: Direct Cancel) → Withdrawn  [no balance change]
```

### `LeaveApprovalView`

| Attribute | Description |
|---|---|
| `user_id` | Applicant's Discord user ID |
| `leave_details` | Dict of leave fields |
| `current_stage` | `'first'` or `'second'` |
| `nickname` | Applicant display name |

**Button setup** is done in `_ensure_buttons_attached(interaction)` which runs DB checks and dynamically binds callbacks. This is needed because View classes are reconstructed on bot restart without state.

**Persistent registration:** `LeaveApprovalView` instances are registered per-message via `self.bot.add_view(view, message_id=message_id)` in `on_ready`. `LeaveApplicationView` is registered globally with `self.bot.add_view(LeaveApplicationView())` — this is required for button interactions to work after bot restart.

### `handle_approval(interaction, approved: bool)`

1. `await interaction.response.defer(ephemeral=True)` — prevents "already responded" errors
2. Reads embed footer to extract `Stage | User ID | Nickname | Channel ID | Message ID`
3. If `approved=True`:
   - **Stage `'first'`** → sends leave to HR (`leave-hr`), updates embed, calls `update_persistent_dm` with `next_stage='second'`
   - **Stage `'second'`** → finalises leave (`db.confirm_leave_acceptance`), updates embed, calls `update_persistent_dm` with `next_stage='final'`
4. If `approved=False` → opens `DeclineReasonModal`

### `ApproveWithNotesModal`

Both HOD and HR acceptance open `ApproveWithNotesModal` (optional notes field). Notes are stored in `leave_details['approval_notes']` and shown in the embed.

---

## Footer Metadata Format

The embed footer is used as a portable state carrier:

```
Stage: {stage} | User ID: {uid} | Nickname: {nick} | Channel ID: {ch_id} | Message ID: {msg_id} | DM ID: {dm_id}
```

- `Channel ID` points to the approval channel for the current stage
- `DM ID` is appended once the DM is sent
- When advancing stage 1 → 2, the `DM ID` is explicitly carried forward into the new footer

---

## DM Update System

### `update_persistent_dm(bot, user_id, leave_details, next_stage, footer_text, status_msg, color)`

1. Parses `DM ID` from `footer_text`
2. `bot.fetch_user(user_id)` → creates DM channel if needed
3. `dm_channel.fetch_message(dm_id)` → retrieves original DM
4. Builds new embed with status label from `stage_labels` dict
5. Attaches appropriate `DMLeaveActionView` based on `next_stage`
6. Edits the DM message in-place

### `DMLeaveActionView` — Button Logic

| Stage | Button Shown | Action |
|---|---|---|
| `first` | Cancel Leave (red) | Direct cancellation |
| `second` | Cancel Leave (red) | Direct cancellation |
| `final` (approved) | Request Cancellation (grey) | Sends to HR for approval |
| `final` (declined/withdrawn) | *(no buttons)* | — |

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
3. New embed sent to `leave-hr` with `CancellationRequestView`:

### `CancellationRequestView` — HR Actions

| Button | Action |
|---|---|
| Approve Cancellation | Withdraws leave, reduces balance, updates original HR card, notifies user via DM, deletes this card |
| Reject Cancellation | Reverts DB to `'Accepted'`, notifies user via DM, deletes this card |

After either action, the **original HR approval card** is also edited: colour turns red/green as appropriate.

---

## Balance Tracking

`confirm_leave_acceptance()` increments `total_sick_leave` / `total_casual_leave` / `total_c_off` and sets `last_leave_taken`. `refund_leave_balance()` decrements on withdrawal. Balances are shown in the approval embed and in the Leave Details button.

---

## Ephemeral Message Handling

All ephemeral messages use `_send_ephemeral(interaction, content, delay=10)` (defined in `leave_views.py`). Ephemeral followup messages must be deleted via `interaction.followup.delete_message(msg.id)` — `Webhook.send()` does not support `delete_after`.

---

## Leave Database Functions (Key)

See `06_databases.md` for the full list. Frequently used:

```python
db.submit_leave_application(nickname, leave_details)   # INSERT → returns leave_id
db.confirm_leave_acceptance(...)                       # Marks as Accepted, increments balance
db.deny_leave(nickname, leave_id)                      # Marks as Denied
db.withdraw_leave(nickname, leave_id)                  # Marks as Withdrawn
db.request_withdraw_leave(nickname, leave_id)          # Marks as Withdrawal Requested
db.revert_cancellation_request(nickname, leave_id)     # Reverts to Accepted
db.reduce_leave_balance(user_id, leave_reason, days)   # Deducts from balance
db.get_leave_full_details(nickname, leave_id)          # Full row as dict
db.get_footer_text(nickname, leave_id)                 # Reads stored footer string
db.update_footer_text(nickname, leave_id, footer)      # Writes new footer string
```
