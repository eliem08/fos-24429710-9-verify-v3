// InvoiceLedger Frontend SPA Controller

let jobsCache = [];
let rulesCache = [];
let mappingsCache = [];

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initDropzone();
    initModals();
    refreshAllData();

    // Event listeners
    document.getElementById('btn-sync-samples').addEventListener('click', loadSampleInvoices);
    document.getElementById('btn-email-sync').addEventListener('click', loadSampleInvoices);
    document.getElementById('btn-export-csv').addEventListener('click', handleExportCSV);
    document.getElementById('ledger-search').addEventListener('input', filterLedger);
    document.getElementById('ledger-job-filter').addEventListener('change', filterLedger);
    document.getElementById('btn-add-rule-modal').addEventListener('click', () => openModal('rule-modal'));
    document.getElementById('btn-new-job').addEventListener('click', () => openModal('job-modal'));
    document.getElementById('rule-form').addEventListener('submit', handleAddRule);
    document.getElementById('job-form').addEventListener('submit', handleAddJob);
    document.getElementById('review-form').addEventListener('submit', handleCommitInvoice);
    document.getElementById('btn-modal-reject').addEventListener('click', handleRejectInvoice);
    document.getElementById('btn-save-mapping').addEventListener('click', handleSaveMapping);
});

// Toast notification helper
function showToast(msg, type = 'info') {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = `toast ${type}`;
    t.classList.remove('hidden');
    setTimeout(() => {
        t.classList.add('hidden');
    }, 4000);
}

// Navigation Tabs
function initTabs() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            navItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            const tabId = item.getAttribute('data-tab');

            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            const activePanel = document.getElementById(`tab-${tabId}`);
            if (activePanel) activePanel.classList.add('active');

            const titleMap = {
                intake: 'Intake & Upload',
                review: 'Human Review Queue',
                rollups: 'Job P&L Rollups',
                ledger: 'Committed Ledger',
                rules: 'Automation Rules',
                mappings: 'P&L Column Mapping'
            };
            document.getElementById('page-title').textContent = titleMap[tabId] || 'InvoiceLedger';

            // Refresh specific data
            if (tabId === 'review') loadPendingInvoices();
            if (tabId === 'rollups') loadRollups();
            if (tabId === 'ledger') loadLedger();
            if (tabId === 'rules') loadRules();
            if (tabId === 'mappings') loadMappings();
        });
    });
}

// Drag & Drop Intake
function initDropzone() {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const btnBrowse = document.getElementById('btn-browse');

    btnBrowse.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('click', () => fileInput.click());

    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files.length) uploadFiles(files);
    });

    fileInput.addEventListener('change', (e) => {
        if (fileInput.files.length) uploadFiles(fileInput.files);
    });
}

