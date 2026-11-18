const STORAGE_KEY = 'caremax-demo-v1';
const API_BASE = '/api';

const initialData = {
    products: [],
    sales: [],
    invoices: [],
    reportData: null
};

let state = JSON.parse(JSON.stringify(initialData));
let cart = [];
let editingProductId = null;
let stkPushResolver = null;
let pendingOwnerSection = null;
let currentSection = 'dashboard';
let ownerLoggedIn = false;
let firstAdminSetup = false;
let currentUserRole = null;
let authStatusAvailable = false;

function loadLocalState() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
        try {
            return JSON.parse(saved);
        } catch (e) {
            console.warn('Invalid saved state, using defaults');
        }
    }
    return JSON.parse(JSON.stringify(initialData));
}

function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

async function refreshAuthStatus() {
    let status;
    try {
        status = await apiRequest('/auth/status');
        authStatusAvailable = true;
    } catch (error) {
        console.warn('CareMax authentication service unavailable:', error.message);
        authStatusAvailable = false;
        status = { authenticated: false, setupRequired: false };
    }
    ownerLoggedIn = status.authenticated;
    firstAdminSetup = status.setupRequired;
    currentUserRole = status.role || null;
    const title = document.querySelector('#authOverlay h2');
    const description = document.querySelector('#authOverlay .small');
    const button = document.querySelector('#authOverlay .btn-primary');
    title.textContent = !authStatusAvailable ? 'Service Unavailable' : firstAdminSetup ? 'Create Owner Account' : 'Owner Login';
    description.textContent = !authStatusAvailable
        ? 'CareMax could not check whether an account exists. Refresh the page before trying again.'
        : firstAdminSetup
        ? 'Set a strong owner password. It is stored securely in the CareMax database.'
        : 'Sign in to manage inventory, billing, reports, and patient records.';
    button.textContent = !authStatusAvailable ? 'Try again after refresh' : firstAdminSetup ? 'Create account' : 'Login';
    button.disabled = !authStatusAvailable;
    document.getElementById('ownerUsername').value = status.username || status.setupUsername
        || localStorage.getItem('caremax-last-username') || '';
    document.getElementById('ownerUsernameField').classList.toggle('hidden', status.authenticated);
    document.getElementById('ownerUsername').readOnly = firstAdminSetup;
    document.getElementById('ownerUsername').disabled = status.authenticated;
}

async function apiRequest(path, options = {}) {
    const response = await fetch(API_BASE + path, {
        headers: { 'Content-Type': 'application/json' },
        ...options
    });
    const data = await response.json();
    if (response.status === 401 && !path.startsWith('/auth/')) {
        ownerLoggedIn = false;
        updateAuthUI();
    }
    if (!response.ok) {
        throw new Error(data.error || 'Request failed');
    }
    return data;
}

async function loadDataFromAPI() {
    try {
        if (!ownerLoggedIn) {
            state = { ...initialData, products: await apiRequest('/products') };
            saveState();
            return;
        }
        if (currentUserRole === 'cashier') {
            state = { ...initialData, products: await apiRequest('/products') };
            saveState();
            return;
        }
        const [products, sales, invoices, reportData] = await Promise.all([
            apiRequest('/products'), apiRequest('/sales'), apiRequest('/invoices'), apiRequest('/reports')
        ]);
        state = { products, sales, invoices, reportData };
        saveState();
    } catch (error) {
        console.warn('API unavailable:', error.message);
        state = ownerLoggedIn ? loadLocalState() : { ...initialData };
    }
}

function getCustomerName(id) {
    const invoice = state.invoices.find((x) => x.id === id);
    return invoice ? invoice.id : 'Walk-in';
}

