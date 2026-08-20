# TREZO — Daily Profit Lock System

## Origin
This feature comes directly from the founder's own trading rule:

> "If I'm winning, keep winning but save the minimum I want to make for the average daily."

This is a **disciplined trader's rule.** Professional traders pay thousands of dollars to learn this principle. The founder articulated it naturally. Trezo enforces it automatically.

---

## 1. THE CORE CONCEPT

### What It Does
When Trezo generates profit equal to or above the user's daily target, the target amount is automatically transferred to a locked vault that the bot cannot access. The remaining profit continues working for the rest of the day.

### Why It Works
Three powerful effects happen simultaneously:

1. **Real money preserved** — Every winning day produces actual saved dollars, not paper gains
2. **Prevents giveback** — The most common retail trading mistake is winning early and losing it all back. The lock prevents this mathematically
3. **Psychological compounding** — Watching your "saved" balance grow creates positive reinforcement that strengthens discipline over time

---

## 2. USER CONFIGURATION

### Daily Target Setting
User sets their daily save target. Suggested defaults:

| Account Size | Suggested Daily Target |
|--------------|------------------------|
| $500-$1,000 | $5-$10/day |
| $1,000-$2,500 | $10-$25/day |
| $2,500-$5,000 | $25-$50/day |
| $5,000-$10,000 | $50-$100/day |
| $10,000+ | 1% of account/day |

### Adjustable Parameters
```
DAILY PROFIT LOCK SETTINGS
─────────────────────────────────────────────
Enabled: [Yes/No]
Daily Target: $______ (user-defined)
Save Source: [All gains / Realized gains only]
Save Trigger: [At target / At 110% of target / End of day]
Withdrawal Schedule: [Weekly / Monthly / Manual]
─────────────────────────────────────────────
```

---

## 3. HOW IT WORKS — EXAMPLE SCENARIOS

### Scenario 1: Winning Day
**Setup:** User's daily target is $50. Account starts day at $5,000.

```
9:30 AM   Account: $5,000 | Saved: $0
10:15 AM  Trade closes: +$23 | Account: $5,023 | Saved: $0
11:30 AM  Trade closes: +$31 | Account: $5,054 | Saved: $0
                                      ↑
                            $54 profit reached target!
                                      ↓
11:30 AM  AUTO-LOCK TRIGGERED
          $50 moved to Saved Vault
          Account: $5,004 | Saved: $50
2:00 PM   Trade closes: +$18 | Account: $5,022 | Saved: $50
4:00 PM   Day ends: Account: $5,022 | Saved: $50
```

**Result:** User KEEPS $50 no matter what happens tomorrow. Remaining $22 stays in trading account.

### Scenario 2: Winning Then Losing Day
**Setup:** Same $50 target.

```
9:30 AM   Account: $5,000 | Saved: $0
10:30 AM  Trade closes: +$60 | Account: $5,060 | Saved: $0
                                       ↓
10:30 AM  AUTO-LOCK TRIGGERED
          $50 moved to Saved Vault
          Account: $5,010 | Saved: $50
12:00 PM  Trade closes: -$40 | Account: $4,970 | Saved: $50
2:00 PM   Trade closes: -$25 | Account: $4,945 | Saved: $50
4:00 PM   Day ends: Account: $4,945 | Saved: $50
```

**Result:** User had a losing day in their trading account but still POCKETED $50. Without the lock, they'd be down $5 for the day.

### Scenario 3: Losing Day From Start
**Setup:** Same $50 target.

```
9:30 AM   Account: $5,000 | Saved: $0
10:00 AM  Trade closes: -$20 | Account: $4,980 | Saved: $0
11:00 AM  Trade closes: -$30 | Account: $4,950 | Saved: $0
                                       ↓
                            NO LOCK TRIGGERED
                            (No profit to lock)
12:00 PM  Daily loss limit approaching
1:00 PM   Risk Manager halts new trades
4:00 PM   Day ends: Account: $4,950 | Saved: $0
```

**Result:** Standard risk management kicks in. No lock happens because there was no profit.

### Scenario 4: Crushing It Day
**Setup:** Same $50 target.

```
9:30 AM   Account: $5,000 | Saved: $0
10:00 AM  Trade closes: +$80 | Account: $5,080 | Saved: $0
                                       ↓
10:00 AM  AUTO-LOCK TRIGGERED
          $50 moved to Saved Vault
          Account: $5,030 | Saved: $50
11:00 AM  Trade closes: +$45 | Account: $5,075 | Saved: $50
1:00 PM   Trade closes: +$30 | Account: $5,105 | Saved: $50
3:00 PM   Trade closes: +$22 | Account: $5,127 | Saved: $50
4:00 PM   Day ends: Account: $5,127 | Saved: $50
```

**Result:** User KEEPS $50 guaranteed + has $127 in account gains. The lock didn't cap profits, it just secured the floor.

---

## 4. ADVANCED CONFIGURATION

### Save Source Options

**Option A: All Gains (Default)**
- Both realized and unrealized gains count toward target
- More aggressive locking
- Catches profits before they vanish

