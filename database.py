import sqlite3
import os
from datetime import datetime, timedelta

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wareflow.db')

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def migrate_db():
    """
    Safe migration: adds new tables without dropping existing data.
    Idempotent — safe to call on every app start.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Exceptions table (unified, replaces stock_exceptions for all types)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exception_id TEXT UNIQUE NOT NULL,
        exception_type TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'MEDIUM',
        order_number TEXT,
        sku TEXT,
        description TEXT NOT NULL,
        system_decision TEXT NOT NULL DEFAULT '',
        recommended_action TEXT NOT NULL DEFAULT '',
        expected_impact TEXT NOT NULL DEFAULT '',
        resolution_note TEXT DEFAULT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        detected_at TEXT NOT NULL,
        resolved_at TEXT DEFAULT NULL,
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 2. Picking tasks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS picking_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT UNIQUE NOT NULL,
        order_number TEXT NOT NULL,
        sku TEXT NOT NULL,
        zone TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        assigned_picker TEXT DEFAULT NULL,
        status TEXT NOT NULL DEFAULT 'WAITING',
        started_at TEXT DEFAULT NULL,
        completed_at TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 3. Packing records table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS packing_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT NOT NULL,
        packed_by TEXT DEFAULT NULL,
        packing_status TEXT NOT NULL DEFAULT 'WAITING',
        qc_status TEXT NOT NULL DEFAULT 'PENDING',
        qc_passed_at TEXT DEFAULT NULL,
        qc_failed_at TEXT DEFAULT NULL,
        qc_fail_reason TEXT DEFAULT NULL,
        started_at TEXT DEFAULT NULL,
        completed_at TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 4. Dispatch records table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dispatch_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT NOT NULL,
        courier TEXT NOT NULL DEFAULT 'BlueDart Express',
        tracking_number TEXT DEFAULT NULL,
        ready_at TEXT DEFAULT NULL,
        dispatch_started_at TEXT DEFAULT NULL,
        dispatched_at TEXT DEFAULT NULL,
        dispatch_status TEXT NOT NULL DEFAULT 'READY',
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 5. Reorder recommendations table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reorder_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL,
        recommended_qty INTEGER NOT NULL,
        current_available INTEGER NOT NULL,
        daily_demand INTEGER NOT NULL,
        lead_time_days INTEGER NOT NULL,
        safety_stock INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        created_at TEXT NOT NULL,
        actioned_at TEXT DEFAULT NULL
    )
    """)

    conn.commit()
    conn.close()
    print("Database migration complete.")

