# Concord Bot - Production Deployment Guide

## ⚠️ CRITICAL - READ BEFORE DEPLOYING

This guide covers the necessary steps to deploy Concord bot to a 50+ user production environment.

---

## 🔴 Pre-Deployment Checklist

### 1. Database Connection Pooling (CRITICAL)

**Status:** Partially Fixed - Manual steps required

**What was fixed:**
- ✅ `base_db.py` - Added connection pooling with `psycopg-pool`
- ✅ `discovery_db_manager.py` - Updated to return connections to pool
- ❌ `leave_db_manager.py` - **43 functions still need manual fixes**
- ❌ `task_db_manager.py` - **19 functions still need manual fixes**

**How to fix remaining files:**

Each function using `with get_conn() as conn:` needs to be updated:

```python
# BEFORE:
def _some_function():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("...")
        conn.commit()

# AFTER:
def _some_function():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("...")
        conn.commit()
    finally:
        put_conn(conn)
```

**Install dependency:**
```bash
pip install psycopg-pool
```

**Environment variables:**
```bash
# Add to .env
DB_POOL_MIN=2
DB_POOL_MAX=20
DB_POOL_TIMEOUT=30.0
```

### 2. Discord Rate Limiting (CRITICAL)

**Status:** Fixed

Changes made:
- ✅ `dar_cog.py` - Added rate limit protection (0.5s delay between role operations, 1s between DMs)
- ✅ `discovery_cog.py` - Added 0.1s delay between member fetches
- ✅ Error handling for HTTP 429 (rate limited)

### 3. Error Recovery & Circuit Breaker (CRITICAL)

**Status:** Fixed

Changes made:
- ✅ `main.py` - Added circuit breaker pattern to prevent error spam
- ✅ `main.py` - Added command error handling
- ✅ `main.py` - Added member caching for better performance

### 4. Log Rotation (HIGH)

**Status:** Fixed

Changes made:
- ✅ `main.py` - Replaced FileHandler with RotatingFileHandler (10MB per file, 5 backups)

---

## 📋 Deployment Steps

### Step 1: Environment Setup

```bash
# 1. Clone repository
git clone <repository-url>
ccd concord_test/Concord

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
# Note: psycopg-pool is now included in requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and fill in:
# - BOT_TOKEN (from Discord Developer Portal)
# - DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
# - DB_POOL_MIN=2, DB_POOL_MAX=20
```

### Step 2: Database Setup

```bash
# 1. Create PostgreSQL database
sudo -u postgres psql -c "CREATE DATABASE concord_db;"
sudo -u postgres psql -c "CREATE USER concord_user WITH PASSWORD 'your_secure_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE concord_db TO concord_user;"

# 2. Set appropriate connection limits in postgresql.conf
# max_connections = 200  # Increase from default 100 for 50+ users
```

### Step 3: Manual Code Fixes (CRITICAL)

Before deploying, you MUST manually fix the database functions:

1. Open `Bots/db_managers/leave_db_manager.py`
2. Find all 24 occurrences of `with get_conn() as conn:`
3. Replace each with the try/finally pattern shown above
4. Repeat for `Bots/db_managers/task_db_manager.py` (19 occurrences)

**Alternative:** Run `python3 Scripts/fix_db_connections.py` to see the count of issues.

### Step 4: Discord Bot Configuration

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application or use existing
3. Go to "Bot" section
4. Enable these **Privileged Intents**:
   - ✅ SERVER MEMBERS INTENT (required for member tracking)
   - ✅ MESSAGE CONTENT INTENT (required for message processing)
5. Copy the token to `.env`

### Step 5: Server Permissions

Ensure the bot has these permissions in your Discord server:

- Manage Roles
- Manage Channels  
- Read Messages
- Send Messages
- Create Private Threads
- Manage Threads
- Read Message History
- Mention Everyone
- Add Reactions

### Step 6: Start the Bot

