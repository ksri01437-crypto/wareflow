// Wareflow Client Application Script

document.addEventListener('DOMContentLoaded', () => {
    // 1. Initialize Live Date/Time clock in header
    updateLiveClock();
    setInterval(updateLiveClock, 1000);
});

// Update the header display with current timezone date and time
function updateLiveClock() {
    const dateEl = document.getElementById('live-date');
    if (!dateEl) return;
    
    const now = new Date();
    const options = { 
        weekday: 'short', 
        year: 'numeric', 
        month: 'short', 
        day: '2-digit', 
        hour: '2-digit', 
        minute: '2-digit', 
        second: '2-digit',
        hour12: true 
    };
    
    // Format: "Tue, Aug 18, 2026, 10:15:30 AM"
    dateEl.textContent = now.toLocaleString('en-US', options) + ' | System Zone UTC+5:30';
}

// Spin the icon and reload the page to refresh stats from SQLite
function simulateRefresh() {
    const refreshBtn = document.querySelector('.btn-secondary');
    const refreshIcon = refreshBtn ? refreshBtn.querySelector('i') : null;
    
    if (refreshIcon) {
        refreshIcon.classList.add('bx-spin');
    }
    
    // Smooth delay before reloading so the user notices the refresh animation
    setTimeout(() => {
        window.location.reload();
    }, 450);
}

// WAREFLOW Task 2 — Client-side Operations Logic

// 1. Table Filtering Logic
function filterOrdersTable() {
    const searchVal = document.getElementById('order-search').value.toLowerCase().trim();
    const priorityVal = document.getElementById('filter-priority').value;
    const statusVal = document.getElementById('filter-status').value;
    const riskVal = document.getElementById('filter-risk').value;

    const rows = document.querySelectorAll('.order-row');
    let matchCount = 0;

    rows.forEach(row => {
        const orderId = row.getAttribute('data-order-id').toLowerCase();
        const customer = row.getAttribute('data-customer').toLowerCase();
        const priority = row.getAttribute('data-priority');
        const status = row.getAttribute('data-status');
        const risk = row.getAttribute('data-risk');

        // Search match: matches either ID or Customer
        const matchesSearch = !searchVal || orderId.includes(searchVal) || customer.includes(searchVal);
        
        // Dropdown matches
        const matchesPriority = priorityVal === 'ALL' || priority === priorityVal;
        const matchesStatus = statusVal === 'ALL' || status === statusVal;
        const matchesRisk = riskVal === 'ALL' || risk === riskVal;

        if (matchesSearch && matchesPriority && matchesStatus && matchesRisk) {
            row.style.display = '';
            matchCount++;
        } else {
            row.style.display = 'none';
        }
    });

    // Update matched count badge
    const countEl = document.getElementById('results-count');
    if (countEl) {
        countEl.textContent = `${matchCount} orders matching`;
    }

    // Toggle no-matching message
    const noMatchingEl = document.getElementById('no-matching-rows');
    if (noMatchingEl) {
        noMatchingEl.style.display = matchCount === 0 ? '' : 'none';
    }
}

// 2. Table Sorting Logic
function sortOrdersTable() {
    const sortBy = document.getElementById('sort-by').value;
    const tbody = document.getElementById('orders-tbody');
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll('.order-row'));
    
    // Priority levels map for Priority First sorting
    const priorityWeight = {
        'CRITICAL': 4,
        'HIGH': 3,
        'MEDIUM': 2,
        'LOW': 1
    };

    rows.sort((a, b) => {
        let valA, valB;

        switch (sortBy) {
            case 'priority-first':
                const prioA = priorityWeight[a.getAttribute('data-priority')] || 0;
                const prioB = priorityWeight[b.getAttribute('data-priority')] || 0;
                if (prioA !== prioB) {
                    return prioB - prioA; // Higher priority first
                }
                // If same priority, fall back to score descending
                return parseFloat(b.getAttribute('data-score')) - parseFloat(a.getAttribute('data-score'));

            case 'score-desc':
                return parseFloat(b.getAttribute('data-score')) - parseFloat(a.getAttribute('data-score'));

            case 'score-asc':
                return parseFloat(a.getAttribute('data-score')) - parseFloat(b.getAttribute('data-score'));

            case 'value-desc':
                return parseFloat(b.getAttribute('data-value')) - parseFloat(a.getAttribute('data-value'));

            case 'value-asc':
                return parseFloat(a.getAttribute('data-value')) - parseFloat(b.getAttribute('data-value'));

            case 'created-desc':
                valA = a.getAttribute('data-created');
                valB = b.getAttribute('data-created');
                return valB.localeCompare(valA); // Newest first

            case 'created-asc':
                valA = a.getAttribute('data-created');
                valB = b.getAttribute('data-created');
                return valA.localeCompare(valB); // Oldest first

            default:
                return 0;
        }
    });

    // Re-append sorted rows to the table body
    rows.forEach(row => {
        // Skip appending placeholder rows (like no matches warning)
        if (row.id !== 'no-matching-rows') {
            tbody.appendChild(row);
        }
    });
}

// ─── WAREFLOW Task 3 — Smart Allocation Modal & AJAX ───────────────────────

// Open the comparison/decision modal
function openDecisionModal() {
    const modal = document.getElementById('decision-modal');
    if (modal) modal.style.display = 'flex';
}

// Close the comparison/decision modal
function closeDecisionModal() {
    const modal = document.getElementById('decision-modal');
    if (modal) modal.style.display = 'none';
}

// Close modal on outside-click
document.addEventListener('click', (e) => {
    const modal = document.getElementById('decision-modal');
    if (modal && e.target === modal) closeDecisionModal();
});

