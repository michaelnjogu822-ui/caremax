const STORAGE_KEY = 'caremax-demo-v1';
const API_BASE = '/api';

const initialData = {
    products: [],
    sales: [],
    invoices: []
};

let state = JSON.parse(JSON.stringify(initialData));
let cart = [];
let stkPushResolver = null;

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

async function apiRequest(path, options = {}) {
    const response = await fetch(API_BASE + path, {
        headers: { 'Content-Type': 'application/json' },
        ...options
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error || 'Request failed');
    }
    return data;
}

async function loadDataFromAPI() {
    try {
        const [products, sales, invoices] = await Promise.all([
            apiRequest('/products'),
            apiRequest('/sales'),
            apiRequest('/invoices')
        ]);
        state = { products, sales, invoices };
        saveState();
    } catch (error) {
        console.warn('API unavailable, loading local fallback:', error.message);
        state = loadLocalState();
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

function showSection(section) {
    document.querySelectorAll('[id$="-section"]').forEach((el) => el.classList.add('hidden'));
    document.getElementById(section + '-section').classList.remove('hidden');
    document.querySelectorAll('.nav-btn').forEach((btn) => btn.classList.remove('active'));
    document.querySelector(`[data-section="${section}"]`)?.classList.add('active');

    if (section === 'pos') renderPos();
    if (section === 'dashboard') renderDashboard();
    if (section === 'inventory') renderInventory();
    if (section === 'billing') renderBilling();
    if (section === 'reports') renderReports();
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
        <td>${p.name}</td>
        <td>${p.stock}</td>
        <td>${p.category}</td>
      </tr>
    `).join('');
}

function renderInventory() {
    document.getElementById('inventoryTable').innerHTML = state.products.map((p) => `
    <tr>
      <td>${p.sku}</td>
      <td>${p.name}</td>
      <td>${p.category}</td>
      <td>${formatCurrency(p.price)}</td>
      <td>${p.stock}</td>
      <td>${p.expiry || 'N/A'}</td>
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

function renderReports() {
    const topProducts = [...state.products].sort((a, b) => b.stock - a.stock).slice(0, 5);
    document.getElementById('topProductsReport').innerHTML = topProducts.map((p) => `<div class="small">• ${p.name} — ${p.stock} in stock</div>`).join('');

    const revenue = state.sales.reduce((sum, s) => sum + s.amount, 0);
    document.getElementById('revenueReport').innerHTML = `<h2 style="margin:0;">${formatCurrency(revenue)}</h2><div class="small">Across ${state.sales.length} sales</div>`;

    document.getElementById('stockAlertsReport').innerHTML = state.products
        .filter((p) => p.stock < 10)
        .map((p) => `<div class="small">• ${p.name} — ${p.stock} left</div>`)
        .join('');
}

function renderBilling() {
    document.getElementById('billingTable').innerHTML = state.invoices.map((i) => `
    <tr>
      <td>${i.id}</td>
      <td>${formatCurrency(i.total)}</td>
      <td>${i.paymentMethod}</td>
      <td>${i.status}</td>
      <td>${new Date(i.createdAt).toLocaleDateString()}</td>
    </tr>
  `).join('');
}

function renderReports() {
    const topProducts = [...state.products].sort((a, b) => b.stock - a.stock).slice(0, 5);
    document.getElementById('topProductsReport').innerHTML = topProducts.map((p) => `<div class="small">• ${p.name} — ${p.stock} in stock</div>`).join('');

    const revenue = state.sales.reduce((sum, s) => sum + s.amount, 0);
    document.getElementById('revenueReport').innerHTML = `<h2 style="margin:0;">${formatCurrency(revenue)}</h2><div class="small">Across ${state.sales.length} sales</div>`;

    document.getElementById('stockAlertsReport').innerHTML = state.products
        .filter((p) => p.stock < 10)
        .map((p) => `<div class="small">• ${p.name} — ${p.stock} left</div>`)
        .join('');
}

function renderPos() {
    const search = document.getElementById('productSearch').value.toLowerCase();
    const productGrid = document.getElementById('productGrid');
    const stockPushProduct = document.getElementById('stockPushProduct');

    const currentStockValue = stockPushProduct.value;
    stockPushProduct.innerHTML = state.products.map((p) => `<option value="${p.id}" ${String(p.id) === currentStockValue ? 'selected' : ''}>${p.name} (${p.sku})</option>`).join('');
    if (!stockPushProduct.value && state.products.length) {
        stockPushProduct.value = String(state.products[0].id);
    }

    const filtered = state.products.filter((p) => p.name.toLowerCase().includes(search) || p.sku.toLowerCase().includes(search));
    productGrid.innerHTML = filtered.map((p) => `
    <div class="product-card" onclick="addToCart(${p.id})">
      <strong>${p.name}</strong>
      <div class="small">${p.sku} • ${p.category}</div>
      <div style="margin-top: 6px; font-weight:700;">${formatCurrency(p.price)}</div>
      <div class="small">In stock: ${p.stock}</div>
    </div>
  `).join('');
    updateCartUI();
}

function addToCart(productId) {
    const product = state.products.find((p) => p.id === productId);
    if (!product || product.stock <= 0) return;
    const existing = cart.find((item) => item.productId === productId);
    if (existing) {
        existing.quantity += 1;
    } else {
        cart.push({ productId, quantity: 1 });
    }
    updateCartUI();
}

function changeQty(productId, delta) {
    const item = cart.find((i) => i.productId === productId);
    if (!item) return;
    item.quantity += delta;
    if (item.quantity <= 0) cart = cart.filter((i) => i.productId !== productId);
    updateCartUI();
}

function getCartItems() {
    return cart.map((item) => {
        const product = state.products.find((p) => p.id === item.productId);
        return { ...item, product };
    }).filter((item) => item.product);
}

function updateCartUI() {
    const items = getCartItems();
    const cartContainer = document.getElementById('cartItems');
    const subtotalEl = document.getElementById('subtotal');
    const taxEl = document.getElementById('tax');
    const totalEl = document.getElementById('total');

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
    const tax = subtotal * 0.08;
    const discountedTotal = subtotal - (subtotal * discount / 100) + tax;
    subtotalEl.textContent = formatCurrency(subtotal);
    taxEl.textContent = formatCurrency(tax);
    totalEl.textContent = formatCurrency(discountedTotal);
}

function removeFromCart(productId) {
    cart = cart.filter((i) => i.productId !== productId);
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
    const phone = input.value.trim();

    if (!/^254[0-9]{9}$/.test(phone)) {
        alert('Please enter a valid Kenyan phone number starting with 254.');
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

    if (!productId || !Number.isFinite(quantity) || quantity <= 0) {
        alert('Please choose a valid product and quantity.');
        return;
    }

    try {
        await apiRequest(`/products/${productId}/stock`, {
            method: 'PUT',
            body: JSON.stringify({ quantity })
        });
        await loadDataFromAPI();
        renderPos();
        renderInventory();
        renderDashboard();
        renderReports();
        alert('Stock updated successfully.');
    } catch (error) {
        alert(error.message);
    }
}

async function checkout() {
    const items = getCartItems();
    if (!items.length) return alert('Cart is empty');

    const discount = Number(document.getElementById('discountInput').value || 0);
    const paymentMethod = document.getElementById('paymentMethod').value;

    if (paymentMethod === 'Mobile Money') {
        const phone = await promptForStkPushPhone();
        if (!phone) return;
        alert(`STK push sent to ${phone}. The customer will enter their PIN on the phone to complete payment.`);
    }

    try {
        const result = await apiRequest('/sales', {
            method: 'POST',
            body: JSON.stringify({
                items: items.map((item) => ({ productId: item.productId, quantity: item.quantity })),
                paymentMethod,
                discount
            })
        });

        cart = [];
        document.getElementById('discountInput').value = 0;
        document.getElementById('paymentMethod').value = 'Cash';
        await loadDataFromAPI();
        updateCartUI();
        renderDashboard();
        renderBilling();
        renderReports();
        renderPos();
        alert(`Sale completed successfully. Receipt: ${result.saleId}`);
    } catch (error) {
        alert(error.message);
    }
}

document.querySelectorAll('.nav-btn').forEach((button) => {
    button.addEventListener('click', () => showSection(button.dataset.section));
});

document.getElementById('productSearch').addEventListener('input', renderPos);
document.getElementById('discountInput').addEventListener('input', updateCartUI);


document.getElementById('inventoryForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const payload = {
        name: form.get('name'),
        sku: form.get('sku'),
        category: form.get('category'),
        price: Number(form.get('price')),
        stock: Number(form.get('stock')),
        expiry: form.get('expiry')
    };
    try {
        await apiRequest('/products', { method: 'POST', body: JSON.stringify(payload) });
        await loadDataFromAPI();
        e.target.reset();
        renderInventory();
        renderDashboard();
        renderPos();
        renderReports();
    } catch (error) {
        alert(error.message);
    }
});

async function bootstrap() {
    await loadDataFromAPI();
    renderDashboard();
    renderInventory();
    renderBilling();
    renderReports();
    renderPos();
}

bootstrap();