**Option B: Realized Gains Only**
- Only completed (closed) trades count
- More conservative
- Aligns with actual cash position

### Save Trigger Options

**Option A: At Target (Default)**
- Lock triggers exactly when target reached
- Example: $50 target → lock at $50 profit

**Option B: At 110% of Target**
- Wait for slight buffer above target
- Example: $50 target → lock at $55 profit
- Reduces lock triggers on small movements

**Option C: End of Day**
- Calculate total daily P&L at market close
- Lock daily target if achieved
- Most conservative approach

### Withdrawal Schedule Options

**Weekly Withdrawal**
- Every Friday at 4:00 PM, total saved amount transfers to user's bank
- Trezo retains nothing
- Best for active income earners

**Monthly Withdrawal**
- Last business day of month
- Larger lump sum
- Better for bigger goals

**Manual Withdrawal**
- User requests transfer anytime
- Funds remain in Trezo vault until requested
- Maximum flexibility

---

## 5. DATABASE IMPLEMENTATION

### Tables Required

**daily_lock_vault**
```sql
CREATE TABLE daily_lock_vault (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    date DATE NOT NULL,
    amount_locked DECIMAL(10,2) NOT NULL,
    source TEXT,  -- which trades contributed
    locked_at TIMESTAMP DEFAULT NOW(),
    unlocked_at TIMESTAMP,
    withdrawn BOOLEAN DEFAULT FALSE,
    withdrawn_at TIMESTAMP,
    withdrawn_to TEXT  -- bank account reference
);

CREATE INDEX idx_lock_vault_user_date ON daily_lock_vault(user_id, date);
```

**lock_settings**
```sql
CREATE TABLE lock_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id),
    enabled BOOLEAN DEFAULT TRUE,
    daily_target DECIMAL(10,2) NOT NULL,
    save_source TEXT DEFAULT 'all_gains',
    save_trigger TEXT DEFAULT 'at_target',
    withdrawal_schedule TEXT DEFAULT 'weekly',
    last_withdrawal TIMESTAMP,
    total_saved_ytd DECIMAL(10,2) DEFAULT 0,
    total_withdrawn_ytd DECIMAL(10,2) DEFAULT 0
);
```

---

## 6. BACKEND IMPLEMENTATION

### Python Implementation

```python
# backend/app/agents/risk_manager.py

class DailyProfitLockManager:
    def __init__(self, user_id):
        self.user_id = user_id
        self.settings = self.load_settings()
    
    def load_settings(self):
        """Load user's lock settings from DB"""
        return db.query(LockSettings).filter_by(user_id=self.user_id).first()
    
    async def check_and_lock(self):
        """Called after every closed trade"""
        if not self.settings.enabled:
            return
        
        today_pnl = await self.calculate_today_pnl()
        already_locked = await self.get_today_locked()
        
        # Don't double-lock
        if already_locked >= self.settings.daily_target:
            return
        
        # Check if trigger met
        if self.settings.save_trigger == 'at_target':
            trigger = self.settings.daily_target
        elif self.settings.save_trigger == 'at_110_percent':
            trigger = self.settings.daily_target * 1.10
        else:
            # end_of_day handled separately
            return
        
        if today_pnl >= trigger:
            await self.execute_lock()
    
    async def execute_lock(self):
        """Move daily target to vault"""
        amount_to_lock = self.settings.daily_target - await self.get_today_locked()
        
        # Create vault entry
        vault_entry = DailyLockVault(
            user_id=self.user_id,
            date=datetime.utcnow().date(),
            amount_locked=amount_to_lock,
            source='auto_lock_at_target',
            locked_at=datetime.utcnow()
        )
        db.session.add(vault_entry)
        
        # Update YTD total
        self.settings.total_saved_ytd += amount_to_lock
        db.session.commit()
        
        # Notify user
        await self.notify_user(amount_to_lock)
        
        # Log event
        log_event({
            'type': 'profit_lock_triggered',
            'user_id': self.user_id,
            'amount': amount_to_lock,
            'timestamp': datetime.utcnow()
        })
    
    async def notify_user(self, amount):
        """Send positive reinforcement notification"""
        await send_notification(
            self.user_id,
            f"🎯 Daily target hit! ${amount:.2f} locked in your vault.",
            celebratory=True
        )
    
    async def calculate_today_pnl(self):
        """Calculate today's realized P&L"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
        
        if self.settings.save_source == 'all_gains':
            # Include unrealized
            unrealized = await self.get_unrealized_pnl()
            realized = await self.get_realized_pnl_today()
            return realized + unrealized
        else:
            # Realized only
            return await self.get_realized_pnl_today()
    
    async def end_of_day_check(self):
        """Run at 4:00 PM ET if trigger is 'end_of_day'"""
        if self.settings.save_trigger != 'end_of_day':
            return
        
        today_pnl = await self.calculate_today_pnl()
        if today_pnl >= self.settings.daily_target:
            await self.execute_lock()
```

### Scheduled Job

