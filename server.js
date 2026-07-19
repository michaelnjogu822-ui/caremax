const express = require('express');
const cors = require('cors');
const path = require('path');
const { Pool } = require('pg');

const app = express();
const PORT = process.env.PORT || 3000;
const usePostgres = Boolean(process.env.DATABASE_URL);
const DB_PATH = path.join(__dirname, 'caremax.db');

let db = null;
let pgPool = null;

if (usePostgres) {
    pgPool = new Pool({
        connectionString: process.env.DATABASE_URL,
        ssl: process.env.NODE_ENV === 'production' ? { rejectUnauthorized: false } : false
    });
    pgPool.on('error', (err) => {
        console.error('Postgres pool error:', err);
    });
    console.log('Using Postgres database');
    initDb().catch((err) => console.error('Postgres init failed:', err));
} else {
    const sqlite3 = require('sqlite3').verbose();
    db = new sqlite3.Database(DB_PATH, (err) => {
        if (err) {
            console.error('Failed to open SQLite DB:', err.message);
        } else {
            console.log('Connected to SQLite database');
            initDb();
        }
    });
}

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

async function initDb() {
    if (usePostgres) {
        await initPostgres();
        return;
    }

    db.serialize(() => {
        db.run(`CREATE TABLE IF NOT EXISTS patients (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      phone TEXT,
      dob TEXT,
      gender TEXT,
      bloodGroup TEXT,
      allergies TEXT
    )`);

        db.run(`CREATE TABLE IF NOT EXISTS appointments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      patientId INTEGER,
      doctor TEXT,
      date TEXT,
      time TEXT,
      reason TEXT,
      status TEXT
    )`);

        db.run(`CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      sku TEXT UNIQUE,
      category TEXT,
      price REAL,
      stock INTEGER,
      expiry TEXT
    )`);

        db.run(`CREATE TABLE IF NOT EXISTS sales (
      id TEXT PRIMARY KEY,
      patientId INTEGER,
      amount REAL,
      paymentMethod TEXT,
      createdAt TEXT,
      status TEXT
    )`);

        db.run(`CREATE TABLE IF NOT EXISTS invoices (
      id TEXT PRIMARY KEY,
      patientId INTEGER,
      total REAL,
      paymentMethod TEXT,
      status TEXT,
      createdAt TEXT
    )`);

        db.get('SELECT COUNT(*) AS count FROM products', (err, row) => {
            if (!err && row.count === 0) {
                seedData();
            }
        });
    });
}

async function initPostgres() {
    const queries = [
        `CREATE TABLE IF NOT EXISTS patients (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            dob TEXT,
            gender TEXT,
            bloodGroup TEXT,
            allergies TEXT
        );`,
        `CREATE TABLE IF NOT EXISTS appointments (
            id SERIAL PRIMARY KEY,
            patientId INTEGER REFERENCES patients(id),
            doctor TEXT,
            date TEXT,
            time TEXT,
            reason TEXT,
            status TEXT
        );`,
        `CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            sku TEXT UNIQUE,
            category TEXT,
            price REAL,
            stock INTEGER,
            expiry TEXT
        );`,
        `CREATE TABLE IF NOT EXISTS sales (
            id TEXT PRIMARY KEY,
            patientId INTEGER REFERENCES patients(id),
            amount REAL,
            paymentMethod TEXT,
            createdAt TEXT,
            status TEXT
        );`,
        `CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            patientId INTEGER REFERENCES patients(id),
            total REAL,
            paymentMethod TEXT,
            status TEXT,
            createdAt TEXT
        );`
    ];

    for (const sql of queries) {
        await pgPool.query(sql);
    }

    const { rows } = await pgPool.query('SELECT COUNT(*)::int AS count FROM products');
    if (rows[0].count === 0) {
        await seedDataPostgres();
    }
}

async function seedDataPostgres() {
    const seedProducts = [
        ['Paracetamol 500mg', 'PAR-500', 'Pain Relief', 120, 50, '2026-12-01'],
        ['Amoxil 250mg', 'AMX-250', 'Antibiotic', 260, 18, '2026-09-15'],
        ['Insulin Glargine', 'INS-GLA', 'Diabetes', 1800, 9, '2026-08-10'],
        ['Vitamin C 1000mg', 'VIT-C', 'Supplements', 350, 22, '2026-11-21'],
        ['Blood Pressure Monitor', 'BPM-01', 'Equipment', 4200, 7, ''],
        ['ORS Sachet', 'ORS-01', 'Hydration', 80, 30, '2026-07-06']
    ];

    for (const item of seedProducts) {
        await pgPool.query(
            'INSERT INTO products (name, sku, category, price, stock, expiry) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (sku) DO NOTHING',
            item
        );
    }

    const seedPatients = [
        ['Alice Mwangi', '0712345678', '1990-05-12', 'Female', 'A+', 'Penicillin'],
        ['John Otieno', '0723456789', '1985-11-03', 'Male', 'O+', 'None'],
        ['Grace Njeri', '0734567890', '2001-08-21', 'Female', 'B-', 'Latex']
    ];

    for (const p of seedPatients) {
        await pgPool.query(
            'INSERT INTO patients (name, phone, dob, gender, bloodGroup, allergies) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING',
            p
        );
    }

    const seedAppointments = [
        [1, 'Dr. Amina Yusuf', '2026-06-19', '09:00', 'General checkup', 'Scheduled'],
        [2, 'Dr. Peter Kamau', '2026-06-19', '11:30', 'Blood pressure review', 'Scheduled'],
        [3, 'Dr. Sarah Wanjiku', '2026-06-20', '10:00', 'Lab results follow-up', 'Completed']
    ];

    for (const a of seedAppointments) {
        await pgPool.query(
            'INSERT INTO appointments (patientId, doctor, date, time, reason, status) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING',
            a
        );
    }
}

