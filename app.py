import os
import random
import string
from flask import Flask, render_template, jsonify, abort, request, redirect, url_for
from database import get_db_connection, init_db, migrate_db, seed_new_tables, DB_FILE
from datetime import datetime, timedelta
from warehouse_logic import (
    calculate_priority, get_inventory_status, calculate_reorder_recommendation,
    allocate_inventory, detect_bottleneck, calculate_picking_optimization,
    check_dispatch_delays, generate_exception_id, generate_task_id,
    estimate_picking_time, check_picking_delay_risk
)

app = Flask(__name__)

# ── Startup: ensure DB and all tables exist ───────────────────────────────────
if not os.path.exists(DB_FILE):
    print("Database not found. Initializing from scratch...")
    init_db()
else:
    # Safely add new tables if they don't exist yet
    migrate_db()
    seed_new_tables()

# ── Helpers ───────────────────────────────────────────────────────────────────

COURIERS = ['BlueDart Express', 'FedEx Ground', 'DHL Express', 'Delhivery', 'Ekart Logistics']
PICKERS  = ['Aarav', 'Priya', 'Rahul', 'Ananya', 'Vikram']

def log_activity(cursor, message, activity_type='System', severity='info'):
    cursor.execute(
        "INSERT INTO recent_activity (timestamp, activity_type, message, severity) VALUES (?,?,?,?)",
        (datetime.now().isoformat(), activity_type, message, severity)
    )

