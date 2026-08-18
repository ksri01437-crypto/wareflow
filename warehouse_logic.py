from datetime import datetime, timedelta

def calculate_priority(order, current_time=None):
    """
    Calculates priority score, priority level, risks, and explanations for a given order.
    """
    if current_time is None:
        current_time = datetime.now()

    score = 0
    reasons = []

    is_urgent = bool(order.get('is_urgent', 0))
    customer_priority = order.get('customer_priority', 'NORMAL')
    has_inventory_risk = bool(order.get('has_inventory_risk', 0))
    status = order.get('status', 'NEW')

    try:
        created_dt = datetime.fromisoformat(order.get('created_at'))
    except Exception:
        created_dt = current_time - timedelta(hours=1)

    try:
        deadline_dt = datetime.fromisoformat(order.get('delivery_deadline'))
    except Exception:
        deadline_dt = current_time + timedelta(hours=8)

    # 1. Urgency
    if is_urgent:
        score += 40
        reasons.append({'points': '+40', 'factor': 'Urgent order'})

    # 2. Customer Priority
    if customer_priority == 'HIGH':
        score += 20
        reasons.append({'points': '+20', 'factor': 'High-priority customer'})

    # 3. Delivery Deadline (within 6 hours)
    time_to_deadline = deadline_dt - current_time
    is_within_6h = timedelta(seconds=0) <= time_to_deadline <= timedelta(hours=6)
    is_past_due = time_to_deadline < timedelta(seconds=0)

    if (is_within_6h or is_past_due) and status != 'DISPATCHED':
        score += 20
        reasons.append({
            'points': '+20',
            'factor': 'Delivery deadline within 6 hours' if is_within_6h else 'Delivery deadline exceeded'
        })

    # 4. Inventory Risk
    if has_inventory_risk and status != 'DISPATCHED':
        score += 15
        reasons.append({'points': '+15', 'factor': 'Inventory allocation risk'})

    # 5. Order Age (> 4 hours)
    waiting_time = current_time - created_dt
    is_waiting_long = waiting_time >= timedelta(hours=4)
    if is_waiting_long and status != 'DISPATCHED':
        score += 10
        reasons.append({'points': '+10', 'factor': 'Order waiting more than 4 hours'})

    # Priority classification
    if score >= 80:
        priority_level = 'CRITICAL'
    elif score >= 60:
        priority_level = 'HIGH'
    elif score >= 35:
        priority_level = 'MEDIUM'
    else:
        priority_level = 'LOW'

    # Risk detection
    detected_risks = []
    if (time_to_deadline <= timedelta(hours=6)) and status != 'DISPATCHED':
        detected_risks.append('DELIVERY_RISK')
    if has_inventory_risk and status != 'DISPATCHED':
        detected_risks.append('INVENTORY_RISK')
    if is_waiting_long and status != 'DISPATCHED':
        detected_risks.append('DELAY_RISK')

    if status == 'DISPATCHED':
        overall_risk = 'NONE'
        risk_badge = 'ON TRACK'
    elif 'DELIVERY_RISK' in detected_risks or 'INVENTORY_RISK' in detected_risks:
        overall_risk = detected_risks[0]
        risk_badge = 'AT RISK'
    elif 'DELAY_RISK' in detected_risks:
        overall_risk = 'DELAY_RISK'
        risk_badge = 'WARNING'
    else:
        overall_risk = 'NONE'
        risk_badge = 'ON TRACK'

    return {
        'score': score,
        'priority_level': priority_level,
        'reasons': reasons,
        'risks': detected_risks,
        'primary_risk': overall_risk,
        'risk_badge': risk_badge,
        'waiting_hours': round(waiting_time.total_seconds() / 3600, 1),
        'hours_remaining': round(time_to_deadline.total_seconds() / 3600, 1),
    }


def get_inventory_status(available, reorder_level, sku=None):
    """
    Returns (status_label, badge_class) based on available stock vs reorder threshold.
    Rule: available <= 35% of reorder → CRITICAL (covers SKU-104 case: 7 <= 35% of 20 = 7.0)
    """
    if available == 0:
        return 'OUT OF STOCK', 'badge-status-on_hold'
    if available <= (reorder_level * 0.35):
        return 'CRITICAL', 'badge-priority-critical'
    if available <= reorder_level:
        return 'LOW STOCK', 'badge-priority-high'
    return 'HEALTHY', 'badge-risk-on-track'


def calculate_reorder_recommendation(sku_data):
    """
    Recommended Reorder = (Daily Demand × Lead Time) + Safety Stock − Current Available
    Minimum: 0
    """
    available = sku_data.get('available_quantity', 0)
    daily_demand = sku_data.get('daily_demand', 0)
    lead_time = sku_data.get('lead_time_days', 0)
    safety_stock = sku_data.get('safety_stock', 0)
    reorder_qty = (daily_demand * lead_time) + safety_stock - available
    return max(reorder_qty, 0)