def seed_new_tables():
    """
    Seeds new tables with realistic demo data.
    Only inserts if tables are empty to avoid duplicates.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()

    # ── Seed Picking Tasks ─────────────────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM picking_tasks")
    if cursor.fetchone()[0] == 0:
        picking_data = [
            # task_id, order_number, sku, zone, qty, picker, status, started_at, completed_at, created_at
            ('PKT-001', 'ORD-1043', 'SKU-101', 'A1', 3, 'Elena Rostova', 'WAITING', None, None, (now - timedelta(hours=1, minutes=30)).isoformat()),
            ('PKT-002', 'ORD-1044', 'SKU-102', 'B1', 15, 'Marcus Vance', 'IN_PROGRESS', (now - timedelta(minutes=45)).isoformat(), None, (now - timedelta(hours=2)).isoformat()),
            ('PKT-003', 'ORD-1045', 'SKU-105', 'B3', 5, 'Sarah Connor', 'COMPLETED', (now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=1)).isoformat(), (now - timedelta(hours=3)).isoformat()),
            ('PKT-004', 'ORD-1047', 'SKU-103', 'B1', 4, 'Elena Rostova', 'COMPLETED', (now - timedelta(hours=3)).isoformat(), (now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=4)).isoformat()),
            ('PKT-005', 'ORD-1049', 'SKU-107', 'B4', 2, None, 'WAITING', None, None, (now - timedelta(minutes=30)).isoformat()),
            ('PKT-006', 'ORD-1050', 'SKU-101', 'A1', 8, 'Marcus Vance', 'IN_PROGRESS', (now - timedelta(hours=1)).isoformat(), None, (now - timedelta(hours=2)).isoformat()),
            ('PKT-007', 'ORD-1051', 'SKU-109', 'C2', 10, None, 'WAITING', None, None, (now - timedelta(minutes=15)).isoformat()),
            ('PKT-008', 'ORD-1052', 'SKU-105', 'B3', 6, 'Sarah Connor', 'COMPLETED', (now - timedelta(hours=4)).isoformat(), (now - timedelta(hours=3)).isoformat(), (now - timedelta(hours=5)).isoformat()),
        ]
        for row in picking_data:
            cursor.execute("""
            INSERT OR IGNORE INTO picking_tasks
                (task_id, order_number, sku, zone, quantity, assigned_picker,
                 status, started_at, completed_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """, row)

    # ── Seed Packing Records ───────────────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM packing_records")
    if cursor.fetchone()[0] == 0:
        packing_data = [
            # order_number, packed_by, packing_status, qc_status, qc_passed_at, qc_failed_at, qc_fail_reason, started_at, completed_at, created_at
            ('ORD-1045', 'Sarah Connor', 'PACKING', 'PENDING', None, None, None, (now - timedelta(hours=1)).isoformat(), None, (now - timedelta(hours=1, minutes=5)).isoformat()),
            ('ORD-1047', 'Elena Rostova', 'COMPLETED', 'PASSED', (now - timedelta(hours=1)).isoformat(), None, None, (now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=1, minutes=30)).isoformat(), (now - timedelta(hours=2, minutes=10)).isoformat()),
            ('ORD-1052', 'Sarah Connor', 'COMPLETED', 'PASSED', (now - timedelta(hours=2)).isoformat(), None, None, (now - timedelta(hours=3)).isoformat(), (now - timedelta(hours=2, minutes=30)).isoformat(), (now - timedelta(hours=3, minutes=10)).isoformat()),
        ]
        for row in packing_data:
            cursor.execute("""
            INSERT OR IGNORE INTO packing_records
                (order_number, packed_by, packing_status, qc_status, qc_passed_at,
                 qc_failed_at, qc_fail_reason, started_at, completed_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """, row)

    # ── Seed Dispatch Records ──────────────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM dispatch_records")
    if cursor.fetchone()[0] == 0:
        dispatch_data = [
            # order_number, courier, tracking_number, ready_at, dispatch_started_at, dispatched_at, dispatch_status
            ('ORD-1052', 'BlueDart Express', 'BD-9921XZ', (now - timedelta(hours=2)).isoformat(), None, None, 'READY'),
            ('ORD-1046', 'FedEx Ground', 'FX-88342A', (now - timedelta(hours=14)).isoformat(), (now - timedelta(hours=13)).isoformat(), (now - timedelta(hours=12)).isoformat(), 'DISPATCHED'),
            ('ORD-1053', 'DHL Express', 'DHL-77143B', (now - timedelta(hours=10)).isoformat(), (now - timedelta(hours=9)).isoformat(), (now - timedelta(hours=8)).isoformat(), 'DISPATCHED'),
        ]
        for row in dispatch_data:
            cursor.execute("""
            INSERT OR IGNORE INTO dispatch_records
                (order_number, courier, tracking_number, ready_at,
                 dispatch_started_at, dispatched_at, dispatch_status)
            VALUES (?,?,?,?,?,?,?)
            """, row)

    # ── Seed Exceptions ────────────────────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM exceptions")
    if cursor.fetchone()[0] == 0:
        exc_data = [
            ('EX-001', 'STOCK_SHORTAGE', 'CRITICAL', 'ORD-1042', 'SKU-104',
             '10 units of Wireless Headphones required but only 7 available.',
             'Allocate all 7 available units to Order ORD-1042 (priority score 105, CRITICAL) over ORD-1088 (score 40, MEDIUM).',
             'Reserve 7 units for ORD-1042. Backorder 3 units. Generate replenishment recommendation of 26 units.',
             'Protects the highest-priority shipment while preventing over-allocation. ORD-1088 will be fulfilled on next replenishment.',
             None, 'OPEN', (now - timedelta(hours=2)).isoformat(), None),
            ('EX-002', 'PICKING_DELAY', 'HIGH', 'ORD-1044', 'SKU-102',
             'Picking for Order ORD-1044 has been in progress for 45 minutes, exceeding the 30-minute target.',
             'Flag picker Marcus Vance for supervisor check-in. Reassign 5 remaining items to Zone B fast-lane.',
             'Escalate picking task to supervisor. Consider reassigning to secondary picker to recover time.',
             'Reduces risk of SLA breach. ORD-1044 deadline is in 10 hours — recoverable with immediate action.',
             None, 'OPEN', (now - timedelta(minutes=30)).isoformat(), None),
            ('EX-003', 'DAMAGED_ITEM', 'MEDIUM', 'ORD-1050', 'SKU-101',
             '2 of 8 Ergonomic Office Chairs received in picking zone show transit damage.',
             'Remove 2 damaged units from available inventory. Update reservation to 6 units. Initiate replacement procurement.',
             'Mark 2 units as damaged in inventory. Reassign available stock. Notify customer of partial fulfillment risk.',
             'Customer ORD-1050 may receive 6 of 8 ordered chairs. Proactive communication prevents complaint escalation.',
             None, 'IN_PROGRESS', (now - timedelta(hours=1)).isoformat(), None),
            ('EX-004', 'DISPATCH_DELAY', 'MEDIUM', 'ORD-1052', None,
             'Order ORD-1052 has been READY_TO_DISPATCH for 2 hours without dispatch initiation.',
             'Prioritize ORD-1052 for next dispatch slot. Assign courier BlueDart Express (already pre-assigned).',
             'Dispatch ORD-1052 in the next batch. Courier BlueDart Express is on-site.',
             'Prevents further SLA deterioration. Customer Quantum Retailers is a HIGH-priority account.',
             None, 'OPEN', (now - timedelta(hours=1, minutes=45)).isoformat(), None),
        ]
        for row in exc_data:
            cursor.execute("""
            INSERT OR IGNORE INTO exceptions
                (exception_id, exception_type, severity, order_number, sku, description,
                 system_decision, recommended_action, expected_impact, resolution_note,
                 status, detected_at, resolved_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, row)

    # ── Seed Reorder Recommendations ───────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM reorder_recommendations")
    if cursor.fetchone()[0] == 0:
        reorder_data = [
            ('SKU-104', 26, 7, 8, 2, 10, 'OPEN', now.isoformat()),
            ('SKU-106', 21, 0, 4, 4, 5, 'OPEN', (now - timedelta(hours=3)).isoformat()),
            ('SKU-102', 15, 12, 6, 3, 5, 'OPEN', (now - timedelta(hours=1)).isoformat()),
        ]
        for row in reorder_data:
            cursor.execute("""
            INSERT OR IGNORE INTO reorder_recommendations
                (sku, recommended_qty, current_available, daily_demand,
                 lead_time_days, safety_stock, status, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """, row)

    conn.commit()
    conn.close()
    print("New table seed data inserted.")

def init_db():
    """
    Full reset — drops all tables and re-seeds from scratch.
    Only use for development reset. Production uses migrate_db().
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Drop all tables in reverse dependency order
    for table in ['dispatch_records', 'packing_records', 'picking_tasks',
                  'reorder_recommendations', 'exceptions', 'stock_exceptions',
                  'allocations', 'recent_activity', 'bottlenecks', 'orders', 'inventory']:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")

    # 1. Inventory
    cursor.execute("""
    CREATE TABLE inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        bin_location TEXT NOT NULL,
        available_quantity INTEGER NOT NULL,
        reserved_quantity INTEGER NOT NULL DEFAULT 0,
        damaged_quantity INTEGER NOT NULL DEFAULT 0,
        reorder_level INTEGER NOT NULL,
        daily_demand INTEGER NOT NULL DEFAULT 0,
        lead_time_days INTEGER NOT NULL DEFAULT 0,
        safety_stock INTEGER NOT NULL DEFAULT 0
    )
    """)

    # 2. Orders
    cursor.execute("""
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        customer_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        customer_priority TEXT NOT NULL,
        is_urgent INTEGER NOT NULL,
        delivery_deadline TEXT NOT NULL,
        status TEXT NOT NULL,
        items_summary TEXT NOT NULL,
        total_value REAL NOT NULL,
        has_inventory_risk INTEGER NOT NULL,
        assigned_picker TEXT,
        requested_sku TEXT,
        requested_qty INTEGER
    )
    """)

    # 3. Allocations
    cursor.execute("""
    CREATE TABLE allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT NOT NULL,
        sku TEXT NOT NULL,
        requested_quantity INTEGER NOT NULL,
        allocated_quantity INTEGER NOT NULL,
        pending_quantity INTEGER NOT NULL,
        priority_score INTEGER NOT NULL,
        decision_reason TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 4. Stock exceptions (legacy, kept for backward compatibility)
    cursor.execute("""
    CREATE TABLE stock_exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exception_type TEXT NOT NULL,
        order_number TEXT NOT NULL,
        sku TEXT NOT NULL,
        required_qty INTEGER NOT NULL,
        available_qty INTEGER NOT NULL,
        shortage_qty INTEGER NOT NULL,
        priority_level TEXT NOT NULL,
        decision TEXT NOT NULL,
        resolution TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 5. Recent activity
    cursor.execute("""
    CREATE TABLE recent_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        message TEXT NOT NULL,
        severity TEXT NOT NULL
    )
    """)

    # 6. Bottlenecks
    cursor.execute("""
    CREATE TABLE bottlenecks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        area TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT NOT NULL,
        timestamp TEXT NOT NULL
    )
    """)

    # 7. Exceptions (unified)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exception_id TEXT UNIQUE NOT NULL,
        exception_type TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'MEDIUM',
        order_number TEXT,
        sku TEXT,
        description TEXT NOT NULL,
        system_decision TEXT NOT NULL DEFAULT '',
        recommended_action TEXT NOT NULL DEFAULT '',
        expected_impact TEXT NOT NULL DEFAULT '',
        resolution_note TEXT DEFAULT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        detected_at TEXT NOT NULL,
        resolved_at TEXT DEFAULT NULL,
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 8. Picking tasks
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS picking_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT UNIQUE NOT NULL,
        order_number TEXT NOT NULL,
        sku TEXT NOT NULL,
        zone TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        assigned_picker TEXT DEFAULT NULL,
        status TEXT NOT NULL DEFAULT 'WAITING',
        started_at TEXT DEFAULT NULL,
        completed_at TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 9. Packing records
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS packing_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT NOT NULL,
        packed_by TEXT DEFAULT NULL,
        packing_status TEXT NOT NULL DEFAULT 'WAITING',
        qc_status TEXT NOT NULL DEFAULT 'PENDING',
        qc_passed_at TEXT DEFAULT NULL,
        qc_failed_at TEXT DEFAULT NULL,
        qc_fail_reason TEXT DEFAULT NULL,
        started_at TEXT DEFAULT NULL,
        completed_at TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 10. Dispatch records
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dispatch_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT NOT NULL,
        courier TEXT NOT NULL DEFAULT 'BlueDart Express',
        tracking_number TEXT DEFAULT NULL,
        ready_at TEXT DEFAULT NULL,
        dispatch_started_at TEXT DEFAULT NULL,
        dispatched_at TEXT DEFAULT NULL,
        dispatch_status TEXT NOT NULL DEFAULT 'READY',
        FOREIGN KEY(order_number) REFERENCES orders(order_number)
    )
    """)

    # 11. Reorder recommendations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reorder_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL,
        recommended_qty INTEGER NOT NULL,
        current_available INTEGER NOT NULL,
        daily_demand INTEGER NOT NULL,
        lead_time_days INTEGER NOT NULL,
        safety_stock INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        created_at TEXT NOT NULL,
        actioned_at TEXT DEFAULT NULL
    )
    """)

    # Seed Inventory
    now = datetime.now()
    inventory_data = [
        ('SKU-104', 'Wireless Headphones', 'Electronics', 'B2', 7, 0, 0, 20, 8, 2, 10),
        ('SKU-101', 'Ergonomic Office Chair', 'Furniture', 'A1', 45, 0, 0, 15, 5, 5, 10),
        ('SKU-102', 'Wireless Mechanical Keyboard', 'Electronics', 'B1', 12, 0, 0, 20, 6, 3, 5),
        ('SKU-103', 'Ultra-Wide Monitor 34"', 'Electronics', 'B1', 2, 0, 0, 10, 2, 5, 2),
        ('SKU-105', 'Noise Cancelling Headphones', 'Electronics', 'B3', 60, 0, 0, 15, 10, 2, 8),
        ('SKU-106', 'USB-C Docking Station 10-in-1', 'Electronics', 'B4', 0, 0, 0, 15, 4, 4, 5),
        ('SKU-107', 'LED Desk Lamp with Qi Charger', 'Electronics', 'B4', 35, 0, 0, 12, 3, 3, 4),
        ('SKU-108', 'Premium Leather Journal', 'Office Supplies', 'C1', 120, 0, 0, 30, 15, 5, 15),
        ('SKU-109', 'Gel Ink Rollerball Pens (12-pack)', 'Office Supplies', 'C2', 8, 0, 0, 25, 10, 2, 10),
        ('SKU-110', 'High-Speed HDMI 2.1 Cable', 'Electronics', 'B5', 200, 0, 0, 50, 20, 2, 15),
        ('SKU-111', 'Anti-Fatigue Standing Mat', 'Furniture', 'A2', 18, 0, 0, 10, 4, 3, 5),
        ('SKU-112', 'Cardboard Shipping Boxes (Medium)', 'Packaging', 'D1', 450, 0, 0, 100, 80, 2, 50),
    ]
    for row in inventory_data:
        cursor.execute("""
        INSERT INTO inventory (sku, name, category, bin_location, available_quantity,
            reserved_quantity, damaged_quantity, reorder_level, daily_demand, lead_time_days, safety_stock)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, row)

    # Seed Orders
    orders_data = [
        ('ORD-1042', 'Acme Electronics', (now - timedelta(hours=5)).isoformat(), 'HIGH', 1, (now + timedelta(hours=4)).isoformat(), 'NEW', '10x Wireless Headphones', 24500.00, 1, None, 'SKU-104', 10),
        ('ORD-1088', 'Nova Retail', (now - timedelta(hours=1)).isoformat(), 'NORMAL', 0, (now + timedelta(hours=12)).isoformat(), 'NEW', '5x Wireless Headphones', 12250.00, 0, None, 'SKU-104', 5),
        ('ORD-1043', 'Apex Systems', (now - timedelta(hours=2)).isoformat(), 'HIGH', 1, (now + timedelta(hours=3)).isoformat(), 'ALLOCATED', '3x Ergonomic Office Chair', 49500.00, 0, 'Elena Rostova', 'SKU-101', 3),
        ('ORD-1044', 'Zenith Tech Partners', (now - timedelta(hours=8)).isoformat(), 'NORMAL', 0, (now + timedelta(hours=10)).isoformat(), 'PICKING', '15x Wireless Mechanical Keyboard', 13500.00, 1, 'Marcus Vance', 'SKU-102', 15),
        ('ORD-1045', 'Aero Logistics', (now - timedelta(hours=3)).isoformat(), 'NORMAL', 1, (now + timedelta(hours=2)).isoformat(), 'PACKING', '5x Noise Cancelling Headphones', 18900.00, 0, 'Sarah Connor', 'SKU-105', 5),
        ('ORD-1046', 'Starlight Design', (now - timedelta(hours=12)).isoformat(), 'NORMAL', 0, (now - timedelta(hours=2)).isoformat(), 'DISPATCHED', '5x Premium Leather Journal', 3750.00, 0, 'John Doe', 'SKU-108', 5),
        ('ORD-1047', 'Hyperion Retail', (now - timedelta(hours=3)).isoformat(), 'NORMAL', 0, (now + timedelta(hours=16)).isoformat(), 'QC', '4x Ultra-Wide Monitor 34"', 98000.00, 0, 'Elena Rostova', 'SKU-103', 4),
        ('ORD-1048', 'Genesis Medical Labs', (now - timedelta(hours=6)).isoformat(), 'NORMAL', 0, (now + timedelta(hours=24)).isoformat(), 'ON_HOLD', '12x USB-C Docking Station 10-in-1', 14400.00, 1, None, 'SKU-106', 12),
        ('ORD-1049', 'Triton Global', (now - timedelta(minutes=45)).isoformat(), 'NORMAL', 1, (now + timedelta(hours=5)).isoformat(), 'NEW', '2x LED Desk Lamp', 3200.00, 0, None, 'SKU-107', 2),
        ('ORD-1050', 'Ember Industries', (now - timedelta(hours=5)).isoformat(), 'HIGH', 0, (now + timedelta(hours=8)).isoformat(), 'PARTIALLY_FULFILLED', '8x Ergonomic Office Chair', 21400.00, 1, 'Marcus Vance', 'SKU-101', 8),
        ('ORD-1051', 'Vanguard Corp', (now - timedelta(minutes=20)).isoformat(), 'NORMAL', 0, (now + timedelta(hours=18)).isoformat(), 'NEW', '10x Gel Ink Rollerball Pens', 1500.00, 0, None, 'SKU-109', 10),
        ('ORD-1052', 'Quantum Retailers', (now - timedelta(hours=1)).isoformat(), 'HIGH', 0, (now + timedelta(hours=14)).isoformat(), 'READY_TO_DISPATCH', '6x Noise Cancelling Headphones', 45000.00, 0, 'Sarah Connor', 'SKU-105', 6),
        ('ORD-1053', 'Nexus Logistics', (now - timedelta(hours=14)).isoformat(), 'HIGH', 1, (now - timedelta(hours=8)).isoformat(), 'DISPATCHED', '8x Ultra-Wide Monitor 34"', 196000.00, 0, 'John Doe', 'SKU-103', 8),
        ('ORD-1054', 'Solaris Energy', (now - timedelta(hours=10)).isoformat(), 'NORMAL', 0, (now + timedelta(hours=18)).isoformat(), 'NEW', '2x Anti-Fatigue Standing Mat', 33000.00, 0, None, 'SKU-111', 2),
        ('ORD-1055', 'Orion Group', (now - timedelta(minutes=10)).isoformat(), 'NORMAL', 0, (now + timedelta(hours=24)).isoformat(), 'NEW', '1x High-Speed HDMI 2.1 Cable', 800.00, 0, None, 'SKU-110', 1),
    ]
    for row in orders_data:
        cursor.execute("""
        INSERT INTO orders (order_number, customer_name, created_at, customer_priority,
            is_urgent, delivery_deadline, status, items_summary, total_value,
            has_inventory_risk, assigned_picker, requested_sku, requested_qty)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, row)

    # Seed Activities
    activities = [
        ((now - timedelta(minutes=5)).isoformat(), 'Order', 'Order ORD-1055 received from Orion Group.', 'info'),
        ((now - timedelta(minutes=12)).isoformat(), 'Inventory', 'SKU-106 (USB-C Docking Station) marked OUT OF STOCK.', 'error'),
        ((now - timedelta(minutes=24)).isoformat(), 'Picker', 'Marcus Vance picked 12 items for Order ORD-1044.', 'success'),
        ((now - timedelta(minutes=42)).isoformat(), 'System', 'Route optimization updated for Zone B.', 'info'),
        ((now - timedelta(hours=1, minutes=15)).isoformat(), 'Carrier', 'FedEx ground pickup completed for 10 orders.', 'success'),
        ((now - timedelta(hours=2, minutes=5)).isoformat(), 'Inventory', 'SKU-102 (Wireless Keyboard) quantity dropped below threshold.', 'warning'),
        ((now - timedelta(hours=3, minutes=10)).isoformat(), 'Delay', 'Order ORD-1042 flagged as CRITICAL: approaching deadline.', 'error'),
        ((now - timedelta(hours=4, minutes=30)).isoformat(), 'Picker', 'Sarah Connor logged into picking terminal P-3 (Zone D).', 'info'),
    ]
    for row in activities:
        cursor.execute("INSERT INTO recent_activity (timestamp, activity_type, message, severity) VALUES (?,?,?,?)", row)

    # Seed Bottlenecks
    bottleneck_data = [
        ('Zone B (Electronics Shelf)', 'Critical', 'High picker traffic causing queue times to exceed 8 minutes.', (now - timedelta(minutes=30)).isoformat()),
        ('Packing Station 03', 'Moderate', 'Thermal printer offline; rerouting to Station 04.', (now - timedelta(hours=1)).isoformat()),
        ('Staging Area East', 'Moderate', 'Consolidation delayed due to oversize cargo backlog.', (now - timedelta(hours=2)).isoformat()),
    ]
    for row in bottleneck_data:
        cursor.execute("INSERT INTO bottlenecks (area, severity, description, timestamp) VALUES (?,?,?,?)", row)

    # Seed new tables (exceptions, picking, packing, dispatch, reorder)
    conn.commit()
    conn.close()

    # Now call migrate + seed for new tables
    migrate_db()
    seed_new_tables()
    print("Database fully initialized and seeded.")


if __name__ == '__main__':
    init_db()