async function uploadFiles(files) {
    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
    }

    showToast(`Uploading ${files.length} file(s)...`, 'info');
    try {
        const res = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        showToast(`Successfully processed ${data.processed} invoices!`, 'success');
        
        // Append to log
        const log = document.getElementById('intake-log');
        log.innerHTML = '';
        data.results.forEach(r => {
            const item = document.createElement('div');
            item.className = 'card mt-2';
            item.style.padding = '12px';
            item.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <strong>${r.invoice.vendor_name}</strong> - #${r.invoice.invoice_number}
                        <div class="muted">${r.filename} | ${r.invoice.invoice_date}</div>
                    </div>
                    <div style="text-align:right;">
                        <span class="text-success" style="font-weight:700;">$${r.invoice.total_amount.toFixed(2)}</span>
                        <div><span class="badge ${r.invoice.status === 'committed' ? 'badge-success' : (r.invoice.status === 'duplicate' ? 'badge-danger' : 'badge-warning')}">${r.invoice.status}</span></div>
                    </div>
                </div>
            `;
            log.appendChild(item);
        });

        refreshAllData();
    } catch (err) {
        showToast('Upload failed: ' + err.message, 'error');
    }
}

async function loadSampleInvoices() {
    showToast('Loading realistic sample invoices...', 'info');
    try {
        const res = await fetch('/api/email-sync', { method: 'POST' });
        const data = await res.json();
        showToast(`Loaded ${data.processed} sample invoices!`, 'success');
        refreshAllData();
    } catch (err) {
        showToast('Error syncing: ' + err.message, 'error');
    }
}

// Refresh Master Data
async function refreshAllData() {
    loadStats();
    await loadJobs();
    loadPendingInvoices();
    loadRules();
    loadMappings();
}

async function loadStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        const sum = data.company_summary;
        document.getElementById('stat-committed-spend').textContent = `$${sum.total_committed_spend.toLocaleString(undefined, {minimumFractionDigits:2})}`;
        document.getElementById('stat-active-jobs').textContent = sum.active_jobs_count;
        
        // Count pending
        const invRes = await fetch('/api/invoices?status=pending_review');
        const pending = await invRes.json();
        document.getElementById('stat-pending-count').textContent = pending.length;
        document.getElementById('badge-pending').textContent = pending.length;

        // Count duplicate
        const dupRes = await fetch('/api/invoices?status=duplicate');
        const dups = await dupRes.json();
        document.getElementById('stat-duplicates-count').textContent = dups.length;
    } catch (e) {
        console.error(e);
    }
}

async function loadJobs() {
    try {
        const res = await fetch('/api/jobs');
        jobsCache = await res.json();

        // Populate dropdowns
        const jobSelects = [document.getElementById('modal-job'), document.getElementById('rule-job'), document.getElementById('ledger-job-filter')];
        jobSelects.forEach(sel => {
            if (!sel) return;
            const currentVal = sel.value;
            sel.innerHTML = sel.id === 'ledger-job-filter' ? '<option value="">All Jobs</option>' : '';
            jobsCache.forEach(j => {
                const opt = document.createElement('option');
                opt.value = j.name;
                opt.textContent = `${j.name} (${j.client_name || 'No Client'})`;
                sel.appendChild(opt);
            });
            if (currentVal) sel.value = currentVal;
        });
    } catch (e) {
        console.error(e);
    }
}

// Review Queue
async function loadPendingInvoices() {
    try {
        const res = await fetch('/api/invoices?status=pending_review');
        const invoices = await res.json();
        const container = document.getElementById('review-cards-container');
        container.innerHTML = '';

        if (!invoices.length) {
            container.innerHTML = '<div class="empty-state">No pending invoices in queue. All caught up! 🎉</div>';
            return;
        }

        invoices.forEach(inv => {
            const card = document.createElement('div');
            card.className = 'review-card';
            card.innerHTML = `
                <div class="review-card-header">
                    <div>
                        <div class="review-vendor">${inv.vendor_name}</div>
                        <span class="muted">Inv #${inv.invoice_number}</span>
                    </div>
                    <div class="review-amount">$${inv.total_amount.toFixed(2)}</div>
                </div>

                <div class="meta-row">
                    <span>📅 Date: <strong>${inv.invoice_date}</strong></span>
                    <span>PO: <strong>${inv.po_number || 'N/A'}</strong></span>
                </div>

                <div style="margin: 6px 0;">
                    <div class="meta-row" style="margin-bottom:4px;">
                        <span>Target Job</span>
                        <strong>${inv.job_name || '<span class="text-warning">Unassigned</span>'}</strong>
                    </div>
                    <div class="meta-row">
                        <span>Cost Code</span>
                        <strong>${inv.cost_code || '<span class="text-warning">Uncategorized</span>'}</strong>
                    </div>
                </div>

                <div>
                    <div class="meta-row" style="margin-bottom:2px;">
                        <span class="muted">Extraction Confidence</span>
                        <span><strong>${Math.round(inv.confidence_score * 100)}%</strong></span>
                    </div>
                    <div class="confidence-bar">
                        <div class="confidence-fill" style="width: ${Math.round(inv.confidence_score * 100)}%;"></div>
                    </div>
                </div>

                <div class="actions-row mt-2">
                    <button class="btn btn-primary btn-sm" onclick="openReviewModal('${inv.id}')">Review & Commit</button>
                    <button class="btn btn-outline btn-sm" onclick="quickCommit('${inv.id}')">⚡ 1-Click Approve</button>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error(e);
    }
}

async function openReviewModal(invId) {
    const res = await fetch(`/api/invoices/${invId}`);
    const inv = await res.json();

    document.getElementById('modal-inv-id').value = inv.id;
    document.getElementById('modal-vendor').value = inv.vendor_name;
    document.getElementById('modal-inv-num').value = inv.invoice_number;
    document.getElementById('modal-date').value = inv.invoice_date;
    document.getElementById('modal-amount').value = inv.total_amount;
    document.getElementById('modal-po').value = inv.po_number || '';
    if (inv.job_name) document.getElementById('modal-job').value = inv.job_name;
    if (inv.cost_code) document.getElementById('modal-cost-code').value = inv.cost_code;
    document.getElementById('modal-raw-text').textContent = inv.raw_text || 'No raw text available';

    openModal('edit-modal');
}

async function quickCommit(invId) {
    const res = await fetch(`/api/invoices/${invId}`);
    const inv = await res.json();
    const targetJob = inv.job_name || (jobsCache.length ? jobsCache[0].name : '101 Main St Remodel');
    const targetCode = inv.cost_code || '06-Framing';

    await fetch(`/api/invoices/${invId}/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            job_name: targetJob,
            cost_code: targetCode,
            save_rule: true
        })
    });
    showToast(`Committed invoice #${inv.invoice_number}!`, 'success');
    refreshAllData();
}

async function handleCommitInvoice(e) {
    e.preventDefault();
    const invId = document.getElementById('modal-inv-id').value;
    const body = {
        vendor_name: document.getElementById('modal-vendor').value,
        invoice_number: document.getElementById('modal-inv-num').value,
        invoice_date: document.getElementById('modal-date').value,
        total_amount: parseFloat(document.getElementById('modal-amount').value),
        po_number: document.getElementById('modal-po').value,
        job_name: document.getElementById('modal-job').value,
        cost_code: document.getElementById('modal-cost-code').value,
        save_rule: document.getElementById('modal-save-rule').checked
    };

    try {
        await fetch(`/api/invoices/${invId}/commit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        closeModals();
        showToast('Invoice committed & reconciled to P&L!', 'success');
        refreshAllData();
    } catch (err) {
        showToast('Commit failed: ' + err.message, 'error');
    }
}

async function handleRejectInvoice() {
    const invId = document.getElementById('modal-inv-id').value;
    if (!confirm('Are you sure you want to reject this invoice?')) return;
    await fetch(`/api/invoices/${invId}/reject`, { method: 'POST' });
    closeModals();
    showToast('Invoice rejected', 'info');
    refreshAllData();
}

// Job Rollups View
async function loadRollups() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        const container = document.getElementById('jobs-container');
        container.innerHTML = '';

        data.jobs.forEach(job => {
            const card = document.createElement('div');
            card.className = 'card';
            
            let costCodeHtml = '';
            for (const [code, cData] of Object.entries(job.cost_code_breakdown)) {
                costCodeHtml += `
                    <tr>
                        <td><strong>${code}</strong></td>
                        <td class="text-right">$${cData.budget.toLocaleString(undefined, {minimumFractionDigits:2})}</td>
                        <td class="text-right text-success">$${cData.spent.toLocaleString(undefined, {minimumFractionDigits:2})}</td>
                        <td class="text-right ${cData.remaining < 0 ? 'text-danger' : 'muted'}">$${cData.remaining.toLocaleString(undefined, {minimumFractionDigits:2})}</td>
                    </tr>
                `;
            }

            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div>
                        <h3>${job.job_name}</h3>
                        <span class="muted">${job.client_name || 'Standard Client'}</span>
                    </div>
                    <span class="badge ${job.budget_utilization_pct > 90 ? 'badge-danger' : 'badge-success'}">
                        ${job.budget_utilization_pct}% Spent
                    </span>
                </div>

                <div class="progress-bar-bg">
                    <div class="progress-fill" style="width: ${Math.min(100, job.budget_utilization_pct)}%;"></div>
                </div>

                <div class="meta-row" style="margin: 8px 0 16px 0;">
                    <span>Budget: <strong>$${job.budget_total.toLocaleString()}</strong></span>
                    <span>Committed: <strong class="text-success">$${job.committed_spend.toLocaleString(undefined, {minimumFractionDigits:2})}</strong></span>
                    <span>Remaining: <strong class="${job.remaining_budget < 0 ? 'text-danger' : ''}">$${job.remaining_budget.toLocaleString(undefined, {minimumFractionDigits:2})}</strong></span>
                </div>

                <h4 style="font-size:12px; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">Cost Code Breakdown</h4>
                <table class="data-table cost-breakdown">
                    <thead>
                        <tr>
                            <th>Cost Code</th>
                            <th class="text-right">Budget</th>
                            <th class="text-right">Spent</th>
                            <th class="text-right">Remaining</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${costCodeHtml || '<tr><td colspan="4" class="muted text-center">No cost code activity</td></tr>'}
                    </tbody>
                </table>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error(e);
    }
}

// Committed Ledger
async function loadLedger() {
    const jobFilter = document.getElementById('ledger-job-filter').value;
    const search = document.getElementById('ledger-search').value;
    let url = `/api/invoices?status=committed`;
    if (jobFilter) url += `&job_name=${encodeURIComponent(jobFilter)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    try {
        const res = await fetch(url);
        const invoices = await res.json();
        const tbody = document.getElementById('ledger-table-body');
        tbody.innerHTML = '';

        if (!invoices.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center muted">No committed invoices found matching criteria.</td></tr>';
            return;
        }

        invoices.forEach(inv => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${inv.invoice_date}</td>
                <td><strong>${inv.job_name || 'N/A'}</strong></td>
                <td><span class="badge badge-info">${inv.cost_code || 'Uncategorized'}</span></td>
                <td>${inv.vendor_name}</td>
                <td><code>#${inv.invoice_number}</code></td>
                <td>${inv.po_number || '-'}</td>
                <td class="text-right text-success"><strong>$${inv.total_amount.toFixed(2)}</strong></td>
                <td><a href="/${inv.archive_path || '#'}" target="_blank" class="muted" style="text-decoration:underline;">📁 View File</a></td>
                <td><span class="badge badge-success">Committed</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
    }
}

function filterLedger() {
    loadLedger();
}

function handleExportCSV() {
    const templateId = document.getElementById('export-template-select').value;
    const jobName = document.getElementById('ledger-job-filter').value;
    let url = `/api/export?status=committed`;
    if (templateId) url += `&template_id=${encodeURIComponent(templateId)}`;
    if (jobName) url += `&job_name=${encodeURIComponent(jobName)}`;
    window.location.href = url;
}

// Rules Engine
async function loadRules() {
    try {
        const res = await fetch('/api/rules');
        rulesCache = await res.json();
        const tbody = document.getElementById('rules-table-body');
        tbody.innerHTML = '';

        if (!rulesCache.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center muted">No routing rules defined yet.</td></tr>';
            return;
        }

        rulesCache.forEach(r => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${r.vendor_pattern}</strong></td>
                <td><span class="badge badge-info">${r.match_type}</span></td>
                <td>${r.job_name}</td>
                <td><span class="badge badge-warning">${r.cost_code}</span></td>
                <td>${r.priority}</td>
                <td><span class="badge badge-success">Active</span></td>
                <td><button class="btn btn-danger btn-sm" onclick="deleteRule('${r.id}')">Delete</button></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
    }
}

async function handleAddRule(e) {
    e.preventDefault();
    const body = {
        id: `rule-${Date.now()}`,
        vendor_pattern: document.getElementById('rule-pattern').value,
        match_type: document.getElementById('rule-match-type').value,
        job_name: document.getElementById('rule-job').value,
        cost_code: document.getElementById('rule-cost-code').value,
        priority: parseInt(document.getElementById('rule-priority').value || '50'),
        is_active: true
    };
    await fetch('/api/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    closeModals();
    showToast('Rule created!', 'success');
    loadRules();
}

async function deleteRule(ruleId) {
    if (!confirm('Delete this rule?')) return;
    await fetch(`/api/rules/${ruleId}`, { method: 'DELETE' });
    showToast('Rule removed', 'info');
    loadRules();
}

// Jobs Management
async function handleAddJob(e) {
    e.preventDefault();
    const body = {
        id: `job-${Date.now()}`,
        name: document.getElementById('job-name').value,
        client_name: document.getElementById('job-client').value,
        budget_total: parseFloat(document.getElementById('job-budget').value || '0'),
        cost_code_budgets: {
            "03-Concrete": 15000,
            "06-Framing": 30000,
            "07-Roofing": 20000,
            "15-Mechanical/Plumbing": 15000,
            "16-Electrical": 15000
        }
    };
    await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    closeModals();
    showToast('Job created!', 'success');
    refreshAllData();
}

// Column Mapping
async function loadMappings() {
    try {
        const res = await fetch('/api/mappings');
        mappingsCache = await res.json();
        
        // Populate export select
        const exportSel = document.getElementById('export-template-select');
        exportSel.innerHTML = '';
        mappingsCache.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = `${m.template_name} ${m.is_default ? '(Default)' : ''}`;
            exportSel.appendChild(opt);
        });

        // Populate editor with default template
        const defaultTpl = mappingsCache.find(m => m.is_default) || mappingsCache[0];
        if (defaultTpl) {
            const container = document.getElementById('mapping-fields-container');
            container.innerHTML = '';
            for (const [header, field] of Object.entries(defaultTpl.columns)) {
                const row = document.createElement('div');
                row.className = 'form-row';
                row.style.marginBottom = '8px';
                row.innerHTML = `
                    <div class="form-group" style="flex:1;">
                        <label>Excel Column Header</label>
                        <input type="text" class="form-control mapping-header" value="${header}">
                    </div>
                    <div class="form-group" style="flex:1;">
                        <label>Invoice Data Field</label>
                        <select class="form-control mapping-field">
                            <option value="invoice_date" ${field === 'invoice_date' ? 'selected' : ''}>Invoice Date</option>
                            <option value="job_name" ${field === 'job_name' ? 'selected' : ''}>Job Name</option>
                            <option value="cost_code" ${field === 'cost_code' ? 'selected' : ''}>Cost Code</option>
                            <option value="vendor_name" ${field === 'vendor_name' ? 'selected' : ''}>Vendor Name</option>
                            <option value="invoice_number" ${field === 'invoice_number' ? 'selected' : ''}>Invoice Number</option>
                            <option value="po_number" ${field === 'po_number' ? 'selected' : ''}>PO Number</option>
                            <option value="total_amount" ${field === 'total_amount' ? 'selected' : ''}>Total Amount ($)</option>
                            <option value="status" ${field === 'status' ? 'selected' : ''}>Status</option>
                            <option value="archive_path" ${field === 'archive_path' ? 'selected' : ''}>Audit File Path</option>
                        </select>
                    </div>
                `;
                container.appendChild(row);
            }
        }
    } catch (e) {
        console.error(e);
    }
}

async function handleSaveMapping() {
    const headers = document.querySelectorAll('.mapping-header');
    const fields = document.querySelectorAll('.mapping-field');
    const columns = {};
    headers.forEach((h, idx) => {
        if (h.value.trim()) {
            columns[h.value.trim()] = fields[idx].value;
        }
    });

    const body = {
        id: 'tpl-default',
        template_name: 'Default Contractor P&L',
        columns: columns,
        is_default: true
    };

    await fetch('/api/mappings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    showToast('Column mapping template saved!', 'success');
}

// Modal Helpers
function initModals() {
    document.querySelectorAll('.modal-close, .modal-backdrop').forEach(el => {
        el.addEventListener('click', closeModals);
    });
}

function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('hidden');
}

function closeModals() {
    document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
}