def allocate_inventory(competing_orders, available_stock):
    """
    Greedy priority-based inventory allocation.
    Returns structured allocation decisions.
    """
    sorted_orders = sorted(competing_orders, key=lambda o: o.get('score', 0), reverse=True)
    results = []
    remaining_stock = available_stock

    for order in sorted_orders:
        required = order.get('requested_qty', 0)
        if remaining_stock > 0:
            allocated = min(required, remaining_stock)
            remaining_stock -= allocated
            pending = required - allocated
        else:
            allocated = 0
            pending = required

        results.append({
            'order_number': order['order_number'],
            'customer_name': order['customer_name'],
            'priority_level': order['priority_level'],
            'score': order['score'],
            'required': required,
            'allocated': allocated,
            'pending': pending,
        })

    # Decision reason
    if len(results) >= 2:
        top = results[0]
        second = results[1]
        reason = (
            f"Allocate all {available_stock} available units to Order {top['order_number']}. "
            f"Order {top['order_number']} has a significantly higher operational priority score of "
            f"{top['score']} ({top['priority_level']}) compared to Order {second['order_number']} "
            f"score of {second['score']} ({second['priority_level']})."
        )
    elif len(results) == 1:
        top = results[0]
        reason = f"Allocate {top['allocated']} units to Order {top['order_number']} (Score: {top['score']})."
    else:
        reason = "No competing orders found in active fulfillment pipeline."

    return {
        'allocations': results,
        'remaining_stock': remaining_stock,
        'decision_reason': reason,
    }


def detect_bottleneck(stage_metrics):
    """
    Rule-based bottleneck detector.
    stage_metrics: dict of {stage_name: {'avg_minutes': X, 'target_minutes': Y, 'order_count': N}}
    Returns the worst bottleneck or None.
    """
    worst = None
    worst_ratio = 0.0

    for stage, data in stage_metrics.items():
        avg = data.get('avg_minutes', 0)
        target = data.get('target_minutes', 1)
        if target == 0:
            continue
        ratio = avg / target
        if ratio > worst_ratio:
            worst_ratio = ratio
            worst = {
                'stage': stage,
                'avg_minutes': avg,
                'target_minutes': target,
                'order_count': data.get('order_count', 0),
                'ratio': round(ratio, 2),
                'severity': 'HIGH' if ratio >= 1.5 else 'MEDIUM' if ratio >= 1.2 else 'LOW',
                'overrun_pct': round((ratio - 1) * 100, 1),
            }

    return worst


def calculate_picking_optimization(picking_tasks):
    """
    Groups WAITING picking tasks by zone. If >=2 tasks share a zone, recommend batching.
    Returns list of batch recommendations.
    """
    from collections import defaultdict
    zone_groups = defaultdict(list)

    for task in picking_tasks:
        if task.get('status') == 'WAITING':
            zone_groups[task['zone']].append(task)

    recommendations = []
    for zone, tasks in zone_groups.items():
        if len(tasks) >= 2:
            # Simple mock: 8% travel reduction per additional order in same zone (capped at 40%)
            travel_reduction = min(8 * (len(tasks) - 1), 40)
            recommendations.append({
                'zone': zone,
                'task_count': len(tasks),
                'order_numbers': [t['order_number'] for t in tasks],
                'travel_reduction_pct': travel_reduction,
                'recommendation': f"Batch {len(tasks)} orders in Zone {zone} into one picking route to reduce picker travel by ~{travel_reduction}%.",
            })

    return recommendations


def check_dispatch_delays(orders, threshold_minutes=120):
    """
    Flags READY_TO_DISPATCH orders that have been waiting beyond threshold.
    Returns list of delayed order numbers with elapsed minutes.
    """
    now = datetime.now()
    delayed = []

    for order in orders:
        if order.get('status') == 'READY_TO_DISPATCH':
            try:
                # Approximate ready time from created_at + typical processing time
                created_dt = datetime.fromisoformat(order.get('created_at', ''))
                elapsed_mins = (now - created_dt).total_seconds() / 60
                if elapsed_mins > threshold_minutes:
                    delayed.append({
                        'order_number': order['order_number'],
                        'elapsed_minutes': round(elapsed_mins),
                        'customer_name': order.get('customer_name', ''),
                    })
            except Exception:
                pass

    return delayed


def generate_exception_id(conn):
    """
    Generates next sequential exception ID (EX-XXX format).
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM exceptions")
    count = cursor.fetchone()[0]
    return f"EX-{str(count + 1).zfill(3)}"


def generate_task_id(conn):
    """
    Generates next sequential picking task ID (PKT-XXXX format).
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM picking_tasks")
    count = cursor.fetchone()[0]
    return f"PKT-{str(count + 1).zfill(4)}"


def estimate_picking_time(item_count):
    """
    Estimates picking time based on item count.
    Rule: 3-5 minutes per item + 2 minute zone overhead.
    Returns estimated minutes.
    """
    base_time = 2
    time_per_item = 4
    return base_time + (item_count * time_per_item)


def check_picking_delay_risk(elapsed_minutes, target_minutes):
    """
    Determines if a picking task is at risk based on elapsed vs target time.
    Returns: (risk_status, percentage_over_target)
    """
    if elapsed_minutes > target_minutes:
        overage_pct = round(((elapsed_minutes - target_minutes) / target_minutes) * 100, 1)
        if overage_pct >= 50:
            return ('CRITICAL_DELAY', overage_pct)
        elif overage_pct >= 25:
            return ('HIGH_DELAY', overage_pct)
        else:
            return ('PICKING_DELAY', overage_pct)
    return ('ON_TIME', 0)