def next_order_number(cursor):
    cursor.execute("SELECT order_number FROM orders ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        try:
            last_num = int(row[0].replace('ORD-', ''))
            return f"ORD-{last_num + 1}"
        except Exception:
            pass
    return "ORD-1100"

# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM orders")
    db_orders = [dict(row) for row in cursor.fetchall()]

    scored_orders = []
    current_time = datetime.now()
    for order in db_orders:
        analysis = calculate_priority(order, current_time)
        order.update(analysis)
        scored_orders.append(order)

    total_orders    = len(scored_orders)
    pending_orders  = sum(1 for o in scored_orders if o['status'] not in ('DISPATCHED',))
    orders_at_risk  = sum(1 for o in scored_orders if o['risk_badge'] in ('AT RISK', 'WARNING') and o['status'] != 'DISPATCHED')

    cursor.execute("SELECT * FROM inventory")
    db_inventory = [dict(row) for row in cursor.fetchall()]
    total_inventory   = len(db_inventory)
    healthy_inventory = 0
    active_pickers_set = {o['assigned_picker'] for o in scored_orders if o['assigned_picker'] and o['status'] in ('PICKING', 'PACKING')}

    for item in db_inventory:
        status_name, _ = get_inventory_status(item['available_quantity'], item['reorder_level'], item['sku'])
        if status_name == 'HEALTHY':
            healthy_inventory += 1

    inventory_health  = round(healthy_inventory / total_inventory * 100, 1) if total_inventory > 0 else 0
    picking_efficiency = round(88.4 + min(len(active_pickers_set) * 0.8, 6.0), 1)
    fulfillment_rate  = round((total_orders - orders_at_risk) / total_orders * 100, 1) if total_orders > 0 else 0

    active_risky = sorted([o for o in scored_orders if o['status'] != 'DISPATCHED'], key=lambda o: o['score'], reverse=True)
    highest_priority_order = active_risky[0] if active_risky else None

    allocation_record = None
    if highest_priority_order:
        cursor.execute("SELECT * FROM allocations WHERE order_number = ?", (highest_priority_order['order_number'],))
        row = cursor.fetchone()
        if row:
            allocation_record = dict(row)

    pipeline = {'Pending': 0, 'Picking': 0, 'Packing': 0, 'Shipped': 0}
    for o in scored_orders:
        st = o['status']
        if st in ('NEW', 'ON_HOLD'):
            pipeline['Pending'] += 1
        elif st in ('ALLOCATED', 'PICKING'):
            pipeline['Picking'] += 1
        elif st in ('PACKING', 'QC', 'READY_TO_DISPATCH', 'PARTIALLY_FULFILLED'):
            pipeline['Packing'] += 1
        elif st == 'DISPATCHED':
            pipeline['Shipped'] += 1

    pipeline_total = sum(pipeline.values())
    pipeline_pcts  = {k: round(v / pipeline_total * 100, 1) if pipeline_total > 0 else 0 for k, v in pipeline.items()}

    cursor.execute("SELECT SUM(available_quantity) FROM inventory")
    total_qty = cursor.fetchone()[0] or 0
    storage_utilization = round(total_qty / 3500 * 100, 1)

    cursor.execute("SELECT * FROM bottlenecks ORDER BY timestamp DESC LIMIT 3")
    bottlenecks = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM recent_activity ORDER BY timestamp DESC LIMIT 8")
    recent_activities = []
    for row in cursor.fetchall():
        rd = dict(row)
        try:
            rd['time_formatted'] = datetime.fromisoformat(rd['timestamp']).strftime('%I:%M %p')
        except Exception:
            rd['time_formatted'] = rd['timestamp'][:16]
        recent_activities.append(rd)

    # Open exceptions count for header badge
    cursor.execute("SELECT COUNT(*) FROM exceptions WHERE status = 'OPEN'")
    open_exceptions = cursor.fetchone()[0]

    # Inventory list for New Order modal
    cursor.execute("SELECT sku, name, category FROM inventory ORDER BY name")
    inventory_for_modal = [dict(r) for r in cursor.fetchall()]

    conn.close()

    demo_order_allocated = bool(
        allocation_record and highest_priority_order
        and highest_priority_order['order_number'] == 'ORD-1042'
    )

    return render_template(
        'dashboard.html',
        total_orders=total_orders,
        pending_orders=pending_orders,
        orders_at_risk=orders_at_risk,
        inventory_health=inventory_health,
        picking_efficiency=picking_efficiency,
        fulfillment_rate=fulfillment_rate,
        highest_priority_order=highest_priority_order,
        allocation_record=allocation_record,
        demo_order_allocated=demo_order_allocated,
        pipeline=pipeline,
        pipeline_pcts=pipeline_pcts,
        storage_utilization=storage_utilization,
        active_pickers_count=len(active_pickers_set),
        pickers=list(active_pickers_set),
        bottlenecks=bottlenecks,
        recent_activities=recent_activities,
        open_exceptions=open_exceptions,
        inventory_for_modal=inventory_for_modal,
    )

# ── NEW ORDER ─────────────────────────────────────────────────────────────────

@app.route('/orders/create', methods=['POST'])
def create_order():
    data = request.get_json() or {}

    customer_name     = (data.get('customer_name') or '').strip()
    customer_priority = data.get('customer_priority', 'NORMAL').upper()
    sku               = (data.get('sku') or '').strip()
    quantity          = data.get('quantity', 0)
    delivery_deadline = (data.get('delivery_deadline') or '').strip()
    is_urgent         = int(bool(data.get('is_urgent', False)))
    total_value       = float(data.get('total_value') or 0)

    # Validation
    if not customer_name:
        return jsonify({'success': False, 'error': 'Customer name is required.'}), 400
    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Quantity must be a positive integer.'}), 400
    if total_value < 0:
        return jsonify({'success': False, 'error': 'Order value cannot be negative.'}), 400
    if not delivery_deadline:
        return jsonify({'success': False, 'error': 'Delivery deadline is required.'}), 400
    try:
        deadline_dt = datetime.fromisoformat(delivery_deadline)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid delivery deadline format.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    if sku:
        cursor.execute("SELECT * FROM inventory WHERE sku = ?", (sku,))
        product = cursor.fetchone()
        if not product:
            conn.close()
            return jsonify({'success': False, 'error': f'Product {sku} not found in inventory.'}), 400
        product = dict(product)
        items_summary = f"{quantity}x {product['name']}"
        has_inventory_risk = 1 if product['available_quantity'] < quantity else 0
    else:
        items_summary = f"{quantity}x Custom Item"
        has_inventory_risk = 0
        product = None

    now = datetime.now()
    order_number = next_order_number(cursor)

    # Build order dict for priority calculation
    temp_order = {
        'order_number': order_number,
        'customer_name': customer_name,
        'created_at': now.isoformat(),
        'customer_priority': customer_priority,
        'is_urgent': is_urgent,
        'delivery_deadline': deadline_dt.isoformat(),
        'status': 'NEW',
        'has_inventory_risk': has_inventory_risk,
    }
    analysis = calculate_priority(temp_order, now)

    try:
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute("""
            INSERT INTO orders (order_number, customer_name, created_at, customer_priority,
                is_urgent, delivery_deadline, status, items_summary, total_value,
                has_inventory_risk, assigned_picker, requested_sku, requested_qty)
            VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?)
        """, (order_number, customer_name, now.isoformat(), customer_priority,
              is_urgent, deadline_dt.isoformat(), 'NEW', items_summary, total_value,
              has_inventory_risk, sku or None, quantity))

        log_activity(cursor,
            f"Order {order_number} created for {customer_name}. Priority: {analysis['priority_level']} (Score: {analysis['score']}).",
            'Order', 'success')

        cursor.execute("COMMIT")
        conn.close()
        return jsonify({
            'success': True,
            'order_number': order_number,
            'priority_level': analysis['priority_level'],
            'score': analysis['score'],
            'risk_badge': analysis['risk_badge'],
        })
    except Exception as e:
        cursor.execute("ROLLBACK")
        conn.close()
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

# ── ORDERS ────────────────────────────────────────────────────────────────────

@app.route('/orders')
def orders_list():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY id DESC")
    db_orders = [dict(row) for row in cursor.fetchall()]
    conn.close()

    current_time = datetime.now()
    scored_orders = []
    for order in db_orders:
        analysis = calculate_priority(order, current_time)
        order.update(analysis)
        try:
            order['created_formatted'] = datetime.fromisoformat(order['created_at']).strftime('%b %d, %Y %I:%M %p')
        except Exception:
            order['created_formatted'] = order['created_at']
        scored_orders.append(order)

    return render_template('orders.html', orders=scored_orders)

@app.route('/orders/<order_id>')
def order_detail(order_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE order_number = ? OR id = ?", (order_id, order_id))
    db_order = cursor.fetchone()

    if not db_order:
        conn.close()
        abort(404)

    order = dict(db_order)
    current_time = datetime.now()
    order.update(calculate_priority(order, current_time))

    try:
        order['created_formatted'] = datetime.fromisoformat(order['created_at']).strftime('%b %d, %Y %I:%M %p')
    except Exception:
        order['created_formatted'] = order['created_at']

    try:
        order['deadline_formatted'] = datetime.fromisoformat(order['delivery_deadline']).strftime('%b %d, %Y %I:%M %p')
    except Exception:
        order['deadline_formatted'] = order['delivery_deadline']

    cursor.execute("SELECT * FROM inventory WHERE sku = ?", (order['requested_sku'],))
    db_product = cursor.fetchone()
    product = dict(db_product) if db_product else None

    cursor.execute("SELECT * FROM allocations WHERE order_number = ?", (order['order_number'],))
    db_alloc = cursor.fetchone()
    allocation = dict(db_alloc) if db_alloc else None

    cursor.execute("SELECT * FROM stock_exceptions WHERE order_number = ?", (order['order_number'],))
    db_ex = cursor.fetchone()
    exception = dict(db_ex) if db_ex else None

    priority_level = order['priority_level']
    rec_map = {
        'CRITICAL': "CRITICAL: This order requires immediate dispatch. Reroute labor to fulfill this immediately.",
        'HIGH':     "HIGH PRIORITY: Process ahead of standard queues. Monitor picking speed to prevent SLA breaches.",
        'MEDIUM':   "STANDARD: Process in normal FIFO batch rotation. Review inventory levels if warning is active.",
        'LOW':      "LOW PRIORITY: Backlog safety order. Fulfill during off-peak hours.",
    }
    recommendation = rec_map.get(priority_level, '')

    allocation_preview = None
    competing_orders   = []
    if not allocation and product:
        cursor.execute("SELECT * FROM orders WHERE requested_sku = ? AND status != 'DISPATCHED'", (product['sku'],))
        for comp in cursor.fetchall():
            comp = dict(comp)
            comp.update(calculate_priority(comp, current_time))
            competing_orders.append(comp)
        allocation_preview = allocate_inventory(competing_orders, product['available_quantity'])

    conn.close()

    return render_template(
        'order_detail.html',
        order=order,
        recommendation=recommendation,
        product=product,
        allocation=allocation,
        exception=exception,
        allocation_preview=allocation_preview,
        competing_orders=competing_orders,
    )

# ── ALLOCATE (fix: read JSON not form) ───────────────────────────────────────

@app.route('/orders/allocate', methods=['POST'])
def allocate_order_inventory():
    data = request.get_json() or {}
    order_number = data.get('order_number')
    sku          = data.get('sku')

    if not order_number or not sku:
        return jsonify({'success': False, 'error': 'Missing parameters.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM allocations WHERE order_number = ? AND sku = ?", (order_number, sku))
    if cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Allocation has already been executed for this order.'}), 400

    cursor.execute("SELECT * FROM orders WHERE order_number = ?", (order_number,))
    db_order = cursor.fetchone()
    if not db_order:
        conn.close()
        return jsonify({'success': False, 'error': 'Order not found.'}), 404
    order = dict(db_order)

    cursor.execute("SELECT * FROM inventory WHERE sku = ?", (sku,))
    db_product = cursor.fetchone()
    if not db_product:
        conn.close()
        return jsonify({'success': False, 'error': 'Inventory item not found.'}), 404
    product = dict(db_product)

    cursor.execute("SELECT * FROM orders WHERE requested_sku = ? AND status != 'DISPATCHED'", (sku,))
    current_time    = datetime.now()
    competing_orders = []
    for comp in cursor.fetchall():
        comp = dict(comp)
        comp.update(calculate_priority(comp, current_time))
        competing_orders.append(comp)

    allocation_result = allocate_inventory(competing_orders, product['available_quantity'])

    order_alloc = next((a for a in allocation_result['allocations'] if a['order_number'] == order_number), None)
    if not order_alloc or order_alloc['allocated'] == 0:
        conn.close()
        return jsonify({'success': False, 'error': 'Priority allocation rules assigned zero units to this order.'}), 400

    allocated_qty = order_alloc['allocated']
    pending_qty   = order_alloc['pending']

    try:
        cursor.execute("BEGIN TRANSACTION")

        new_available = product['available_quantity'] - allocated_qty
        new_reserved  = product['reserved_quantity'] + allocated_qty
        cursor.execute("UPDATE inventory SET available_quantity=?, reserved_quantity=? WHERE sku=?",
                       (new_available, new_reserved, sku))

        new_status = 'PARTIALLY_FULFILLED' if pending_qty > 0 else 'ALLOCATED'
        cursor.execute("UPDATE orders SET status=? WHERE order_number=?", (new_status, order_number))

        cursor.execute("""
            INSERT INTO allocations (order_number, sku, requested_quantity, allocated_quantity,
                pending_quantity, priority_score, decision_reason, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (order_number, sku, order['requested_qty'], allocated_qty, pending_qty,
              order_alloc['score'], allocation_result['decision_reason'], current_time.isoformat()))

        # ── AUTOMATIC PICKING TASK CREATION ────────────────────────────────────
        # Create picking task for allocated quantity
        if allocated_qty > 0:
            task_id = generate_task_id(cursor)
            zone = product.get('zone', 'A1')  # Default zone if not specified
            estimated_minutes = estimate_picking_time(allocated_qty)
            
            cursor.execute("""
                INSERT INTO picking_tasks (task_id, order_number, sku, zone, quantity,
                    status, created_at)
                VALUES (?,?,?,?,?,?,?)
            """, (task_id, order_number, sku, zone, allocated_qty, 'WAITING', current_time.isoformat()))
            
            log_activity(cursor, f"Picking task {task_id} created for Order {order_number}. Qty: {allocated_qty} units. Zone: {zone}. Est. time: {estimated_minutes} min.", 'System', 'info')

        if pending_qty > 0:
            cursor.execute("""
                INSERT INTO stock_exceptions (exception_type, order_number, sku, required_qty,
                    available_qty, shortage_qty, priority_level, decision, resolution, status)
                VALUES (?,?,?,?,?,?,?,?,?,'OPEN')
            """, ('STOCK_SHORTAGE', order_number, sku, order['requested_qty'],
                  product['available_quantity'], pending_qty, order_alloc['priority_level'],
                  f"{allocated_qty} units allocated", f"{pending_qty} units pending replenishment"))

        log_activity(cursor, f"Smart allocation: Order {order_number} received {allocated_qty} units of {sku}.", 'Order', 'success')
        if pending_qty > 0:
            log_activity(cursor, f"Stock shortage: {sku} shortage {pending_qty} units.", 'Inventory', 'error')
            reorder_qty = (product['daily_demand'] * product['lead_time_days']) + product['safety_stock'] - new_available
            log_activity(cursor, f"Reorder recommendation: {sku} — {max(reorder_qty,0)} units.", 'System', 'info')

        cursor.execute("COMMIT")
        conn.close()
        return jsonify({'success': True, 'allocated': allocated_qty, 'pending': pending_qty,
                        'message': f"Allocation completed. {allocated_qty} units reserved for {order_number}. Picking task created."})
    except Exception as e:
        cursor.execute("ROLLBACK")
        conn.close()
        return jsonify({'success': False, 'error': f'Transaction failed: {str(e)}'}), 500

# ── INVENTORY ─────────────────────────────────────────────────────────────────

@app.route('/inventory')
def inventory_list():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory")
    db_inventory = [dict(row) for row in cursor.fetchall()]
    conn.close()

    kpi = {'Total_SKUs': len(db_inventory), 'Healthy': 0, 'Low_Stock': 0, 'Critical': 0, 'Out_of_Stock': 0, 'Damaged': 0}
    inventory_items = []
    for item in db_inventory:
        status, badge_class = get_inventory_status(item['available_quantity'], item['reorder_level'], item['sku'])
        item['status']            = status
        item['status_badge']      = badge_class
        item['total_quantity']    = item['available_quantity'] + item['reserved_quantity'] + item['damaged_quantity']
        reorder_qty               = calculate_reorder_recommendation(item)
        item['recommended_action'] = f"Reorder {reorder_qty} units" if status in ('LOW STOCK', 'CRITICAL', 'OUT OF STOCK') and reorder_qty > 0 else "No action required"
        inventory_items.append(item)
        if status == 'HEALTHY':        kpi['Healthy'] += 1
        elif status == 'LOW STOCK':    kpi['Low_Stock'] += 1
        elif status == 'CRITICAL':     kpi['Critical'] += 1
        elif status == 'OUT OF STOCK': kpi['Out_of_Stock'] += 1
        kpi['Damaged'] += item['damaged_quantity']

    return render_template('inventory.html', inventory=inventory_items, kpi=kpi)

@app.route('/inventory/<id>')
def inventory_detail(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory WHERE id=? OR sku=?", (id, id))
    db_item = cursor.fetchone()
    conn.close()

    if not db_item:
        abort(404)

    item = dict(db_item)
    item['total_quantity'] = item['available_quantity'] + item['reserved_quantity'] + item['damaged_quantity']
    status, badge_class    = get_inventory_status(item['available_quantity'], item['reorder_level'], item['sku'])
    item['status']         = status
    item['status_badge']   = badge_class
    reorder_recommended    = status in ('LOW STOCK', 'CRITICAL', 'OUT OF STOCK')
    reorder_quantity       = calculate_reorder_recommendation(item)

    return render_template('inventory_detail.html', item=item,
                           reorder_recommended=reorder_recommended, reorder_quantity=reorder_quantity)

# ── EXCEPTIONS ────────────────────────────────────────────────────────────────

@app.route('/exceptions')
def exceptions_list():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM exceptions ORDER BY detected_at DESC")
    db_exc = [dict(r) for r in cursor.fetchall()]

    for e in db_exc:
        try:
            e['detected_formatted'] = datetime.fromisoformat(e['detected_at']).strftime('%b %d, %I:%M %p')
        except Exception:
            e['detected_formatted'] = e['detected_at']

    kpi = {
        'open':     sum(1 for e in db_exc if e['status'] == 'OPEN'),
        'critical': sum(1 for e in db_exc if e['severity'] == 'CRITICAL' and e['status'] == 'OPEN'),
        'high':     sum(1 for e in db_exc if e['severity'] == 'HIGH' and e['status'] == 'OPEN'),
        'resolved': sum(1 for e in db_exc if e['status'] == 'RESOLVED'),
        'total':    len(db_exc),
    }

    conn.close()
    return render_template('exceptions.html', exceptions=db_exc, kpi=kpi)

@app.route('/exceptions/<exc_id>/resolve', methods=['POST'])
def resolve_exception(exc_id):
    data = request.get_json() or {}
    note = (data.get('note') or 'Resolved by operator.').strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM exceptions WHERE exception_id=? OR id=?", (exc_id, exc_id))
    exc = cursor.fetchone()
    if not exc:
        conn.close()
        return jsonify({'success': False, 'error': 'Exception not found.'}), 404

    try:
        now = datetime.now()
        cursor.execute("UPDATE exceptions SET status='RESOLVED', resolution_note=?, resolved_at=? WHERE exception_id=? OR id=?",
                       (note, now.isoformat(), exc_id, exc_id))
        log_activity(cursor, f"Exception {exc_id} resolved. Note: {note}", 'System', 'success')
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Exception {exc_id} marked as RESOLVED.'})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

@app.route('/exceptions/<exc_id>/override', methods=['POST'])
def override_exception(exc_id):
    data = request.get_json() or {}
    note = (data.get('note') or 'Operator overrode system recommendation.').strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM exceptions WHERE exception_id=? OR id=?", (exc_id, exc_id))
    exc = cursor.fetchone()
    if not exc:
        conn.close()
        return jsonify({'success': False, 'error': 'Exception not found.'}), 404

    try:
        now = datetime.now()
        cursor.execute("UPDATE exceptions SET status='OVERRIDDEN', resolution_note=?, resolved_at=? WHERE exception_id=? OR id=?",
                       (note, now.isoformat(), exc_id, exc_id))
        log_activity(cursor, f"Exception {exc_id} overridden. Note: {note}", 'System', 'warning')
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Exception {exc_id} overridden.'})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

# ── PICKING ───────────────────────────────────────────────────────────────────

@app.route('/picking')
def picking_list():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pt.*, o.customer_name, o.customer_priority, o.is_urgent, o.delivery_deadline,
               o.status as order_status, i.name as product_name
        FROM picking_tasks pt
        LEFT JOIN orders o ON pt.order_number = o.order_number
        LEFT JOIN inventory i ON pt.sku = i.sku
        ORDER BY pt.created_at DESC
    """)
    db_tasks = [dict(r) for r in cursor.fetchall()]

    current_time = datetime.now()
    tasks = []
    for t in db_tasks:
        # Calculate elapsed time for IN_PROGRESS tasks
        if t['status'] == 'IN_PROGRESS' and t['started_at']:
            try:
                started = datetime.fromisoformat(t['started_at'])
                t['elapsed_minutes'] = round((current_time - started).total_seconds() / 60)
            except Exception:
                t['elapsed_minutes'] = 0
        else:
            t['elapsed_minutes'] = 0

        try:
            t['created_formatted'] = datetime.fromisoformat(t['created_at']).strftime('%b %d, %I:%M %p')
        except Exception:
            t['created_formatted'] = t['created_at']

        # Quick priority calc
        order_stub = {
            'order_number': t['order_number'],
            'customer_priority': t.get('customer_priority', 'NORMAL'),
            'is_urgent': t.get('is_urgent', 0),
            'delivery_deadline': t.get('delivery_deadline', (current_time + timedelta(hours=24)).isoformat()),
            'has_inventory_risk': 0,
            'status': t.get('order_status', 'NEW'),
            'created_at': t['created_at'],
        }
        pa = calculate_priority(order_stub, current_time)
        t['priority_level'] = pa['priority_level']
        t['priority_score']  = pa['score']
        
        # ── PICKING DELAY DETECTION ────────────────────────────────────────────
        # Check for picking delays and create exceptions if needed
        if t['status'] == 'IN_PROGRESS' and t['elapsed_minutes'] > 0:
            target_minutes = estimate_picking_time(t['quantity'])
            delay_status, overage_pct = check_picking_delay_risk(t['elapsed_minutes'], target_minutes)
            t['delay_status'] = delay_status
            t['overage_pct'] = overage_pct
            t['target_minutes'] = target_minutes
            
            # Create exception for critical delays
            if delay_status in ('CRITICAL_DELAY', 'HIGH_DELAY'):
                cursor.execute("""
                    SELECT COUNT(*) FROM exceptions 
                    WHERE exception_type='PICKING_DELAY' AND order_number=?
                """, (t['order_number'],))
                if cursor.fetchone()[0] == 0:  # Only create once
                    exc_id = generate_exception_id(conn)
                    cursor.execute("""
                        INSERT INTO exceptions (exception_id, exception_type, severity, order_number, sku, 
                            description, system_decision, recommended_action, expected_impact, status, detected_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (exc_id, 'PICKING_DELAY', 'HIGH', t['order_number'], t['sku'],
                          f"Picking task {t['task_id']} running {overage_pct}% over target ({t['elapsed_minutes']} min vs {target_minutes} min target)",
                          'Expedite picking or investigate bottleneck.',
                          'Assign additional picker or pre-stage items.',
                          'Prevent order delivery delay.',
                          'OPEN', current_time.isoformat()))
                    log_activity(cursor, f"Picking delay exception created for {t['order_number']}. Task running {overage_pct}% over target.", 'System', 'warning')
                    cursor.execute("SELECT COUNT(*) FROM exceptions WHERE status='OPEN'")
        else:
            t['delay_status'] = 'ON_TIME'
            t['overage_pct'] = 0
            t['target_minutes'] = estimate_picking_time(t['quantity'])
        
        tasks.append(t)

    # Commit any exception creations once through the SQLite connection, not via a raw cursor COMMIT.
    try:
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    kpi = {
        'waiting':    sum(1 for t in tasks if t['status'] == 'WAITING'),
        'in_progress': sum(1 for t in tasks if t['status'] == 'IN_PROGRESS'),
        'completed':  sum(1 for t in tasks if t['status'] == 'COMPLETED'),
        'blocked':    sum(1 for t in tasks if t['status'] == 'BLOCKED'),
        'total':      len(tasks),
    }

    # Batch optimization hints
    optimization = calculate_picking_optimization(tasks)

    conn.close()
    return render_template('picking.html', tasks=tasks, kpi=kpi, optimization=optimization, pickers=PICKERS)

@app.route('/picking/<task_id>/start', methods=['POST'])
def start_picking(task_id):
    data   = request.get_json() or {}
    picker = data.get('picker', PICKERS[0])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM picking_tasks WHERE task_id=?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return jsonify({'success': False, 'error': 'Picking task not found.'}), 404
    task = dict(task)

    if task['status'] not in ('WAITING',):
        conn.close()
        return jsonify({'success': False, 'error': f'Cannot start task in status {task["status"]}.'}), 400

    now = datetime.now()
    cursor.execute("UPDATE picking_tasks SET status='IN_PROGRESS', assigned_picker=?, started_at=? WHERE task_id=?",
                   (picker, now.isoformat(), task_id))
    cursor.execute("UPDATE orders SET status='PICKING', assigned_picker=? WHERE order_number=? AND status='ALLOCATED'",
                   (picker, task['order_number']))
    log_activity(cursor, f"Picking started for Order {task['order_number']} by {picker}. Task: {task_id}.", 'Picker', 'success')
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'Picking task {task_id} started.'})

@app.route('/picking/<task_id>/complete', methods=['POST'])
def complete_picking(task_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM picking_tasks WHERE task_id=?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return jsonify({'success': False, 'error': 'Picking task not found.'}), 404
    task = dict(task)

    if task['status'] != 'IN_PROGRESS':
        conn.close()
        return jsonify({'success': False, 'error': f'Task must be IN_PROGRESS to complete.'}), 400

    now = datetime.now()
    cursor.execute("UPDATE picking_tasks SET status='COMPLETED', completed_at=? WHERE task_id=?",
                   (now.isoformat(), task_id))
    cursor.execute("UPDATE orders SET status='PACKING' WHERE order_number=? AND status='PICKING'",
                   (task['order_number'],))

    # Create packing record
    cursor.execute("SELECT COUNT(*) FROM packing_records WHERE order_number=?", (task['order_number'],))
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO packing_records (order_number, packed_by, packing_status, qc_status, created_at)
            VALUES (?,?,?,?,?)
        """, (task['order_number'], task.get('assigned_picker'), 'WAITING', 'PENDING', now.isoformat()))

    log_activity(cursor, f"Picking completed for Order {task['order_number']}. Moved to PACKING.", 'Picker', 'success')
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'Picking completed. Order moved to PACKING.'})

@app.route('/picking/<task_id>/report-issue', methods=['POST'])
def report_picking_issue(task_id):
    data       = request.get_json() or {}
    issue_type = data.get('issue_type', 'MISSING_ITEM')
    note       = data.get('note', 'Issue reported during picking.')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM picking_tasks WHERE task_id=?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return jsonify({'success': False, 'error': 'Task not found.'}), 404
    task = dict(task)

    now    = datetime.now()
    exc_id = generate_exception_id(conn)

    type_map = {
        'MISSING_ITEM':  ('HIGH',   f"Missing item during picking for Order {task['order_number']} — {note}"),
        'DAMAGED_ITEM':  ('HIGH',   f"Damaged item found during picking for Order {task['order_number']} — {note}"),
        'WRONG_LOCATION': ('MEDIUM', f"Item not at expected bin location for Order {task['order_number']} — {note}"),
    }
    severity, description = type_map.get(issue_type, ('MEDIUM', note))

    cursor.execute("""
        INSERT INTO exceptions (exception_id, exception_type, severity, order_number, sku, description,
            system_decision, recommended_action, expected_impact, status, detected_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (exc_id, issue_type, severity, task['order_number'], task['sku'], description,
          'Pause picking task and escalate to supervisor.',
          'Verify bin location, check adjacent bins, report to inventory team.',
          'Resolving quickly prevents order delay.',
          'OPEN', now.isoformat()))

    cursor.execute("UPDATE picking_tasks SET status='BLOCKED' WHERE task_id=?", (task_id,))
    log_activity(cursor, f"Picking issue reported for {task['order_number']}: {issue_type}. Exception {exc_id} created.", 'System', 'error')
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'exception_id': exc_id, 'message': f'Issue logged. Exception {exc_id} created.'})

# ── PACKING & QC ──────────────────────────────────────────────────────────────

@app.route('/packing')
def packing_list():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pr.*, o.customer_name, o.items_summary, o.customer_priority,
               o.is_urgent, o.delivery_deadline, o.assigned_picker
        FROM packing_records pr
        LEFT JOIN orders o ON pr.order_number = o.order_number
        ORDER BY pr.created_at DESC
    """)
    db_packing = [dict(r) for r in cursor.fetchall()]

    # Also include orders in PACKING/QC status without a packing record
    cursor.execute("SELECT * FROM orders WHERE status IN ('PACKING','QC','READY_TO_DISPATCH')")
    for o in cursor.fetchall():
        o = dict(o)
        cursor.execute("SELECT COUNT(*) FROM packing_records WHERE order_number=?", (o['order_number'],))
        if cursor.fetchone()[0] == 0:
            db_packing.append({
                'order_number': o['order_number'],
                'customer_name': o['customer_name'],
                'items_summary': o['items_summary'],
                'packing_status': 'WAITING',
                'qc_status': 'PENDING',
                'packed_by': o['assigned_picker'],
                'started_at': None,
                'completed_at': None,
                'qc_passed_at': None,
                'qc_failed_at': None,
                'qc_fail_reason': None,
                'created_at': o['created_at'],
            })

    for p in db_packing:
        try:
            p['created_formatted'] = datetime.fromisoformat(p['created_at']).strftime('%b %d, %I:%M %p')
        except Exception:
            p['created_formatted'] = p.get('created_at', '')

    kpi = {
        'waiting':     sum(1 for p in db_packing if p['packing_status'] == 'WAITING'),
        'packing':     sum(1 for p in db_packing if p['packing_status'] == 'PACKING'),
        'qc_pending':  sum(1 for p in db_packing if p['qc_status'] == 'PENDING' and p['packing_status'] == 'COMPLETED'),
        'passed':      sum(1 for p in db_packing if p['qc_status'] == 'PASSED'),
        'failed':      sum(1 for p in db_packing if p['qc_status'] == 'FAILED'),
    }

    conn.close()
    return render_template('packing.html', packing_records=db_packing, kpi=kpi, pickers=PICKERS)

@app.route('/packing/<order_number>/start', methods=['POST'])
def start_packing(order_number):
    data   = request.get_json() or {}
    packer = data.get('packer', PICKERS[0])

    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()

    try:
        cursor.execute("SELECT COUNT(*) FROM packing_records WHERE order_number=?", (order_number,))
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO packing_records (order_number, packed_by, packing_status, qc_status, started_at, created_at)
                VALUES (?,?,?,?,?,?)
            """, (order_number, packer, 'PACKING', 'PENDING', now.isoformat(), now.isoformat()))
        else:
            cursor.execute("UPDATE packing_records SET packing_status='PACKING', packed_by=?, started_at=? WHERE order_number=?",
                           (packer, now.isoformat(), order_number))

        cursor.execute("UPDATE orders SET status='PACKING' WHERE order_number=?", (order_number,))
        log_activity(cursor, f"Packing started for Order {order_number} by {packer}.", 'Packing', 'success')
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Packing started for {order_number}.'})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

@app.route('/packing/<order_number>/complete', methods=['POST'])
def complete_packing(order_number):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()

    try:
        cursor.execute("UPDATE packing_records SET packing_status='COMPLETED', completed_at=? WHERE order_number=?",
                       (now.isoformat(), order_number))
        cursor.execute("UPDATE orders SET status='QC' WHERE order_number=? AND status='PACKING'", (order_number,))
        log_activity(cursor, f"Packing completed for Order {order_number}. Moved to QC.", 'Packing', 'success')
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Packing complete. Order {order_number} moved to QC.'})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

@app.route('/packing/<order_number>/qc-pass', methods=['POST'])
def qc_pass(order_number):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()

    try:
        cursor.execute("UPDATE packing_records SET qc_status='PASSED', qc_passed_at=? WHERE order_number=?",
                       (now.isoformat(), order_number))
        cursor.execute("UPDATE orders SET status='READY_TO_DISPATCH' WHERE order_number=?", (order_number,))

        # Create dispatch record
        cursor.execute("SELECT COUNT(*) FROM dispatch_records WHERE order_number=?", (order_number,))
        if cursor.fetchone()[0] == 0:
            courier = random.choice(COURIERS)
            tracking = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            cursor.execute("""
                INSERT INTO dispatch_records (order_number, courier, tracking_number, ready_at, dispatch_status)
                VALUES (?,?,?,?,?)
            """, (order_number, courier, tracking, now.isoformat(), 'READY'))

        log_activity(cursor, f"QC PASSED for Order {order_number}. Ready to dispatch.", 'QC', 'success')
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'QC passed. Order {order_number} is READY TO DISPATCH.'})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

@app.route('/packing/<order_number>/qc-fail', methods=['POST'])
def qc_fail(order_number):
    data   = request.get_json() or {}
    reason = (data.get('reason') or 'QC failure detected.').strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    now    = datetime.now()
    exc_id = generate_exception_id(conn)

    cursor.execute("UPDATE packing_records SET qc_status='FAILED', qc_failed_at=?, qc_fail_reason=? WHERE order_number=?",
                   (now.isoformat(), reason, order_number))
    cursor.execute("UPDATE orders SET status='QC' WHERE order_number=?", (order_number,))

    cursor.execute("""
        INSERT INTO exceptions (exception_id, exception_type, severity, order_number, sku, description,
            system_decision, recommended_action, expected_impact, status, detected_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (exc_id, 'QC_FAILURE', 'HIGH', order_number, None,
          f"QC failure for Order {order_number}: {reason}",
          'Hold order and investigate root cause before dispatch.',
          'Remove faulty items, re-pack order, re-run QC check.',
          'Prevents defective goods from reaching customer.',
          'OPEN', now.isoformat()))

    log_activity(cursor, f"QC FAILED for Order {order_number}: {reason}. Exception {exc_id} created.", 'QC', 'error')
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'exception_id': exc_id, 'message': f'QC failure logged. Exception {exc_id} created.'})