function formatCurrency(value) {
    return 'KSh ' + Number(value).toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function uniqueId(prefix) {
    return prefix + '-' + Math.floor(1000 + Math.random() * 9000);
}

const SECTION_ROLES = {
    inventory: ['admin', 'pharmacist'],
    billing: ['admin', 'pharmacist', 'viewer'],
    reports: ['admin', 'pharmacist', 'viewer']
};

function showSection(section) {
    if (!canOpenSection(section)) {
        pendingOwnerSection = section;
        if (!ownerLoggedIn) {
            showAuthModal();
        } else {
            showSection('dashboard');
        }
        return;
    }

    currentSection = section;
    document.querySelectorAll('[id$="-section"]').forEach((el) => el.classList.add('hidden'));
    document.getElementById(section + '-section').classList.remove('hidden');
    document.querySelectorAll('.nav-btn').forEach((btn) => btn.classList.remove('active'));
    document.querySelector(`[data-section="${section}"]`)?.classList.add('active');

    if (section === 'pos') renderPos();
    if (section === 'dashboard') renderDashboard();
    if (section === 'inventory') renderInventory();
    if (section === 'billing') renderBilling();
    if (section === 'reports') renderReports();
    if (section === 'users') loadUsers();
}

function isOwnerSection(section) {
    return document.querySelector(`.nav-btn[data-section="${section}"]`)?.dataset.ownerOnly === 'true';
}

function canOpenSection(section) {
    if (!isOwnerSection(section)) return true;
    if (!ownerLoggedIn) return false;
    const roles = SECTION_ROLES[section];
    return !roles || roles.includes(currentUserRole);
}

function updateAuthUI() {
    document.getElementById('ownerLoginBtn').classList.toggle('hidden', ownerLoggedIn);
    document.getElementById('ownerLogoutBtn').classList.toggle('hidden', !ownerLoggedIn);
    const isAdmin = currentUserRole === 'admin';
    document.getElementById('usersNav').classList.toggle('hidden', !isAdmin);
    document.querySelectorAll('.nav-btn[data-owner-only="true"]').forEach((btn) => {
        const allowed = ownerLoggedIn && (SECTION_ROLES[btn.dataset.section] || []).includes(currentUserRole);
        if (allowed) {
            btn.classList.remove('disabled');
            btn.removeAttribute('disabled');
        } else {
            btn.classList.add('disabled');
            btn.setAttribute('disabled', 'true');
        }
    });
}

function showAuthModal() {
    document.getElementById('authOverlay').classList.remove('hidden');
    const error = document.getElementById('authError');
    error.style.display = 'none';
    error.textContent = '';
    const passwordInput = document.getElementById('ownerPassword');
    passwordInput.value = '';
    passwordInput.focus();
}

function hideAuthModal() {
    document.getElementById('authOverlay').classList.add('hidden');
    const error = document.getElementById('authError');
    error.style.display = 'none';
    error.textContent = '';
}

async function validateOwnerLogin() {
    if (!authStatusAvailable) return;
    const password = document.getElementById('ownerPassword').value;
    const username = document.getElementById('ownerUsername').value.trim() || 'admin';
    const error = document.getElementById('authError');
    error.style.display = 'none';
    try {
        const endpoint = firstAdminSetup ? '/auth/setup' : '/auth/login';
        const result = await apiRequest(endpoint, { method: 'POST', body: JSON.stringify({ username, password }) });
        localStorage.setItem('caremax-last-username', username);
        ownerLoggedIn = true;
        currentUserRole = result.user?.role || 'admin';
        hideAuthModal();
        updateAuthUI();
        if (pendingOwnerSection) {
            const next = pendingOwnerSection;
            pendingOwnerSection = null;
            showSection(next);
        }
        await loadDataFromAPI();
        renderDashboard(); renderInventory(); renderBilling(); renderReports();
    } catch (e) {
        error.style.display = 'block';
        error.textContent = e.message;
    }
}

async function logoutOwner() {
    try { await apiRequest('/auth/logout', { method: 'POST', body: '{}' }); } catch (e) { console.warn(e); }
    ownerLoggedIn = false;
    currentUserRole = null;
    await loadDataFromAPI();
    updateAuthUI();
    renderDashboard(); renderPos();
    if (isOwnerSection(currentSection)) {
        showSection('dashboard');
    }
    alert('Owner access revoked. Restricted sections are now locked.');
}

function renderDashboard() {
    const totalProducts = state.products.length;
    const lowStockItems = state.products.filter((p) => p.stock < 10).length;
    const inventoryValue = state.products.reduce((sum, p) => sum + p.price * p.stock, 0);
    const todaySales = state.sales
        .filter((s) => new Date(s.createdAt).toDateString() === new Date().toDateString())
        .reduce((sum, s) => sum + s.amount, 0);

    document.getElementById('totalProducts').textContent = totalProducts;
    document.getElementById('lowStockItems').textContent = lowStockItems;
    document.getElementById('inventoryValue').textContent = formatCurrency(inventoryValue);
    document.getElementById('todaySales').textContent = formatCurrency(todaySales);

    document.getElementById('recentSalesTable').innerHTML = state.sales.slice(0, 5).map((sale) => `
    <tr>
      <td>${sale.id}</td>
      <td>${sale.paymentMethod}</td>
      <td>${formatCurrency(sale.amount)}</td>
      <td>${new Date(sale.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
    </tr>
  `).join('');

    document.getElementById('lowStockTable').innerHTML = state.products
        .filter((p) => p.stock < 10)
        .map((p) => `
      <tr>
        <td>${escapeHtml(p.name)}</td>
        <td>${p.stock}</td>
        <td>${escapeHtml(p.category)}</td>
        <td>${['admin','pharmacist'].includes(currentUserRole) ? `<button class="btn btn-secondary btn-small" onclick="restockProduct(${p.id})">Restock</button>` : ''}</td>
      </tr>
    `).join('');
}

function restockProduct(productId) {
    if (!['admin','pharmacist'].includes(currentUserRole)) {
        showAuthModal();
        return;
    }
    showSection('inventory');
    const selector=document.getElementById('stockPushProduct');
    selector.value=String(productId);
    document.getElementById('stockReceiptPanel').scrollIntoView({behavior:'smooth',block:'center'});
    document.getElementById('stockPushQty').focus();
}

function renderInventory() {
    document.getElementById('inventoryTable').innerHTML = state.products.map((p) => `
    <tr>
      <td>${p.sku}</td>
      <td>${p.name}</td>
      <td>${p.category}</td>
      <td>${formatCurrency(p.price)}</td>
    <td>${p.costPrice == null ? 'Not set' : formatCurrency(p.costPrice)}</td>
    <td>${p.prescriptionRequired ? 'Prescription required' : 'Non-prescription'}</td>
      <td>${p.stock}</td>
      <td>${p.expiry || 'N/A'}</td>
            <td><button class="btn btn-secondary btn-small" onclick="restockProduct(${p.id})">Restock</button> <button class="btn btn-secondary btn-small" onclick="editProduct(${p.id})">Edit</button></td>
    </tr>
  `).join('');
}

function renderBilling() {
    document.getElementById('billingTable').innerHTML = state.invoices.map((i) => `
    <tr>
      <td>${i.id}</td>
      <td>${i.paymentMethod}</td>
      <td>${formatCurrency(i.total)}</td>
      <td>${i.paymentMethod}</td>
      <td>${i.status}</td>
      <td>${new Date(i.createdAt).toLocaleDateString()}</td>
    </tr>
  `).join('');
}

function editProduct(productId) {
    const product = state.products.find((item) => String(item.id) === String(productId));
    if (!product) return;
    editingProductId = product.id;
    document.getElementById('inventoryProductId').value = product.id;
    document.getElementById('inventoryName').value = product.name;
    document.getElementById('inventorySku').value = product.sku;
    document.getElementById('inventoryCategory').value = product.category || '';
    document.getElementById('inventoryPrice').value = product.price;
    document.getElementById('inventoryExpiry').value = product.expiry || '';
    document.getElementById('inventoryPrescription').value = product.prescriptionRequired ? '1' : '0';
    document.getElementById('inventoryCostField').classList.add('hidden');
    document.getElementById('inventoryStockField').classList.add('hidden');
    document.getElementById('inventoryCostPrice').required = false;
    document.getElementById('inventoryStock').required = false;
    document.getElementById('inventoryFormTitle').textContent = 'Edit Product';
    document.getElementById('inventorySubmit').textContent = 'Save Changes';
    document.getElementById('cancelProductEdit').classList.remove('hidden');
    showSection('inventory');
    document.getElementById('inventoryName').focus();
}

function cancelProductEdit() {
    editingProductId = null;
    document.getElementById('inventoryForm').reset();
    document.getElementById('inventoryCostField').classList.remove('hidden');
    document.getElementById('inventoryStockField').classList.remove('hidden');
    document.getElementById('inventoryCostPrice').required = true;
    document.getElementById('inventoryStock').required = true;
    document.getElementById('inventoryFormTitle').textContent = 'Add Product';
    document.getElementById('inventorySubmit').textContent = 'Add Product';
    document.getElementById('cancelProductEdit').classList.add('hidden');
}

function renderReports() {
    const topProducts = [...state.products].sort((a, b) => b.stock - a.stock).slice(0, 5);
    document.getElementById('topProductsReport').innerHTML = topProducts.map((p) => `<div class="small">• ${p.name} — ${p.stock} in stock</div>`).join('');

    const revenue = state.sales.reduce((sum, s) => sum + s.amount, 0);
    document.getElementById('revenueReport').innerHTML = `<h2 style="margin:0;">${formatCurrency(revenue)}</h2><div class="small">Across ${state.sales.length} sales</div>`;

    const profit = state.reportData;
    document.getElementById('profitReport').innerHTML = profit
        ? `<h2 class="margin-reset">${formatCurrency(profit.grossProfit)}</h2><div class="small">${profit.unknownCostLines} sale lines have unknown cost</div>`
        : '<div class="small">Profit data is available when connected to the Python service.</div>';

    document.getElementById('stockAlertsReport').innerHTML = state.products
        .filter((p) => p.stock < 10)
        .map((p) => `<div class="small">• ${p.name} — ${p.stock} left</div>`)
        .join('');
}

function renderPos() {
    const search = document.getElementById('productSearch').value.toLowerCase();
    const productGrid = document.getElementById('productGrid');
    const categoryFilter = document.getElementById('categoryFilter');
    const stockPushProduct = document.getElementById('stockPushProduct');

    const selectedCategory = categoryFilter.value;
    const categories = [...new Set(state.products.map((product) => product.category).filter(Boolean))].sort();
    categoryFilter.innerHTML = '<option value="">All categories</option>' + categories.map((category) =>
        `<option value="${category}" ${category === selectedCategory ? 'selected' : ''}>${category}</option>`
    ).join('');

    const currentStockValue = stockPushProduct.value;
    stockPushProduct.innerHTML = state.products.map((p) => `<option value="${p.id}" ${String(p.id) === currentStockValue ? 'selected' : ''}>${p.name} (${p.sku})</option>`).join('');
    if (!stockPushProduct.value && state.products.length) {
        stockPushProduct.value = String(state.products[0].id);
    }

        const filtered = state.products.filter((p) =>
                (!selectedCategory || p.category === selectedCategory) &&
                (p.name.toLowerCase().includes(search) || p.sku.toLowerCase().includes(search))
        );
    productGrid.innerHTML = filtered.map((p) => `
    <div class="product-card" onclick="addToCart(${p.id})">
      <strong>${p.name}</strong>
      <div class="small">${p.sku} • ${p.category}</div>
      <div style="margin-top: 6px; font-weight:700;">${formatCurrency(p.price)}</div>
      <div class="small">In stock: ${p.stock}</div>
            ${p.prescriptionRequired ? '<span class="product-status rx-status">Prescription required</span>' : ''}
            ${isProductExpired(p) ? '<span class="product-status expired-status">Expired; sale blocked</span>' : ''}
    </div>
  `).join('');
    updateCartUI();
}

function isProductExpired(product) {
    return Boolean(product.expiry && product.expiry < new Date().toISOString().slice(0, 10));
}

function addToCart(productId) {
    const product = state.products.find((p) => String(p.id) === String(productId));
    if (!product || product.stock <= 0) return;
    if (isProductExpired(product)) {
        alert(`${product.name} is expired and cannot be sold.`);
        return;
    }
    const existing = cart.find((item) => String(item.productId) === String(product.id));
    if (existing) {
        existing.quantity += 1;
    } else {
        cart.push({ productId: product.id, quantity: 1 });
    }
    updateCartUI();
}

function changeQty(productId, delta) {
    const item = cart.find((i) => String(i.productId) === String(productId));
    if (!item) return;
    item.quantity += delta;
    if (item.quantity <= 0) cart = cart.filter((i) => String(i.productId) !== String(productId));
    updateCartUI();
}

function getCartItems() {
    return cart.map((item) => {
        const product = state.products.find((p) => String(p.id) === String(item.productId));
        return { ...item, product };
    }).filter((item) => item.product);
}

function updateCartUI() {
    const items = getCartItems();
    const cartContainer = document.getElementById('cartItems');
    const subtotalEl = document.getElementById('subtotal');
    const taxEl = document.getElementById('tax');
    const totalEl = document.getElementById('total');
    const needsPrescriptionVerification = items.some((item) => item.product.prescriptionRequired);
    document.getElementById('prescriptionCheckWrap').classList.toggle('hidden', !needsPrescriptionVerification);
    if (!needsPrescriptionVerification) document.getElementById('prescriptionVerified').checked = false;

    if (!items.length) {
        cartContainer.innerHTML = '<div class="small">Cart is empty</div>';
        subtotalEl.textContent = '0.00';
        taxEl.textContent = '0.00';
        totalEl.textContent = '0.00';
        return;
    }

    cartContainer.innerHTML = items.map((item) => `
    <div class="cart-item">
      <div>
        <strong>${item.product.name}</strong>
        <div class="small">${formatCurrency(item.product.price)}</div>
      </div>
      <div class="qty-controls">
        <button onclick="changeQty(${item.product.id}, -1)">−</button>
        <span>${item.quantity}</span>
        <button onclick="changeQty(${item.product.id}, 1)">+</button>
      </div>
      <button class="btn btn-danger" style="padding: 6px 10px;" onclick="removeFromCart(${item.product.id})">Remove</button>
    </div>
  `).join('');

    const subtotal = items.reduce((sum, item) => sum + item.product.price * item.quantity, 0);
    const discount = Number(document.getElementById('discountInput').value || 0);
    const tax = 0;
    const discountedTotal = Math.round(subtotal - (subtotal * discount / 100) + tax);
    subtotalEl.textContent = formatCurrency(subtotal);
    taxEl.textContent = formatCurrency(tax);
    totalEl.textContent = formatCurrency(discountedTotal);
}

function removeFromCart(productId) {
    cart = cart.filter((i) => String(i.productId) !== String(productId));
    updateCartUI();
}

function showStkPushModal() {
    const modal = document.getElementById('stkPushModal');
    const input = document.getElementById('stkPhoneInput');
    if (modal) {
        modal.classList.remove('hidden');
        input.value = '';
        input.focus();
    }
}

function closeStkPushModal() {
    const modal = document.getElementById('stkPushModal');
    if (modal) modal.classList.add('hidden');
}

function cancelStkPush() {
    closeStkPushModal();
    if (stkPushResolver) {
        stkPushResolver(null);
        stkPushResolver = null;
    }
}

function confirmStkPush() {
    const input = document.getElementById('stkPhoneInput');
    const phone = input.value.trim().replace(/[\s()+-]/g, '');

    if (!/^(?:0[17]\d{8}|254[17]\d{8})$/.test(phone)) {
        alert('Enter a valid Kenyan M-Pesa number, for example 0712345678 or 254712345678.');
        return;
    }

    closeStkPushModal();
    if (stkPushResolver) {
        stkPushResolver(phone);
        stkPushResolver = null;
    }
}

function promptForStkPushPhone() {
    return new Promise((resolve) => {
        stkPushResolver = resolve;
        showStkPushModal();
    });
}

async function pushStock() {
    const productId = Number(document.getElementById('stockPushProduct').value);
    const quantity = Number(document.getElementById('stockPushQty').value);
    const unitCostText = document.getElementById('stockPushCost').value.trim();
    const unitCost = Number(unitCostText);

    if (!productId || !Number.isInteger(quantity) || quantity <= 0 || !unitCostText || !Number.isFinite(unitCost) || unitCost < 0) {
        alert('Choose a product, enter a whole-number quantity, and enter its supplier unit cost.');
        return;
    }

    try {
        await apiRequest(`/products/${productId}/stock`, {
            method: 'PUT',
            body: JSON.stringify({ quantity, unitCost })
        });
        document.getElementById('stockPushQty').value = 1;
        document.getElementById('stockPushCost').value = '';
        await loadDataFromAPI();
        renderPos();
        renderInventory();
        renderDashboard();
        renderReports();
        alert('Stock receipt recorded and on-hand quantity updated.');
    } catch (error) {
        alert(error.message);
    }
}

async function checkout() {
    if (!ownerLoggedIn) {
        showAuthModal();
        return;
    }
    const items = getCartItems();
    if (!items.length) return alert('Cart is empty');
    if (items.some((item) => item.product.prescriptionRequired) && !document.getElementById('prescriptionVerified').checked) {
        return alert('A pharmacist must verify a valid prescription before checkout.');
    }
    if (items.some((item) => isProductExpired(item.product))) {
        return alert('Expired medicine cannot be sold. Remove expired items from the cart.');
    }

    const discount = Number(document.getElementById('discountInput').value || 0);
    const paymentMethod = document.getElementById('paymentMethod').value;

    let result;
    if (paymentMethod === 'M-Pesa') {
        const phone = await promptForStkPushPhone();
        if (!phone) return;
        try {
            const request = await apiRequest('/payments/mpesa/stkpush', {
                method: 'POST',
                body: JSON.stringify({
                    items: items.map((item) => ({ productId: item.productId, quantity: item.quantity })),
                    discount,
                    phone,
                    prescriptionVerified: document.getElementById('prescriptionVerified').checked
                })
            });
            alert(`M-Pesa prompt sent to a number ending ${request.phoneLast4}. Ask the customer to enter their PIN on their phone.`);
            for (let i = 0; i < 30; i++) {
                await new Promise((resolve) => setTimeout(resolve, 3000));
                const status = await apiRequest(`/payments/mpesa/${request.paymentId}`);
                if (status.status === 'SUCCESS') {
                    result = { saleId: status.saleId, invoiceId: status.invoiceId, total: status.amount };
                    break;
                }
                if (status.status === 'FAILED') {
                    alert(status.message || 'M-Pesa payment was not completed.');
                    return;
                }
                if (status.status === 'REVIEW') {
                    alert('Safaricom reported a payment that needs reconciliation. Contact the administrator before issuing another prompt.');
                    return;
                }
            }
            if (!result) {
                alert('Payment is still pending. Do not start another prompt; check the payment status or contact the administrator.');
                return;
            }
        } catch (error) {
            alert(error.message);
            return;
        }
    } else {
      try {
        result = await apiRequest('/sales', {
            method: 'POST',
            body: JSON.stringify({
                items: items.map((item) => ({ productId: item.productId, quantity: item.quantity })),
                paymentMethod,
                discount,
                prescriptionVerified: document.getElementById('prescriptionVerified').checked
            })
        });
      } catch (error) {
        alert(error.message);
        return;
      }
    }

    try {
        cart = [];
        document.getElementById('discountInput').value = 0;
        document.getElementById('paymentMethod').value = 'Cash';
        document.getElementById('prescriptionVerified').checked = false;
        await loadDataFromAPI();
        updateCartUI();
        renderDashboard();
        renderBilling();
        renderReports();
        renderPos();
        alert(`Sale completed successfully. Receipt: ${result.saleId}${paymentMethod === 'M-Pesa' ? ` · M-Pesa receipt confirmed` : ''}`);
    } catch (error) {
        alert(error.message);
    }
}

document.querySelectorAll('.nav-btn').forEach((button) => {
    button.addEventListener('click', () => showSection(button.dataset.section));
});

document.getElementById('productSearch').addEventListener('input', renderPos);
document.getElementById('categoryFilter').addEventListener('change', renderPos);
document.getElementById('discountInput').addEventListener('input', updateCartUI);


document.getElementById('inventoryForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const payload = {
        name: form.get('name'),
        sku: form.get('sku'),
        category: form.get('category'),
        price: Number(form.get('price')),
        prescriptionRequired: Number(form.get('prescriptionRequired')),
        expiry: form.get('expiry')
    };
    const isEditing = Boolean(editingProductId);
    if (!isEditing) {
        payload.costPrice = Number(form.get('costPrice'));
        payload.stock = Number(form.get('stock'));
    }
    try {
        await apiRequest(isEditing ? `/products/${editingProductId}` : '/products', {
            method: isEditing ? 'PUT' : 'POST',
            body: JSON.stringify(payload)
        });
        await loadDataFromAPI();
        cancelProductEdit();
        renderInventory();
        renderDashboard();
        renderPos();
        renderReports();
    } catch (error) {
        alert(error.message);
    }
});

