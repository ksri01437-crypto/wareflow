# WAREFLOW Quick Start Guide

## System Status ✅

```
Application: WAREFLOW Intelligent Warehouse Operations Platform
Version: 1.0 Production Ready
Status: Running on http://127.0.0.1:5000
Database: SQLite (wareflow.db) - Persistent
Port: 5000
Debug Mode: Enabled (Development)
```

---

## Key Features at a Glance

### 🎯 Smart Prioritization
- Orders scored 0-100 based on urgency, deadline, customer type
- Critical (80+), High (60-79), Medium (35-59), Low (<35)
- Real-time risk assessment (delivery delay, inventory shortage, waiting time)

### 📦 Inventory Management
- Smart allocation: highest-priority orders get available stock first
- Auto-detection of stock shortages → Creates exceptions
- Automatic reorder recommendations based on demand formula
- Real-time inventory health dashboard

### 🏭 Fulfillment Pipeline
```
NEW → ALLOCATED → PICKING → PACKING → QC → READY → DISPATCHING → DISPATCHED
```

### 🔍 Exception Management
All operational issues automatically detected:
- Stock shortages
- Picking delays (25%+ over target)
- Damaged items
- Wrong locations
- QC failures
- Dispatch delays (30+ min waiting)

### 📊 Real-time Analytics
- Fulfillment rate & efficiency metrics
- Inventory health status
- Bottleneck detection
- Performance trends
- Exception resolution tracking

---

## How to Use

### Starting the Application

```bash
cd c:\Users\ksri0\OneDrive\Desktop\smartwarehouse
python app.py
```

Access at: http://127.0.0.1:5000

### Creating an Order

1. Click **"+ New Order"** on Dashboard
2. Enter:
   - Customer Name: Any name
   - SKU: Select from dropdown (e.g., SKU-101)
   - Quantity: Number of units
   - Customer Priority: NORMAL, HIGH
   - Urgent: Check if urgent
   - Delivery Deadline: Pick date/time
   - Order Value: Total amount
3. Click **Create Order**
4. System automatically:
   - Calculates priority score
   - Detects risks
   - Suggests allocation

### Allocating Inventory

1. Go to **Orders** page
2. Click order to view details
3. Scroll to "Smart Allocation" section
4. Review preview of how inventory would be allocated
5. Click **"Allocate Inventory"**
6. System automatically:
   - Reserves inventory
   - Creates picking task (NEW!)
   - Logs activity
   - Detects any shortages

### Managing Picking Tasks

1. Go to **Picking** page
2. See all tasks sorted by priority
3. For each task:
   - **Assign Picker**: Select from Aarav, Priya, Rahul, Ananya, Vikram
   - **Start Picking**: Timer begins, monitors for delays
   - **Complete Picking**: Records time, moves to PACKING
   - **Report Issue**: Creates exception if something wrong

**NEW**: System automatically detects if picking is running 25%+ over target and creates exception!

### Packing & QC

1. Go to **Packing & QC** page
2. Start packing order
3. Complete packing
4. Perform QC checks:
   - ✅ **QC Pass**: Order ready for dispatch
   - ❌ **QC Fail**: Creates exception, order stays for rework

### Dispatch

1. Go to **Dispatch** page
2. See orders ready to dispatch
3. **Start Dispatch**: Initiates handoff to courier
4. **Mark Dispatched**: Completes order lifecycle

**NEW**: System automatically alerts if order waiting >30 min for dispatch!

### Managing Exceptions

1. Go to **Exceptions** page
2. See all active/resolved exceptions
3. For each exception:
   - Read **System Decision** (what happened)
   - Read **Recommended Action** (what to do)
   - Review **Expected Impact** (business outcome)
4. Click **Resolve** or **Override**
5. Add resolution note
6. Exception closed

### Viewing Analytics

1. Go to **Analytics** page
2. See KPIs:
   - Fulfillment rate
   - QC pass rate
   - Picking efficiency
   - Exception resolution
3. View trends:
   - Orders by status
   - Orders by priority
   - Exceptions by type
4. View bottleneck analysis

---

## Key Workflows