```python
# backend/app/scheduler.py

@scheduler.scheduled_job('cron', hour=16, minute=0, timezone='America/New_York')
async def end_of_day_lock_check():
    """Run end-of-day lock checks for all users"""
    users = db.query(User).filter(User.lock_settings.enabled == True).all()
    for user in users:
        manager = DailyProfitLockManager(user.id)
        await manager.end_of_day_check()

@scheduler.scheduled_job('cron', day_of_week='fri', hour=16, minute=30, timezone='America/New_York')
async def weekly_withdrawal_processing():
    """Process weekly withdrawals every Friday"""
    users = db.query(User).filter(
        User.lock_settings.withdrawal_schedule == 'weekly'
    ).all()
    for user in users:
        await process_withdrawal(user.id)
```

---

## 7. FRONTEND IMPLEMENTATION

### Dashboard Widget

```jsx
// frontend/src/components/Dashboard/DailyLockWidget.jsx

function DailyLockWidget({ userId }) {
  const { data, isLoading } = useDailyLockData(userId);
  
  if (isLoading) return <LoadingSpinner />;
  
  const progress = (data.todayPnl / data.dailyTarget) * 100;
  const isLocked = data.todayLocked > 0;
  
  return (
    <div className="daily-lock-widget">
      <div className="header">
        <h3>Daily Profit Lock</h3>
        <span className="target">Target: ${data.dailyTarget}</span>
      </div>
      
      <div className="progress-bar">
        <div 
          className="progress-fill"
          style={{ width: `${Math.min(100, progress)}%` }}
        />
        <span className="progress-text">
          ${data.todayPnl.toFixed(2)} / ${data.dailyTarget}
        </span>
      </div>
      
      {isLocked && (
        <div className="locked-notice">
          <CheckIcon /> ${data.todayLocked} secured in your vault
        </div>
      )}
      
      <div className="vault-summary">
        <div className="stat">
          <label>This Week</label>
          <value>${data.weekTotal.toFixed(2)}</value>
        </div>
        <div className="stat">
          <label>This Month</label>
          <value>${data.monthTotal.toFixed(2)}</value>
        </div>
        <div className="stat">
          <label>YTD</label>
          <value>${data.ytdTotal.toFixed(2)}</value>
        </div>
      </div>
      
      <button className="settings-btn" onClick={openSettings}>
        Adjust Target
      </button>
    </div>
  );
}
```

---

## 8. POSITIVE REINFORCEMENT PSYCHOLOGY

### Celebration Triggers

When a daily target is hit:
- Subtle celebration animation in UI
- Notification: "🎯 Daily target hit!"
- Progress bar fills with celebratory color
- Saved amount displayed prominently

### Streak Tracking
```
🔥 5-day target streak!
🔥 30-day target streak!
🔥 100-day target streak!
🔥 1-year target streak!
```

Streaks build psychological momentum without encouraging reckless trading (because the system enforces the lock regardless).

### Milestone Recognition
- First $100 saved
- First $1,000 saved
- First $10,000 saved
- First $100,000 saved
- $1,000,000 vault milestone (the dream)

---

## 9. ANTI-GAMING PROTECTIONS

### Preventing User Manipulation
Some users might try to "trick" the lock. Trezo prevents this:

**Manipulation attempt:** User raises daily target after profitable day
- **Protection:** Settings changes only apply to NEXT day
- Today's lock uses today's setting

**Manipulation attempt:** User disables lock mid-day after profits
- **Protection:** Lock cannot be disabled while position is open
- Disabling requires 24-hour cooldown

**Manipulation attempt:** User withdraws from vault to fund losing trades
- **Protection:** Vault funds cannot be transferred back to trading account
- Only outbound to bank account

---

## 10. ANALYTICS & REPORTING

### Monthly Report
```
TREZO DAILY PROFIT LOCK — May 2026 Report
─────────────────────────────────────────────
Days target met: 18 / 22 trading days (82%)
Days target missed: 4
Total saved: $1,234.56
Average daily save: $68.59
Best streak: 12 days
Withdrawal received: $1,000 on May 31

Year-to-date: $8,742.30 saved
─────────────────────────────────────────────
```

### Behavior Analysis
Trezo tracks correlation between:
- Lock hits and overall account growth
- Lock streaks and trading discipline
- Withdrawal patterns and lifestyle changes

This data helps users understand their progress AND helps Strategy Discovery Agent calibrate optimal targets.

---

## 11. PHILOSOPHICAL FRAMING

The Daily Profit Lock isn't just a feature. It's an embodiment of the Woven Basket philosophy:

**"Like Maternal Love — not everything will be ok, but the love tries to keep whatever it is protecting safe, layer after layer, giving its all."**

The Lock is maternal protection in code form. It says:
- "Today was good. Let me save some of that for you."
- "Tomorrow might be hard. You have something saved."
- "Discipline is hard. Let me hold the line when you can't."

Every locked dollar is a love letter from past-you to future-you.

---

*The user's rule. Trezo's enforcement. Real wealth, one lock at a time.*