```bash
# Using the run script
chmod +x run.sh
./run.sh

# Or manually
source .venv/bin/activate
python3 main.py
```

---

## 🔧 Post-Deployment Monitoring

### Health Check Commands

Run these commands in Discord to verify bot health:

```
!view_tasks    # Should respond with task list or "No pending tasks"
```

### Log Monitoring

Watch these log files:

```bash
# Real-time log monitoring
tail -f Logs/concord_runtime.log

# Check for errors
grep "ERR-" Logs/concord_runtime.log

# Check database pool status (customize as needed)
grep "DB\|pool\|connection" Logs/concord_runtime.log
```

### Key Metrics to Monitor

1. **Database Connections**
   - Check active connections: `SELECT count(*) FROM pg_stat_activity;`
   - Should stay below `DB_POOL_MAX` (default: 20)

2. **Discord API Rate Limits**
   - Watch for `429` errors in logs
   - Should see `[DAR] Rate limited` messages if hit

3. **Memory Usage**
   - Monitor with `top` or `htop`
   - Should be stable, not growing unbounded

4. **Circuit Breaker**
   - Watch for `[ERR-COR-099] Circuit breaker active!` 
   - Indicates too many errors - investigate immediately

---

## 🚨 Emergency Procedures

### Bot Not Responding

1. Check if process is running:
   ```bash
   ps aux | grep "python3 main.py"
   ```

2. Check logs for errors:
   ```bash
   tail -100 Logs/concord_runtime.log
   ```

3. Restart if needed:
   ```bash
   pkill -f "python3 main.py"
   ./run.sh
   ```

### Database Connection Errors

If you see `[ERR-DB-001]` errors:

1. Check PostgreSQL is running:
   ```bash
   sudo systemctl status postgresql
   ```

2. Check connection count:
   ```bash
   sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity;"
   ```

3. If connections are maxed out, restart PostgreSQL:
   ```bash
   sudo systemctl restart postgresql
   ```

### Rate Limiting Issues

If Discord rate limits are hit:

1. Check logs for `[DAR] Rate limited` messages
2. The bot will automatically back off
3. Consider increasing delays in:
   - `dar_cog.py` - `handle_role_removal()`
   - `dar_cog.py` - `send_dar_reminders()`

---

## 📊 Performance Tuning

### For 50-100 Users (Default Settings)

```bash
DB_POOL_MIN=2
DB_POOL_MAX=20
```

### For 100-500 Users

```bash
DB_POOL_MIN=5
DB_POOL_MAX=50
DB_POOL_TIMEOUT=60.0
```

### PostgreSQL Tuning

Edit `/etc/postgresql/14/main/postgresql.conf`:

```conf
max_connections = 200
shared_buffers = 256MB
work_mem = 4MB
maintenance_work_mem = 64MB
```

Restart PostgreSQL after changes:
```bash
sudo systemctl restart postgresql
```

---

## ✅ Final Deployment Verification

Before going live, verify:

- [ ] All database functions use connection pooling (43 in leave, 19 in task)
- [ ] `.env` file is configured with correct tokens and DB credentials
- [ ] PostgreSQL is running with increased `max_connections`
- [ ] Bot has all required Discord intents enabled
- [ ] Bot has correct permissions in the Discord server
- [ ] Log directory exists: `mkdir -p Logs`
- [ ] Archive directory exists: `mkdir -p Archives/Tasks`
- [ ] Database migrations/schema created (auto-on first run)
- [ ] Test with 2-3 users before full deployment
- [ ] Monitor logs for first hour of production

---

## 🆘 Support

If you encounter issues:

1. Check logs: `Logs/concord_runtime.log`
2. Look for error codes: `grep "ERR-" Logs/concord_runtime.log | tail -20`
3. Verify database: `psql -U concord_user -d concord_db -c "\dt"`
4. Check Discord status: https://discordstatus.com/

---

**Version:** 1.0  
**Last Updated:** 2026-03-14  
**Author:** Production Readiness Audit