# ── DISPATCH ──────────────────────────────────────────────────────────────────

@app.route('/dispatch')
def dispatch_list():
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    
    cursor.execute("""
        SELECT dr.*, o.customer_name, o.items_summary, o.customer_priority, o.total_value,
               o.delivery_deadline
        FROM dispatch_records dr
        LEFT JOIN orders o ON dr.order_number = o.order_number
        ORDER BY dr.ready_at DESC
    """)
    db_dispatch = [dict(r) for r in cursor.fetchall()]

    for d in db_dispatch:
        for field in ('ready_at', 'dispatch_started_at', 'dispatched_at'):
            if d.get(field):
                try:
                    d[f"{field}_formatted"] = datetime.fromisoformat(d[field]).strftime('%b %d, %I:%M %p')
                except Exception:
                    d[f"{field}_formatted"] = d[field]
            else:
                d[f"{field}_formatted"] = '—'
        
        # ── DISPATCH DELAY DETECTION ──────────────────────────────────────────
        # Check if order is ready for dispatch but hasn't been dispatched for too long
        if d['dispatch_status'] == 'READY':
            if d.get('ready_at'):
                try:
                    ready_dt = datetime.fromisoformat(d['ready_at'])
                    waiting_minutes = round((now - ready_dt).total_seconds() / 60)
                    d['waiting_minutes'] = waiting_minutes
                    
                    # If waiting more than 30 minutes, flag as potentially delayed
                    if waiting_minutes > 30:
                        d['dispatch_risk'] = 'AT RISK'
                        
                        # Create exception if not already created
                        cursor.execute("""
                            SELECT COUNT(*) FROM exceptions 
                            WHERE exception_type='DISPATCH_DELAY' AND order_number=?
                        """, (d['order_number'],))
                        if cursor.fetchone()[0] == 0:
                            exc_id = generate_exception_id(conn)
                            cursor.execute("""
                                INSERT INTO exceptions (exception_id, exception_type, severity, order_number, sku, 
                                    description, system_decision, recommended_action, expected_impact, status, detected_at)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                            """, (exc_id, 'DISPATCH_DELAY', 'MEDIUM', d['order_number'], None,
                                  f"Order {d['order_number']} ready for dispatch for {waiting_minutes} minutes",
                                  'Prioritize dispatch to meet customer delivery deadline.',
                                  'Assign courier immediately and start dispatch.',
                                  'Ensures on-time delivery.',
                                  'OPEN', now.isoformat()))
                            log_activity(cursor, f"Dispatch delay exception created for {d['order_number']}. Waiting {waiting_minutes} min.", 'System', 'warning')
                    else:
                        d['dispatch_risk'] = 'ON_TRACK'
                except Exception:
                    d['waiting_minutes'] = 0
                    d['dispatch_risk'] = 'UNKNOWN'
            else:
                d['waiting_minutes'] = 0
                d['dispatch_risk'] = 'UNKNOWN'
        else:
            d['dispatch_risk'] = 'N/A'
    
    # Commit any exception writes once through the SQLite connection, not via a raw cursor COMMIT.
    try:
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    kpi = {
        'ready':        sum(1 for d in db_dispatch if d['dispatch_status'] == 'READY'),
        'dispatching':  sum(1 for d in db_dispatch if d['dispatch_status'] == 'DISPATCHING'),
        'dispatched':   sum(1 for d in db_dispatch if d['dispatch_status'] == 'DISPATCHED'),
        'delayed':      sum(1 for d in db_dispatch if d.get('dispatch_risk') == 'AT RISK'),
        'total':        len(db_dispatch),
    }

    conn.close()
    return render_template('dispatch.html', dispatch_records=db_dispatch, kpi=kpi)