### Workflow 1: Simple Order → Dispatch
```
1. Create order (NEW)
2. Allocate inventory → Task auto-created (ALLOCATED)
3. Assign picker and start picking (PICKING)
4. Complete picking (PACKING)
5. Complete packing (QC)
6. QC passes (READY_TO_DISPATCH)
7. Start dispatch (DISPATCHING)
8. Mark dispatched (DISPATCHED) ✓
```
**Time**: ~2 minutes  
**Complexity**: Low  
**Exceptions**: None expected

### Workflow 2: Stock Shortage → Resolution
```
1. Create order: SKU-104, Qty 10 (only 7 available)
2. Try to allocate
3. System: Allocates 7 units, 3 pending
4. Exception: STOCK_SHORTAGE created
5. System: Creates reorder recommendation (26 units)
6. Operator: Reviews and approves reorder
7. Operator: Resolves exception
8. Order proceeds with available 7 units
9. Later: Shortage order fulfilled when stock arrives
```
**Key Points**: Smart allocation prevents lost sales, creates visibility

### Workflow 3: Picking Delay → Intervention
```
1. Picking task started, target 20 minutes
2. At 15 minutes: Still picking (75% progress) ✓ OK
3. At 20 minutes: Still picking (100%) - On target ✓
4. At 25 minutes: Still picking (125%) - 25% over!
5. System: Creates PICKING_DELAY exception (HIGH_DELAY)
6. Operator: Sees exception notification
7. Operator: Reviews and assigns additional picker
8. Picking completes at 28 minutes total
9. Operator: Resolves exception (success)
```
**Key Points**: Early warning prevents cascade delays

### Workflow 4: QC Failure → Rework
```
1. Order in QC status
2. Operator: Checks order contents
3. Operator: Finds damage to product
4. Operator: Clicks "QC FAIL"
5. System: Creates QC_FAILURE exception (HIGH severity)
6. System: Recommendation: "Remove faulty items, re-pack"
7. Operator: Reviews exception
8. Operator: Removes damaged item, re-packs
9. Operator: Re-runs QC and clicks "QC PASS"
10. Order moves to READY_TO_DISPATCH
11. Operator: Resolves exception
```
**Key Points**: Prevents defective goods reaching customers

---

## Database Tables Reference

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| orders | Order records | order_number, status, priority_score, customer_name |
| inventory | Stock management | sku, available_qty, reserved_qty, reorder_level |
| picking_tasks | Picking queue | task_id, order_number, status, assigned_picker |
| packing_records | Packing tracking | order_number, packing_status, qc_status |
| dispatch_records | Logistics tracking | order_number, courier, tracking_number, status |
| exceptions | Exception registry | exception_id, type, severity, status, resolution_note |
| recent_activity | Audit trail | timestamp, activity_type, message, severity |
| allocations | Allocation decisions | order_number, sku, allocated_qty, pending_qty |
| bottlenecks | Performance analysis | stage, avg_minutes, bottleneck_severity |
| reorder_recommendations | Stock replenishment | sku, recommended_qty, daily_demand |

---

## Priority Scoring System

```
Base Score: 0

+40 pts: Order marked URGENT
+20 pts: High-priority customer
+20 pts: Delivery deadline within 6 hours
+15 pts: Inventory risk detected
+10 pts: Order waiting >4 hours

TOTAL SCORE (0-100):
- 80+: CRITICAL (Immediate action)
- 60-79: HIGH (Expedited)
- 35-59: MEDIUM (Standard)
- <35: LOW (Backlog)
```

---

## Inventory Status Formula

```
Current Stock Level vs Reorder Level:

IF stock = 0:
  Status = OUT OF STOCK (Red)

ELSE IF stock <= (reorder_level × 35%):
  Status = CRITICAL (Dark Red)

ELSE IF stock <= reorder_level:
  Status = LOW STOCK (Yellow)

ELSE:
  Status = HEALTHY (Green)
```

**Example**: Reorder level = 20
- Stock 0: OUT OF STOCK
- Stock 1-7: CRITICAL (≤35% of 20)
- Stock 8-20: LOW STOCK
- Stock 21+: HEALTHY

