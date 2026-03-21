# Concord Unified Engine — Manual

> **Version:** 2.0 · **Last updated:** 2026-03-17

This folder is the single source of truth for how Concord works.
Each file covers one area of the system in detail.

---

## 📂 Table of Contents

| File | What it covers |
|---|---|
| [01_architecture.md](./01_architecture.md) | System overview, startup sequence, cog loading, directory layout |
| [02_discovery.md](./02_discovery.md) | Server discovery cog + discovery DB schema |
| [03_leave.md](./03_leave.md) | Full leave management system — 3-file layout, workflow, views, DB |
| [04_tasks.md](./04_tasks.md) | Task management — lifecycle, private threads, modals, sync engines |
| [05_DAR.md](./05_DAR.md) | Daily Activity Report cog — channel-based posting, reminders |
| [06_databases.md](./06_databases.md) | All databases, schemas, and access patterns |
| [07_configuration.md](./07_configuration.md) | Environment variables, channel/role resolution, PostgreSQL setup |
| [WALKTHROUGH.md](./WALKTHROUGH.md) | Chronological log of all implemented changes |

---

## Quick-start Reading Order

1. **New contributor** → Start with `01_architecture.md` for the big picture, then read the module you'll work on.
2. **Debugging leave issues** → `03_leave.md` has every stage, view, and DB call mapped out.
3. **Debugging task issues** → `04_tasks.md` has the full lifecycle, sync model, and button routing.
4. **Understanding the database** → `06_databases.md` has every table and every function.
5. **Understanding what changed and why** → `WALKTHROUGH.md`.