function seedData() {
    const seedProducts = [
        ['Paracetamol 500mg', 'PAR-500', 'Pain Relief', 120, 50, '2026-12-01'],
        ['Amoxil 250mg', 'AMX-250', 'Antibiotic', 260, 18, '2026-09-15'],
        ['Insulin Glargine', 'INS-GLA', 'Diabetes', 1800, 9, '2026-08-10'],
        ['Vitamin C 1000mg', 'VIT-C', 'Supplements', 350, 22, '2026-11-21'],
        ['Blood Pressure Monitor', 'BPM-01', 'Equipment', 4200, 7, ''],
        ['ORS Sachet', 'ORS-01', 'Hydration', 80, 30, '2026-07-06']
    ];

    const stmt = db.prepare('INSERT INTO products (name, sku, category, price, stock, expiry) VALUES (?, ?, ?, ?, ?, ?)');
    for (const item of seedProducts) stmt.run(item);
    stmt.finalize();

    const seedPatients = [
        ['Alice Mwangi', '0712345678', '1990-05-12', 'Female', 'A+', 'Penicillin'],
        ['John Otieno', '0723456789', '1985-11-03', 'Male', 'O+', 'None'],
        ['Grace Njeri', '0734567890', '2001-08-21', 'Female', 'B-', 'Latex']
    ];

    const patientStmt = db.prepare('INSERT INTO patients (name, phone, dob, gender, bloodGroup, allergies) VALUES (?, ?, ?, ?, ?, ?)');
    for (const p of seedPatients) patientStmt.run(p);
    patientStmt.finalize();

    const seedAppointments = [
        [1, 'Dr. Amina Yusuf', '2026-06-19', '09:00', 'General checkup', 'Scheduled'],
        [2, 'Dr. Peter Kamau', '2026-06-19', '11:30', 'Blood pressure review', 'Scheduled'],
        [3, 'Dr. Sarah Wanjiku', '2026-06-20', '10:00', 'Lab results follow-up', 'Completed']
    ];

    const apptStmt = db.prepare('INSERT INTO appointments (patientId, doctor, date, time, reason, status) VALUES (?, ?, ?, ?, ?, ?)');
    for (const a of seedAppointments) apptStmt.run(a);
    apptStmt.finalize();
}

function runQuery(query, params = []) {
    if (usePostgres) {
        return pgPool.query(query, params).then((res) => res.rows);
    }
    return new Promise((resolve, reject) => {
        db.all(query, params, (err, rows) => {
            if (err) reject(err);
            else resolve(rows);
        });
    });
}

function runExec(query, params = []) {
    if (usePostgres) {
        const isInsert = /^\s*INSERT\s+/i.test(query);
        const finalQuery = isInsert ? `${query} RETURNING id` : query;
        return pgPool.query(finalQuery, params).then((res) => ({
            id: res.rows?.[0]?.id ?? null,
            changes: res.rowCount
        }));
    }
    return new Promise((resolve, reject) => {
        db.run(query, params, function (err) {
            if (err) reject(err);
            else resolve({ id: this.lastID, changes: this.changes });
        });
    });
}

app.get('/api/health', (_, res) => res.json({ ok: true }));