async function loadUsers() {
    if (currentUserRole !== 'admin') return;
    try {
        const users = await apiRequest('/users');
        document.getElementById('usersTable').innerHTML = users.map((user) => `<tr>
          <td>${escapeHtml(user.username)}</td><td>${escapeHtml(user.role)}</td>
          <td>${user.active ? 'Active' : 'Disabled'}</td><td>${new Date(user.created_at).toLocaleDateString()}</td>
          <td>${String(user.id) === String(users.find((u) => u.username === document.getElementById('ownerUsername').value)?.id) ? 'Current administrator' : `<select aria-label="Role for ${escapeHtml(user.username)}" onchange="changeUserRole(${user.id}, this.value)"><option value="admin" ${user.role === 'admin' ? 'selected' : ''}>Admin</option><option value="pharmacist" ${user.role === 'pharmacist' ? 'selected' : ''}>Pharmacist</option><option value="cashier" ${user.role === 'cashier' ? 'selected' : ''}>Cashier</option><option value="viewer" ${user.role === 'viewer' ? 'selected' : ''}>Viewer</option></select><button class="btn btn-secondary btn-small" onclick="toggleUser(${user.id}, ${!user.active})">${user.active ? 'Disable' : 'Enable'}</button>`}</td>
        </tr>`).join('');
    } catch (error) { document.getElementById('userManagementMessage').textContent = error.message; }
}