@app.route('/dispatch/<order_number>/start', methods=['POST'])
def start_dispatch(order_number):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute("SELECT * FROM dispatch_records WHERE order_number=?", (order_number,))
    rec = cursor.fetchone()
    if not rec:
        conn.close()
        return jsonify({'success': False, 'error': 'Dispatch record not found.'}), 404

    cursor.execute("UPDATE dispatch_records SET dispatch_status='DISPATCHING', dispatch_started_at=? WHERE order_number=?",
                   (now.isoformat(), order_number))
    cursor.execute("UPDATE orders SET status='DISPATCHING' WHERE order_number=? AND status='READY_TO_DISPATCH'", (order_number,))
    log_activity(cursor, f"Dispatch initiated for Order {order_number}.", 'Carrier', 'info')
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'Dispatch started for {order_number}.'})

@app.route('/dispatch/<order_number>/complete', methods=['POST'])
def complete_dispatch(order_number):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()

    try:
        cursor.execute("UPDATE dispatch_records SET dispatch_status='DISPATCHED', dispatched_at=? WHERE order_number=?",
                       (now.isoformat(), order_number))
        cursor.execute("UPDATE orders SET status='DISPATCHED' WHERE order_number=?", (order_number,))
        log_activity(cursor, f"Order {order_number} successfully dispatched.", 'Carrier', 'success')
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Order {order_number} marked as DISPATCHED.'})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