// POST to /orders/allocate, show a toast, then reload
function executeAllocation(orderNumber, sku) {
    const acceptBtn = document.querySelector('#decision-modal .btn-primary');
    if (acceptBtn) {
        acceptBtn.disabled = true;
        acceptBtn.innerHTML = '<i class="bx bx-loader-alt bx-spin"></i> Processing…';
    }

    fetch('/orders/allocate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_number: orderNumber, sku: sku })
    })
    .then(res => res.json())
    .then(data => {
        closeDecisionModal();
        if (data.success) {
            showToast(
                `✓ Allocation accepted — ${data.allocated} units reserved for ${orderNumber}.`,
                'success'
            );
            setTimeout(() => window.location.reload(), 1200);
        } else {
            showToast(`⚠ ${data.error || 'Allocation failed.'}`, 'error');
            if (acceptBtn) {
                acceptBtn.disabled = false;
                acceptBtn.innerHTML = 'Accept Recommendation';
            }
        }
    })
    .catch(err => {
        closeDecisionModal();
        showToast('Network error — could not reach the server.', 'error');
        console.error('Allocation error:', err);
        if (acceptBtn) {
            acceptBtn.disabled = false;
            acceptBtn.innerHTML = 'Accept Recommendation';
        }
    });
}

// Toast notification helper
function showToast(message, type = 'success') {
    // Remove any existing toast
    const existing = document.getElementById('wareflow-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'wareflow-toast';
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed; bottom: 28px; right: 28px; z-index: 9999;
        padding: 14px 22px; border-radius: 10px; font-size: 14px;
        font-weight: 600; max-width: 400px; line-height: 1.4;
        box-shadow: 0 8px 32px rgba(0,0,0,0.18);
        animation: slide-up 0.3s ease;
        background-color: ${type === 'success' ? '#f0fdf4' : '#fff1f2'};
        color: ${type === 'success' ? '#15803d' : '#b91c1c'};
        border: 1px solid ${type === 'success' ? '#a7f3d0' : '#fca5a5'};
    `;

    // Inject the slide-up keyframe once
    if (!document.getElementById('toast-keyframes')) {
        const style = document.createElement('style');
        style.id = 'toast-keyframes';
        style.textContent = `
            @keyframes slide-up {
                from { opacity: 0; transform: translateY(20px); }
                to   { opacity: 1; transform: translateY(0); }
            }`;
        document.head.appendChild(style);
    }

    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.4s';
        setTimeout(() => toast.remove(), 400);
    }, 4000);
}

// ─── PICKING FUNCTIONS ──────────────────────────────────────────────────────

// Start a picking task
function startPicking(taskId) {
    const pickerSelect = prompt('Select Picker:\n\n1. Aarav\n2. Priya\n3. Rahul\n4. Ananya\n5. Vikram\n\nEnter picker name:');
    
    if (!pickerSelect) return;

    const validPickers = ['Aarav', 'Priya', 'Rahul', 'Ananya', 'Vikram'];
    const picker = validPickers.find(p => p.toLowerCase() === pickerSelect.toLowerCase());
    
    if (!picker) {
        showToast('⚠ Invalid picker name. Please try again.', 'error');
        return;
    }

    fetch(`/picking/${taskId}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ picker: picker })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            showToast(`✓ ${data.message}`, 'success');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast(`⚠ ${data.error || 'Failed to start picking.'}`, 'error');
        }
    })
    .catch(err => {
        showToast('Network error — could not reach the server.', 'error');
        console.error('Start picking error:', err);
    });
}

// Complete a picking task
function completePicking(taskId) {
    if (!confirm('Mark this picking task as completed and move to packing?')) return;

    fetch(`/picking/${taskId}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            showToast(`✓ ${data.message}`, 'success');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast(`⚠ ${data.error || 'Failed to complete picking.'}`, 'error');
        }
    })
    .catch(err => {
        showToast('Network error — could not reach the server.', 'error');
        console.error('Complete picking error:', err);
    });
}

// Open the report issue modal
function reportPickingIssue(taskId) {
    document.getElementById('issue-task-id').value = taskId;
    document.getElementById('issue-type').value = 'MISSING_ITEM';
    document.getElementById('issue-note').value = '';
    document.getElementById('picking-issue-modal').style.display = 'flex';
}

// Close the report issue modal
function closePickingIssueModal() {
    document.getElementById('picking-issue-modal').style.display = 'none';
}

// Submit a picking issue
function submitPickingIssue() {
    const taskId = document.getElementById('issue-task-id').value;
    const issueType = document.getElementById('issue-type').value;
    const note = document.getElementById('issue-note').value.trim();

    if (!note) {
        showToast('⚠ Please enter a note describing the issue.', 'error');
        return;
    }

    const submitBtn = document.querySelector('#picking-issue-modal .btn-danger');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="bx bx-loader-alt bx-spin"></i> Reporting…';
    }

    fetch(`/picking/${taskId}/report-issue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ issue_type: issueType, note: note })
    })
    .then(res => res.json())
    .then(data => {
        closePickingIssueModal();
        if (data.success) {
            showToast(`✓ ${data.message}`, 'success');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast(`⚠ ${data.error || 'Failed to report issue.'}`, 'error');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = 'Report Issue';
            }
        }
    })
    .catch(err => {
        closePickingIssueModal();
        showToast('Network error — could not reach the server.', 'error');
        console.error('Report issue error:', err);
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = 'Report Issue';
        }
    });
}

// Close modal on outside-click
document.addEventListener('click', (e) => {
    const modal = document.getElementById('picking-issue-modal');
    if (modal && e.target === modal) closePickingIssueModal();
});

