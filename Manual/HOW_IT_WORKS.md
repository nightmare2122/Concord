# How Concord Works (A Simple Guide)

Welcome to Concord! This guide explains what the bot does and how it makes your workspace run smoothly without diving into the technical coding details.

## The Big Picture
Think of Concord as your **Automated Office Manager**. Instead of people having to manually track who is on leave, who finished what tasks, or who submitted their daily reports, Concord does it all quietly in the background right inside Discord. 

It never forgets, it never sleeps, and it keeps everything organized.

---

## 1. The "Brain" (Discovery System)
Before Concord can do any work, it needs to know what your Discord server looks like. We call this the **Discovery Brain**. 
Every time you rename a channel, add a new tag, or schedule a server event, Concord instantly memorizes it. 

**Why is this cool?**
Most bots break if you rename the `#leave-application` channel to `#apply-for-leave`. Concord is smart. It knows what channels are supposed to do, so if you change their names or move them around, Concord automatically adapts without anyone needing to reprogram it.

---

## 2. Daily Activity Reports (DAR)
Every business needs to know what got done today. Concord takes the friction out of DARs.

**How it works for you:**
- When you go to the `#daily-activity-report` channel, you will always see a permanent button that says **Submit DAR**.
- Clicking it opens a form right in Discord asking what you worked on.
- Once you submit, Concord instantly gives you a `DAR Submitted` badge/role next to your name so everyone knows you did your part.
- Behind the scenes, it neatens up your submission and files it cleanly away in the `#dar-reports` logs.

**What happens if you forget?**
If it gets late (between 7 PM and 10 PM) and you haven't submitted your form, Concord will gently slide into your Direct Messages to remind you.
And every morning at 11:00 AM, Concord clears the slate, removing everyone's `DAR Submitted` badges so the tracking can begin fresh for the new day.

---

## 3. The Leave Pipeline
Requesting time off shouldn't be a hassle of emails. Concord built a two-stage approval system.

**How it works for you:**
- You ask for leave. 
- It first goes to your Head of Department (HOD) for approval.
- Once the HOD approves, it routes to Human Resources (HR) for a final sign-off.
- **You are always kept in the loop:** Concord Direct Messages you at every single step. If your HOD approves it but HR declines it, your DM will update live showing exactly who said what and why.

---

## 4. Task Management
For assigning work, Concord gives you a command system to deal out tasks to employees.
It tracks the priority (High, Medium, Normal) and enforces deadlines. If an employee gets a task, they can interact with Concord to update the status (In Progress, Blocked, Completed) so management always has a bird's-eye view of what's getting done without having to micromanage.

---

## Summary
Concord's goal is to let you focus on your actual work. Let the bot handle the nagging, the tracking, and the paperwork.
