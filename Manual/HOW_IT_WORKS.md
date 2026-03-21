# How Concord Works

A plain English walkthrough of the entire bot — no code, no jargon.

---

## The Big Picture

Concord is a Discord bot that handles three things for your workplace:
1. **Leave** — employees apply for leave, managers approve it in stages
2. **Tasks** — managers assign work, employees track and complete it
3. **DAR** — employees log their daily activity, bot tracks and reminds

It also has a **Discovery** system that runs first and makes everything else work.

---

## 1. Discovery — How the Bot Learns Your Server

When Concord starts up, the very first thing it does is read your entire Discord server and memorise it — every channel, every role, every member. It stores all of this in a database.

This matters because the rest of the bot needs to know things like "which channel is the leave application channel?" and "what is the ID of the HR role?". Instead of those being hardcoded, Concord looks them up by name from what it discovered.

**Why this is useful:** If you rename `#leave-application` to `#apply-for-leave`, Concord doesn't break. Next time it restarts, it discovers the new name and carries on. The hardcoded IDs in the code are just emergency fallbacks if the discovery hasn't run yet.

The discovery sweep happens every time the bot starts. While it's running, every other part of the bot waits. Once it's done, it signals "I'm ready" and everything else kicks off.

---

## 2. Leave — From Application to Approval

### Applying for Leave

There is a single channel called `#leave-application`. In it, the bot posts a message with four buttons:
- **Full Day** — for a standard full day (or range of days)
- **Half Day** — for a morning or afternoon half-day
- **Off Duty** — for a few hours off
- **Leave Details** — shows you your remaining leave balance without applying for anything

Clicking any of the first three opens a small form (called a modal) where you fill in the date, reason, and any other relevant details. When you submit the form, the bot creates a leave record in the database.

### Stage 1 — HOD Approval

The bot looks at what department role you have (e.g. `leave-cad`, `leave-architects`) and posts your leave request in the corresponding HOD channel. The HOD sees an embed with your details and two buttons: **Accept** and **Decline**.

- If the HOD **accepts**, they can optionally type a note, and the request moves to HR.
- If the HOD **declines**, they must provide a reason. The request ends here.

Some senior roles (like Heads and Project Coordinators) skip the HOD stage entirely and go straight to HR.

### Stage 2 — HR Approval

HR sees the same kind of embed in `#leave-hr` and again has Accept / Decline buttons.

- If HR **accepts**, the leave is fully approved. Your leave balance is updated.
- If HR **declines**, the request ends. A notification-only embed (no buttons) is also sent to `#leave-pa` to keep PA informed.

### Your DM — Always Kept in the Loop

From the moment you apply, you receive a Direct Message from the bot showing your leave status. This DM **updates live** at every stage — pending HOD, pending HR, approved, declined. The DM also has a button so you can cancel your leave at any point.

The way the bot finds your original DM after a restart is by storing a reference to it inside the embed footer (a hidden line of text). When something changes, the bot reads that footer, finds your DM, and edits it.

### Cancelling Leave

There are two paths depending on whether the leave has been fully approved yet:

- **Not yet approved (pending):** You click "Cancel Leave" in your DM. It cancels immediately. No HR involvement needed.
- **Already approved:** You click "Request Cancellation". This sends a request to HR with Approve / Reject buttons. If HR approves the cancellation, your leave balance is refunded. If HR rejects it, you stay on leave.

### After a Bot Restart

When the bot restarts, it goes through recent messages in all the leave channels and reattaches the buttons. Without this step, the buttons would show up but clicking them would do nothing. The bot reads the footer of each embed to reconstruct the correct state before reattaching.

---

## 3. Tasks — From Assignment to Completion

### Creating a Task

A manager goes to the task command channel and clicks "Assign Task". They first select who the task is for (up to 10 people). Then a form pops up with five fields:
- Priority (High / Normal / Low)
- Description
- Note or remark (optional)
- Deadline date (optional)
- Deadline time (optional)

Both deadline fields must be filled in together — you can't set a date without a time or vice versa. The bot also rejects deadlines in the past.

### The Task Thread

Once the form is submitted, the bot creates a **private thread** in the command channel. Only the assigner and the assignees can see it. The thread is named `task-{number} · {priority} Priority`.

Inside the thread, the bot posts the task details and a set of buttons for the assigner to manage the task. Separately, each assignee gets their own private channel where they see all their pending tasks, and the assigner has a dashboard channel showing all tasks they've created.

### Assignee Actions

After seeing the task, each assignee must **acknowledge** it. At this point:
- If the task has a deadline, they can accept it or propose a new one.
- If there's no deadline, they set their own.

If they propose a new deadline, the assigner gets buttons in the task thread to accept or reject the proposal.

Once acknowledged, the assignee has buttons available:
- **Mark Done** — submits for assigner review
- **Flag Blocker** — signals something is blocking progress
- **Reject Task** — rejects the task with a reason
- **Partial Completion** — marks partial progress
- **Request Update** — asks the assigner for more info
- **Request Deadline Extension** — proposes a new deadline

### Completion

When an assignee marks the task done, the assigner gets buttons to **Approve** or **Revise**. If revised, the assignee gets it back to work on more. Once the assigner approves, the task is marked as **Finalized**.

24 hours after finalization, the bot archives and locks the private thread automatically. It's never deleted — just locked and archived.

### Background Work

Three background jobs run continuously:
- **Reminders:** Every hour, the bot checks for tasks that are pending or overdue and DMs the relevant assignees.
- **Cleanup:** Every hour, the bot checks if any task threads were manually deleted and cleans up the orphaned database records.
- **Archive:** Continuously checks for tasks finalized more than 24 hours ago and archives their threads.

### Tracking Multiple Assignees

If a task has three assignees, the bot tracks each one separately using a simple list of 0s and 1s — e.g. `0, 1, 0` means the first and third haven't finished but the second has. The task isn't finalized until the assigner explicitly closes it.

### After a Bot Restart

Task buttons work after restarts too. When someone clicks a button, the bot reads the task ID from the button's identifier, fetches the task from the database, rebuilds the correct view, and processes the click. This is called "zombie rehydration".

---

## 4. DAR — Daily Activity Reports

### Submitting

Employees post their daily activity report directly in `#daily-activity-report` — they just type a message and send it. There is no form, no button to click.

The bot listens for messages in that channel. When it sees one, it:
1. Gives the employee a `DAR Submitted` role (visible next to their name)
2. Creates a discussion thread on that message so others can comment

### Daily Reset — 11:00 AM

Every day at 11:00 AM IST, the bot removes the `DAR Submitted` role from everyone. Before it does, it saves a text file listing everyone who had submitted that day.

This gives the slate a fresh start. People who submitted show as not submitted again, ready for the next day's report.

### Evening Reminders — 7 PM to 10 PM

Between 7 PM and 10 PM (Monday to Saturday), once per hour, the bot checks who still doesn't have the `DAR Submitted` role and sends them a DM reminder.

Excluded from reminders:
- The bot itself
- Members with the `PA` role
- Members with the `On Leave` role
- Members with the `DAR Exclude` role

---

## How Everything Starts Up

When you run the bot:

1. The bot loads all its modules
2. The **Discovery** module runs first and sweeps the entire server
3. It signals "done" — all other modules were waiting for this signal
4. Each module resolves its channels and roles from what discovery found
5. The leave module reattaches buttons to all existing leave messages
6. The task module starts its background reminder, cleanup, and archive jobs
7. The DAR module starts its hourly role check loop

If the bot has been down and comes back up, it picks up exactly where it left off — pending leave applications still have buttons, task threads still respond to clicks, everything restores automatically.