# ── ANALYTICS ─────────────────────────────────────────────────────────────────

@app.route('/analytics')
def analytics():
    conn = get_db_connection()
    cursor = conn.cursor()
    current_time = datetime.now()

    cursor.execute("SELECT * FROM orders")
    db_orders = [dict(r) for r in cursor.fetchall()]
    for o in db_orders:
        o.update(calculate_priority(o, current_time))

    total_orders      = len(db_orders)
    dispatched        = sum(1 for o in db_orders if o['status'] == 'DISPATCHED')
    at_risk           = sum(1 for o in db_orders if o['risk_badge'] in ('AT RISK', 'WARNING'))
    fulfillment_rate  = round(dispatched / total_orders * 100, 1) if total_orders > 0 else 0

    # Orders by status
    status_counts = {}
    for o in db_orders:
        status_counts[o['status']] = status_counts.get(o['status'], 0) + 1

    # Orders by priority
    priority_counts = {}
    for o in db_orders:
        priority_counts[o['priority_level']] = priority_counts.get(o['priority_level'], 0) + 1

    # Inventory health
    cursor.execute("SELECT * FROM inventory")
    db_inv = [dict(r) for r in cursor.fetchall()]
    inv_health = {'HEALTHY': 0, 'LOW STOCK': 0, 'CRITICAL': 0, 'OUT OF STOCK': 0}
    for item in db_inv:
        status, _ = get_inventory_status(item['available_quantity'], item['reorder_level'], item['sku'])
        inv_health[status] = inv_health.get(status, 0) + 1

    # Exception distribution
    cursor.execute("SELECT * FROM exceptions")
    db_exc = [dict(r) for r in cursor.fetchall()]
    exc_types  = {}
    exc_status = {'OPEN': 0, 'IN_PROGRESS': 0, 'RESOLVED': 0, 'OVERRIDDEN': 0}
    for e in db_exc:
        exc_types[e['exception_type']]  = exc_types.get(e['exception_type'], 0) + 1
        exc_status[e['status']]         = exc_status.get(e['status'], 0) + 1

    # QC pass rate
    cursor.execute("SELECT COUNT(*) FROM packing_records WHERE qc_status='PASSED'")
    qc_passed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM packing_records WHERE qc_status IN ('PASSED','FAILED')")
    qc_total  = cursor.fetchone()[0]
    qc_rate   = round(qc_passed / qc_total * 100, 1) if qc_total > 0 else 0

    # Bottleneck data (mock stage times for the demo)
    stage_metrics = {
        'Picking':  {'avg_minutes': 18, 'target_minutes': 12, 'order_count': sum(1 for o in db_orders if o['status'] == 'PICKING')},
        'Packing':  {'avg_minutes': 9,  'target_minutes': 10, 'order_count': sum(1 for o in db_orders if o['status'] == 'PACKING')},
        'QC':       {'avg_minutes': 6,  'target_minutes': 8,  'order_count': sum(1 for o in db_orders if o['status'] == 'QC')},
        'Dispatch': {'avg_minutes': 7,  'target_minutes': 10, 'order_count': sum(1 for o in db_orders if o['status'] == 'READY_TO_DISPATCH')},
    }
    bottleneck = detect_bottleneck(stage_metrics)

    conn.close()

    return render_template('analytics.html',
        total_orders=total_orders,
        dispatched=dispatched,
        at_risk=at_risk,
        fulfillment_rate=fulfillment_rate,
        qc_rate=qc_rate,
        status_counts=status_counts,
        priority_counts=priority_counts,
        inv_health=inv_health,
        exc_types=exc_types,
        exc_status=exc_status,
        stage_metrics=stage_metrics,
        bottleneck=bottleneck,
    )