function escapeHtml(value) {
    const node = document.createElement('span'); node.textContent = String(value ?? ''); return node.innerHTML;
}

async function toggleUser(id, active) {
    try { await apiRequest(`/users/${id}`, { method: 'PATCH', body: JSON.stringify({ active }) }); await loadUsers(); }
    catch (error) { document.getElementById('userManagementMessage').textContent = error.message; }
}

async function changeUserRole(id, role) {
    try { await apiRequest(`/users/${id}`, { method: 'PATCH', body: JSON.stringify({ role }) }); await loadUsers(); }
    catch (error) { document.getElementById('userManagementMessage').textContent = error.message; await loadUsers(); }
}

document.getElementById('createUserForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const message = document.getElementById('userManagementMessage'); message.textContent = '';
    try {
        await apiRequest('/users', { method: 'POST', body: JSON.stringify({ username: document.getElementById('newUsername').value.trim(), password: document.getElementById('newUserPassword').value, role: document.getElementById('newUserRole').value }) });
        event.target.reset(); message.textContent = 'User created.'; await loadUsers();
    } catch (error) { message.textContent = error.message; }
});

async function bootstrap() {
    await refreshAuthStatus();
    await loadDataFromAPI();
    updateAuthUI();
    renderDashboard();
    renderInventory();
    renderBilling();
    renderReports();
    renderPos();
}