---

## Picking Time Estimation

```
Estimated Time = 2 minutes + (4 minutes × item quantity)

Examples:
- 1 item: 2 + (1 × 4) = 6 minutes
- 5 items: 2 + (5 × 4) = 22 minutes
- 10 items: 2 + (10 × 4) = 42 minutes
```

---

## Reorder Calculation

```
Recommended Qty = (Daily Demand × Lead Time) + Safety Stock - Current Available

Minimum: 0 (never negative)

Example:
- Daily Demand: 8 units
- Lead Time: 2 days
- Safety Stock: 10 units
- Current Available: 0 units

Recommended = (8 × 2) + 10 - 0 = 26 units
```

---

## API Quick Reference

### Core Routes
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | / | Dashboard |
| GET | /orders | Order list |
| POST | /orders/create | Create order |
| POST | /orders/allocate | Allocate inventory |
| GET | /inventory | Inventory list |
| POST | /inventory/<sku>/reorder | Reorder recommendation |
| GET | /picking | Picking queue |
| POST | /picking/<task_id>/start | Start task |
| POST | /picking/<task_id>/complete | Complete task |
| GET | /packing | Packing list |
| POST | /packing/<order>/qc-pass | QC passed |
| POST | /packing/<order>/qc-fail | QC failed |
| GET | /dispatch | Dispatch list |
| POST | /dispatch/<order>/start | Start dispatch |
| POST | /dispatch/<order>/complete | Complete dispatch |
| GET | /exceptions | Exception list |
| POST | /exceptions/<exc_id>/resolve | Resolve exception |
| GET | /analytics | Analytics dashboard |
| GET | /search?q=<query> | Global search |

---

## Troubleshooting

### Problem: App won't start
```bash
# Check Python version
python --version  # Should be 3.8+

# Check dependencies
pip install -r requirements.txt

# Check port is available
netstat -ano | findstr :5000

# Restart app
python app.py
```

### Problem: Database locked
```
Cause: Multiple Flask instances running
Solution: Kill all python.exe and restart
```

### Problem: Changes not appearing
```
Cause: Browser cache
Solution: Ctrl+Shift+Delete (clear cache) or Ctrl+F5 (hard refresh)
```

### Problem: Order won't allocate
```
Cause: Inventory doesn't exist or out of stock
Solution: Create/restock inventory, try again
```

---

## Demo Scenarios for Presenting

### Scenario A: "Happy Path" (5 minutes)
1. Create order → Allocates automatically → Task created
2. Assign picker → Start picking → Complete
3. Packing → QC Pass → Dispatch → Complete
4. Show order in DISPATCHED status

### Scenario B: "Stock Shortage" (3 minutes)
1. Create order requiring 10 units, only 5 available
2. System allocates 5, flags shortage
3. Exception appears in Exception Registry
4. Show reorder recommendation
5. Resolve exception

### Scenario C: "Picking Delay" (4 minutes)
1. Create order, allocate (task auto-created)
2. Start picking, let it run >20 min
3. System detects HIGH_DELAY
4. Exception appears
5. Show alert on picking page
6. Resolve exception

### Scenario D: "QC Failure" (3 minutes)
1. Order at QC stage
2. Click QC FAIL, provide reason
3. Exception created
4. Show recommended action
5. Resolve exception

---

## Performance Tips

- **Dashboard loads slow**: Close other tabs, refresh cache
- **Database disk space**: Check wareflow.db size (~2-3 MB normal)
- **Many exceptions open**: Resolve old ones to keep list manageable
- **Search slow with many records**: Use more specific keywords

---

## Support

### Documentation
- `IMPLEMENTATION_SUMMARY.md` - Complete feature reference
- `COMPLETION_REPORT.md` - Technical implementation details
- `WAREFLOW_INSTRUCTIONS.md` - Full task specifications (if exists)

### Debug Info
- Enable browser Developer Console (F12) to see errors
- Check Flask terminal for server-side errors
- Database file: `wareflow.db` in project root

---

**Last Updated**: August 18, 2026  
**Version**: 1.0  
**Status**: Production Ready  