app.get('/api/patients', async (_, res) => {
    try {
        const rows = await runQuery('SELECT * FROM patients ORDER BY id DESC');
        res.json(rows);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/patients', async (req, res) => {
    try {
        const { name, phone, dob, gender, bloodGroup, allergies } = req.body;
        const result = await runExec(
            'INSERT INTO patients (name, phone, dob, gender, bloodGroup, allergies) VALUES (?, ?, ?, ?, ?, ?)',
            [name, phone, dob, gender, bloodGroup || '', allergies || '']
        );
        const row = await runQuery('SELECT * FROM patients WHERE id = ?', [result.id]);
        res.status(201).json(row[0]);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.get('/api/appointments', async (_, res) => {
    try {
        const rows = await runQuery('SELECT * FROM appointments ORDER BY date DESC, time DESC');
        res.json(rows);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/appointments', async (req, res) => {
    try {
        const { patientId, doctor, date, time, reason, status } = req.body;
        const result = await runExec(
            'INSERT INTO appointments (patientId, doctor, date, time, reason, status) VALUES (?, ?, ?, ?, ?, ?)',
            [patientId, doctor, date, time, reason, status || 'Scheduled']
        );
        const row = await runQuery('SELECT * FROM appointments WHERE id = ?', [result.id]);
        res.status(201).json(row[0]);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.put('/api/appointments/:id', async (req, res) => {
    try {
        await runExec('UPDATE appointments SET status = ? WHERE id = ?', ['Completed', req.params.id]);
        const row = await runQuery('SELECT * FROM appointments WHERE id = ?', [req.params.id]);
        res.json(row[0]);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.get('/api/products', async (_, res) => {
    try {
        const rows = await runQuery('SELECT * FROM products ORDER BY id ASC');
        res.json(rows);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/products', async (req, res) => {
    try {
        const { name, sku, category, price, stock, expiry } = req.body;
        const result = await runExec(
            'INSERT INTO products (name, sku, category, price, stock, expiry) VALUES (?, ?, ?, ?, ?, ?)',
            [name, sku, category, price, stock, expiry || '']
        );
        const row = await runQuery('SELECT * FROM products WHERE id = ?', [result.id]);
        res.status(201).json(row[0]);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.put('/api/products/:id/stock', async (req, res) => {
    try {
        const quantity = Number(req.body.quantity || 0);
        if (!Number.isFinite(quantity) || quantity <= 0) {
            return res.status(400).json({ error: 'Quantity must be a positive number' });
        }

        const productRows = await runQuery('SELECT * FROM products WHERE id = ?', [req.params.id]);
        if (!productRows.length) {
            return res.status(404).json({ error: 'Product not found' });
        }

        await runExec('UPDATE products SET stock = stock + ? WHERE id = ?', [quantity, req.params.id]);
        const row = await runQuery('SELECT * FROM products WHERE id = ?', [req.params.id]);
        res.json(row[0]);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.get('/api/sales', async (_, res) => {
    try {
        const rows = await runQuery('SELECT * FROM sales ORDER BY createdAt DESC');
        res.json(rows);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.get('/api/invoices', async (_, res) => {
    try {
        const rows = await runQuery('SELECT * FROM invoices ORDER BY createdAt DESC');
        res.json(rows);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/sales', async (req, res) => {
    try {
        const { items, patientId, paymentMethod, discount } = req.body;
        if (!items || !items.length) {
            return res.status(400).json({ error: 'Cart is empty' });
        }

        let subtotal = 0;
        for (const item of items) {
            const productRows = await runQuery('SELECT * FROM products WHERE id = ?', [item.productId]);
            const product = productRows[0];
            if (!product || product.stock < item.quantity) {
                return res.status(400).json({ error: `Not enough stock for ${product?.name || 'item'}` });
            }
            subtotal += product.price * item.quantity;
        }

        const tax = subtotal * 0.08;
        const discountedAmount = subtotal - (subtotal * (discount || 0) / 100);
        const total = Math.max(0, discountedAmount + tax);
        const saleId = `SALE-${Date.now()}`;
        const invoiceId = `INV-${Date.now()}`;
        const now = new Date().toISOString();

        await Promise.all(
            items.map(async (item) => {
                await runExec('UPDATE products SET stock = stock - ? WHERE id = ?', [item.quantity, item.productId]);
            })
        );

        await runExec(
            'INSERT INTO sales (id, patientId, amount, paymentMethod, createdAt, status) VALUES (?, ?, ?, ?, ?, ?)',
            [saleId, patientId || null, total, paymentMethod || 'Cash', now, 'Paid']
        );

        await runExec(
            'INSERT INTO invoices (id, patientId, total, paymentMethod, status, createdAt) VALUES (?, ?, ?, ?, ?, ?)',
            [invoiceId, patientId || null, total, paymentMethod || 'Cash', 'Paid', now]
        );

        res.status(201).json({ saleId, invoiceId, total });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.get('/api/reports', async (_, res) => {
    try {
        const patients = await runQuery('SELECT COUNT(*) AS count FROM patients');
        const appointments = await runQuery('SELECT COUNT(*) AS count FROM appointments');
        const products = await runQuery('SELECT * FROM products');
        const sales = await runQuery('SELECT * FROM sales');
        const lowStock = products.filter((p) => p.stock < 10);
        const inventoryValue = products.reduce((sum, p) => sum + p.price * p.stock, 0);
        const revenue = sales.reduce((sum, s) => sum + (s.amount || 0), 0);

        res.json({
            patientCount: patients[0].count,
            appointmentCount: appointments[0].count,
            inventoryValue,
            revenue,
            lowStock,
            topProducts: [...products].sort((a, b) => b.stock - a.stock).slice(0, 5)
        });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.listen(PORT, () => {
    console.log(`CareMax API running on http://localhost:${PORT}`);
});