bootstrap();

function toggleAssistant(forceOpen) {
    const panel = document.getElementById('assistantPanel');
    const toggle = document.getElementById('assistantToggle');
    const isOpen = forceOpen ?? panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !isOpen);
    toggle.setAttribute('aria-expanded', String(isOpen));
    if (isOpen) document.getElementById('assistantInput').focus();
}

function appendChatMessage(message, isReply) {
    const container = document.getElementById('assistantMessages');
    const bubble = document.createElement('div');
    bubble.className = `assistant-message ${isReply ? 'assistant-reply' : 'assistant-user'}`;
    bubble.textContent = message;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
}

async function sendAssistantMessage(message) {
    const prompt = message.trim();
    if (!prompt) return;
    appendChatMessage(prompt, false);
    try {
        const result = await apiRequest('/chat', {
            method: 'POST',
            body: JSON.stringify({ message: prompt })
        });
        appendChatMessage(result.reply, true);
        if (result.section) showSection(result.section);
    } catch (error) {
        appendChatMessage(`I couldn't reach the CareMax service: ${error.message}`, true);
    }
}

document.getElementById('assistantForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = document.getElementById('assistantInput');
    const prompt = input.value;
    input.value = '';
    await sendAssistantMessage(prompt);
});

document.querySelectorAll('[data-chat-prompt]').forEach((button) => {
    button.addEventListener('click', () => sendAssistantMessage(button.dataset.chatPrompt));
});