# ── GLOBAL SEARCH ─────────────────────────────────────────────────────────────

@app.route('/search')
def search():
    q = (request.args.get('q') or '').strip()
    if not q:
        return render_template('search_results.html', query=q, results={'orders': [], 'inventory': [], 'exceptions': []})

    conn = get_db_connection()
    cursor = conn.cursor()
    like   = f'%{q}%'

    cursor.execute("""
        SELECT * FROM orders WHERE order_number LIKE ? OR customer_name LIKE ? OR items_summary LIKE ?
        ORDER BY id DESC LIMIT 10
    """, (like, like, like))
    orders = [dict(r) for r in cursor.fetchall()]
    current_time = datetime.now()
    for o in orders:
        o.update(calculate_priority(o, current_time))

    cursor.execute("""
        SELECT * FROM inventory WHERE sku LIKE ? OR name LIKE ? OR category LIKE ?
        ORDER BY name LIMIT 10
    """, (like, like, like))
    inventory = [dict(r) for r in cursor.fetchall()]
    for item in inventory:
        status, badge = get_inventory_status(item['available_quantity'], item['reorder_level'], item['sku'])
        item['status'] = status
        item['status_badge'] = badge

    cursor.execute("""
        SELECT * FROM exceptions WHERE exception_id LIKE ? OR order_number LIKE ? OR exception_type LIKE ? OR description LIKE ?
        ORDER BY detected_at DESC LIMIT 10
    """, (like, like, like, like))
    exceptions = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return render_template('search_results.html', query=q, results={
        'orders': orders, 'inventory': inventory, 'exceptions': exceptions
    })

# ── ERROR HANDLERS ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message="Page or record not found."), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message="An internal server error occurred."), 500

# ── REORDER RECOMMENDATION ────────────────────────────────────────────────────

@app.route('/inventory/<sku>/reorder', methods=['POST'])
def create_reorder(sku):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory WHERE sku=?", (sku,))
    item = cursor.fetchone()
    if not item:
        conn.close()
        return jsonify({'success': False, 'error': 'SKU not found.'}), 404

    try:
        item = dict(item)
        qty  = calculate_reorder_recommendation(item)
        now  = datetime.now()

        cursor.execute("""
            INSERT INTO reorder_recommendations (sku, recommended_qty, current_available,
                daily_demand, lead_time_days, safety_stock, status, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (sku, qty, item['available_quantity'], item['daily_demand'],
              item['lead_time_days'], item['safety_stock'], 'OPEN', now.isoformat()))
        log_activity(cursor, f"Reorder recommendation created for {sku}: {qty} units needed.", 'System', 'info')
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'sku': sku, 'recommended_qty': qty, 'message': f'Reorder recommendation for {sku}: {qty} units created.'})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
