const express = require('express');
const path = require('path');
const crypto = require('crypto');
const { Pool } = require('pg');

if (!process.env.DATABASE_URL) {
    console.warn('DATABASE_URL is missing. Configure a managed PostgreSQL database before using the API.');
}

const app = express();
for (const method of ['get', 'post', 'put', 'patch', 'delete']) {
    const register = app[method].bind(app);
    app[method] = (route, ...handlers) => register(route, ...handlers.map(handler =>
        (req, res, next) => Promise.resolve(handler(req, res, next)).catch(next)
    ));
}
const pool = process.env.DATABASE_URL ? new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: process.env.DATABASE_SSL === 'false' ? false : { rejectUnauthorized: false },
    max: Number(process.env.PG_POOL_MAX || 5),
    idleTimeoutMillis: 10000,
    connectionTimeoutMillis: 10000
}) : null;
const SESSION_COOKIE = 'caremax_session';
const SESSION_SECONDS = 8 * 60 * 60;
const PASSWORD_ITERATIONS = 310000;
const ROLES = ['admin', 'pharmacist', 'cashier', 'viewer'];
const validUsername = (value) => /^[a-zA-Z0-9._-]{3,64}$/.test(String(value || '')) || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || ''));
const appReady = pool ? initializeDatabase() : Promise.resolve();
appReady.catch(() => {});

app.disable('x-powered-by');
app.use(express.json({ limit: '1mb' }));

function hashPassword(password, salt = crypto.randomBytes(16).toString('hex')) {
    const digest = crypto.pbkdf2Sync(password, salt, PASSWORD_ITERATIONS, 32, 'sha256').toString('hex');
    return { digest, salt };
}

function query(sql, params = []) {
    if (!pool) throw new Error('Database is not configured. Set DATABASE_URL.');
    let i = 0;
    return pool.query(sql.replace(/\?/g, () => `$${++i}`), params);
}

async function initializeDatabase() {
    const statements = [
        `CREATE TABLE IF NOT EXISTS users (id BIGSERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','pharmacist','cashier','viewer')), active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`,
        `CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`,
        `CREATE TABLE IF NOT EXISTS patients (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, phone TEXT, dob TEXT, gender TEXT, "bloodGroup" TEXT, allergies TEXT)`,
        `CREATE TABLE IF NOT EXISTS appointments (id BIGSERIAL PRIMARY KEY, "patientId" BIGINT REFERENCES patients(id), doctor TEXT, date TEXT, time TEXT, reason TEXT, status TEXT)`,
        `CREATE TABLE IF NOT EXISTS products (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, sku TEXT UNIQUE, category TEXT, price NUMERIC(12,2), stock INTEGER NOT NULL DEFAULT 0, expiry TEXT, "costPrice" NUMERIC(12,2), "prescriptionRequired" BOOLEAN NOT NULL DEFAULT FALSE)`,
        `CREATE TABLE IF NOT EXISTS sales (id TEXT PRIMARY KEY, "patientId" BIGINT REFERENCES patients(id), amount NUMERIC(12,2) NOT NULL, "paymentMethod" TEXT, "createdAt" TIMESTAMPTZ NOT NULL, status TEXT, "prescriptionVerified" BOOLEAN NOT NULL DEFAULT FALSE, "createdBy" BIGINT REFERENCES users(id))`,
        `CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, "patientId" BIGINT REFERENCES patients(id), total NUMERIC(12,2) NOT NULL, "paymentMethod" TEXT, status TEXT, "createdAt" TIMESTAMPTZ NOT NULL, "createdBy" BIGINT REFERENCES users(id))`,
        `CREATE TABLE IF NOT EXISTS sale_items (id BIGSERIAL PRIMARY KEY, "saleId" TEXT NOT NULL REFERENCES sales(id), "productId" BIGINT NOT NULL REFERENCES products(id), "productName" TEXT NOT NULL, quantity INTEGER NOT NULL CHECK (quantity > 0), "unitPrice" NUMERIC(12,2) NOT NULL, "unitCost" NUMERIC(12,2), "lineProfit" NUMERIC(12,2))`,
        `CREATE TABLE IF NOT EXISTS stock_receipts (id BIGSERIAL PRIMARY KEY, "productId" BIGINT NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL CHECK (quantity > 0), "unitCost" NUMERIC(12,2), "receivedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(), "createdBy" BIGINT REFERENCES users(id))`,
        `ALTER TABLE products ADD COLUMN IF NOT EXISTS "costPrice" NUMERIC(12,2)`,
        `ALTER TABLE products ADD COLUMN IF NOT EXISTS "prescriptionRequired" BOOLEAN NOT NULL DEFAULT FALSE`,
        `ALTER TABLE sales ADD COLUMN IF NOT EXISTS "prescriptionVerified" BOOLEAN NOT NULL DEFAULT FALSE`,
        `ALTER TABLE sales ADD COLUMN IF NOT EXISTS "createdBy" BIGINT REFERENCES users(id)`,
        `ALTER TABLE sales ADD COLUMN IF NOT EXISTS "patientId" BIGINT REFERENCES patients(id)`,
        `ALTER TABLE sales ADD COLUMN IF NOT EXISTS "paymentMethod" TEXT`,
        `ALTER TABLE sales ADD COLUMN IF NOT EXISTS "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()`,
        `ALTER TABLE invoices ADD COLUMN IF NOT EXISTS "createdBy" BIGINT REFERENCES users(id)`,
        `ALTER TABLE invoices ADD COLUMN IF NOT EXISTS "patientId" BIGINT REFERENCES patients(id)`,
        `ALTER TABLE invoices ADD COLUMN IF NOT EXISTS "paymentMethod" TEXT`,
        `ALTER TABLE invoices ADD COLUMN IF NOT EXISTS "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()`,
        `ALTER TABLE patients ADD COLUMN IF NOT EXISTS "bloodGroup" TEXT`,
        `ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "patientId" BIGINT REFERENCES patients(id)`,
        `CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at)`,
        `CREATE INDEX IF NOT EXISTS sales_created_at_idx ON sales("createdAt")`
    ];
    for (const statement of statements) await pool.query(statement);
}

async function currentUser(req, res, next) {
    try {
        await appReady;
        const token = req.cookies?.[SESSION_COOKIE] || parseCookies(req.headers.cookie)[SESSION_COOKIE];
        if (token) {
            const hash = crypto.createHash('sha256').update(token).digest('hex');
            const { rows } = await query(`SELECT u.id, u.username, u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>NOW() AND u.active=TRUE`, [hash]);
            req.user = rows[0] || null;
        }
        next();
    } catch (error) { next(error); }
}
function parseCookies(header = '') {
    return Object.fromEntries(header.split(';').map(x => x.trim().split(/=(.*)/s).slice(0, 2)).filter(x => x.length === 2).map(([k, v]) => [k, decodeURIComponent(v)]));
}
function requireRole(...roles) {
    return (req, res, next) => req.user && roles.includes(req.user.role)
        ? next() : res.status(req.user ? 403 : 401).json({ error: req.user ? 'Insufficient permissions' : 'Login required' });
}
function setSession(res, token) {
    const secure = process.env.NODE_ENV === 'production' ? '; Secure' : '';
    res.setHeader('Set-Cookie', `${SESSION_COOKIE}=${token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${SESSION_SECONDS}${secure}`);
}
function clearSession(res) {
    res.setHeader('Set-Cookie', `${SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0${process.env.NODE_ENV === 'production' ? '; Secure' : ''}`);
}
async function createSession(userId, res) {
    const token = crypto.randomBytes(32).toString('hex');
    const hash = crypto.createHash('sha256').update(token).digest('hex');
    await query('INSERT INTO sessions (token_hash,user_id,expires_at) VALUES (?,?,NOW() + INTERVAL \'8 hours\')', [hash, userId]);
    setSession(res, token);
}
function errorHandler(error, req, res, next) {
    console.error(error);
    if (res.headersSent) return next(error);
    res.status(500).json({ error: 'Internal server error' });
}

app.get('/api/health', async (req, res) => {
    try { await appReady; await query('SELECT 1'); res.json({ ok: true, database: 'connected' }); }
    catch { res.status(503).json({ ok: false, database: 'unavailable' }); }
});
app.use('/api', currentUser);
app.get('/api/auth/status', async (req, res) => {
    const { rows } = await query('SELECT COUNT(*)::int AS count FROM users');
    res.json({ setupRequired: rows[0].count === 0, setupUsername: rows[0].count === 0 ? (process.env.ADMIN_EMAIL || null) : null, authenticated: Boolean(req.user), username: req.user?.username || null, role: req.user?.role || null });
});
app.post('/api/auth/setup', async (req, res) => {
    const designatedAdmin = String(process.env.ADMIN_EMAIL || '').trim().toLowerCase();
    if (!designatedAdmin) return res.status(503).json({ error: 'Initial administrator email is not configured by the deployment owner' });
    const username = String(req.body.username || designatedAdmin).trim().toLowerCase();
    const password = String(req.body.password || '');
    if (username !== designatedAdmin) return res.status(403).json({ error: 'Only the designated administrator can complete initial setup' });
    if (!validUsername(username)) return res.status(400).json({ error: 'Enter a valid username or email address' });
    if (password.length < 12) return res.status(400).json({ error: 'Choose a password with at least 12 characters' });
    try {
        const { digest, salt } = hashPassword(password);
        const client = await pool.connect();
        let user;
        try {
            await client.query('BEGIN');
            await client.query('LOCK TABLE users IN EXCLUSIVE MODE');
            const count = await client.query('SELECT COUNT(*)::int AS count FROM users');
            if (count.rows[0].count !== 0) { await client.query('ROLLBACK'); return res.status(409).json({ error: 'Initial administrator is already configured' }); }
            user = (await client.query('INSERT INTO users (username,password_hash,password_salt,role) VALUES ($1,$2,$3,\'admin\') RETURNING id,username,role', [username,digest,salt])).rows[0];
            await client.query('COMMIT');
        } finally { client.release(); }
        await createSession(user.id, res);
        res.status(201).json({ ok: true, user });
    } catch (error) { if (error.code === '23505') return res.status(409).json({ error: 'Username is already in use' }); throw error; }
});
app.post('/api/auth/login', async (req, res) => {
    const username = String(req.body.username || 'admin').trim();
    const { rows } = await query('SELECT id,username,role,password_hash,password_salt FROM users WHERE username=? AND active=TRUE', [username]);
    if (!rows[0] || !crypto.timingSafeEqual(Buffer.from(hashPassword(String(req.body.password || ''), rows[0].password_salt).digest, 'hex'), Buffer.from(rows[0].password_hash, 'hex'))) return res.status(401).json({ error: 'Invalid username or password' });
    await createSession(rows[0].id, res);
    res.json({ ok: true, user: { id: rows[0].id, username: rows[0].username, role: rows[0].role } });
});
app.post('/api/auth/logout', async (req, res) => {
    const token = parseCookies(req.headers.cookie)[SESSION_COOKIE];
    if (token) await query('DELETE FROM sessions WHERE token_hash=?', [crypto.createHash('sha256').update(token).digest('hex')]);
    clearSession(res); res.json({ ok: true });
});

app.get('/api/users', requireRole('admin'), async (req, res) => {
    const { rows } = await query('SELECT id,username,role,active,created_at FROM users ORDER BY id'); res.json(rows);
});
app.post('/api/users', requireRole('admin'), async (req, res) => {
    const { username, password, role } = req.body;
    if (!ROLES.includes(role) || role === 'admin') return res.status(400).json({ error: 'New users can be assigned pharmacist, cashier, or viewer. Administrators must be promoted by an administrator.' });
    if (!validUsername(username) || String(password || '').length < 12) return res.status(400).json({ error: 'Enter a valid username or email and a password of at least 12 characters' });
    const { digest, salt } = hashPassword(password);
    try { const { rows } = await query('INSERT INTO users (username,password_hash,password_salt,role) VALUES (?,?,?,?) RETURNING id,username,role,active,created_at', [username,digest,salt,role]); res.status(201).json(rows[0]); }
    catch (error) { if (error.code === '23505') return res.status(409).json({ error: 'Username is already in use' }); throw error; }
});
app.patch('/api/users/:id', requireRole('admin'), async (req, res) => {
    const { role, active } = req.body;
    if (req.params.id === String(req.user.id) && (active === false || role && role !== 'admin')) return res.status(400).json({ error: 'You cannot disable or demote your own administrator account' });
    if (role !== undefined && !ROLES.includes(role)) return res.status(400).json({ error: 'Invalid role' });
    const { rows } = await query('UPDATE users SET role=COALESCE(?,role), active=COALESCE(?,active) WHERE id=? RETURNING id,username,role,active,created_at', [role ?? null, typeof active === 'boolean' ? active : null, req.params.id]);
    if (!rows[0]) return res.status(404).json({ error: 'User not found' });
    if (active === false) await query('DELETE FROM sessions WHERE user_id=?', [req.params.id]);
    res.json(rows[0]);
});

app.get('/api/products', async (req, res) => {
    const { rows } = await query('SELECT * FROM products ORDER BY id');
    res.json(['admin','pharmacist'].includes(req.user?.role) ? rows : rows.map(({ costPrice, costprice, ...p }) => p));
});
app.post('/api/products', requireRole('admin','pharmacist'), async (req, res) => {
    const { name, sku, category, price, stock, expiry, costPrice, prescriptionRequired } = req.body;
    const { rows } = await query('INSERT INTO products (name,sku,category,price,stock,expiry,"costPrice","prescriptionRequired") VALUES (?,?,?,?,?,?,?,?) RETURNING *', [name,sku || null,category || '',price,stock || 0,expiry || '',costPrice ?? null,Boolean(prescriptionRequired)]);
    res.status(201).json(rows[0]);
});
app.put('/api/products/:id/stock', requireRole('admin','pharmacist'), async (req, res) => {
    const quantity = Number(req.body.quantity);
    if (!Number.isInteger(quantity) || quantity <= 0) return res.status(400).json({ error: 'Quantity must be a positive integer' });
    const client = await pool.connect();
    try {
        await client.query('BEGIN');
        const { rows } = await client.query('UPDATE products SET stock=stock+$1 WHERE id=$2 RETURNING *', [quantity,req.params.id]);
        if (!rows[0]) { await client.query('ROLLBACK'); return res.status(404).json({ error: 'Product not found' }); }
        await client.query('INSERT INTO stock_receipts ("productId",quantity,"unitCost","createdBy") VALUES ($1,$2,$3,$4)', [req.params.id,quantity,req.body.unitCost ?? null,req.user.id]);
        await client.query('COMMIT'); res.json(rows[0]);
    } catch (e) { await client.query('ROLLBACK'); throw e; } finally { client.release(); }
});
app.put('/api/products/:id', requireRole('admin','pharmacist'), async (req,res)=>{
    const b=req.body;
    const {rows}=await query('UPDATE products SET name=COALESCE(?,name),sku=COALESCE(?,sku),category=COALESCE(?,category),price=COALESCE(?,price),expiry=COALESCE(?,expiry),"costPrice"=COALESCE(?,"costPrice"),"prescriptionRequired"=COALESCE(?,"prescriptionRequired") WHERE id=? RETURNING *',[b.name??null,b.sku??null,b.category??null,b.price??null,b.expiry??null,b.costPrice??null,typeof b.prescriptionRequired==='boolean'?b.prescriptionRequired:null,req.params.id]);
    if(!rows[0]) return res.status(404).json({error:'Product not found'}); res.json(rows[0]);
});
app.delete('/api/products/:id', requireRole('admin','pharmacist'), async (req,res)=>{
    try { const {rowCount}=await query('DELETE FROM products WHERE id=?',[req.params.id]); if(!rowCount) return res.status(404).json({error:'Product not found'}); res.status(204).end(); }
    catch(error){ if(error.code==='23503') return res.status(409).json({error:'Product has recorded sale history and cannot be deleted'}); throw error; }
});
app.get('/api/patients', requireRole('admin','pharmacist'), async (req, res) => { const { rows } = await query('SELECT * FROM patients ORDER BY id DESC'); res.json(rows); });
app.post('/api/patients', requireRole('admin','pharmacist'), async (req, res) => {
    const b=req.body; const { rows }=await query('INSERT INTO patients (name,phone,dob,gender,"bloodGroup",allergies) VALUES (?,?,?,?,?,?) RETURNING *',[b.name,b.phone||'',b.dob||'',b.gender||'',b.bloodGroup||'',b.allergies||'']); res.status(201).json(rows[0]);
});
app.put('/api/patients/:id', requireRole('admin','pharmacist'), async (req,res)=>{
    const b=req.body;
    const {rows}=await query('UPDATE patients SET name=COALESCE(?,name),phone=COALESCE(?,phone),dob=COALESCE(?,dob),gender=COALESCE(?,gender),"bloodGroup"=COALESCE(?,"bloodGroup"),allergies=COALESCE(?,allergies) WHERE id=? RETURNING *',[b.name??null,b.phone??null,b.dob??null,b.gender??null,b.bloodGroup??null,b.allergies??null,req.params.id]);
    if(!rows[0]) return res.status(404).json({error:'Patient not found'}); res.json(rows[0]);
});
app.delete('/api/patients/:id', requireRole('admin','pharmacist'), async (req,res)=>{
    try { const {rowCount}=await query('DELETE FROM patients WHERE id=?',[req.params.id]); if(!rowCount) return res.status(404).json({error:'Patient not found'}); res.status(204).end(); }
    catch(error){ if(error.code==='23503') return res.status(409).json({error:'Patient has linked clinical or sales records and cannot be deleted'}); throw error; }
});
app.get('/api/appointments', requireRole('admin','pharmacist'), async (req,res)=>{ const {rows}=await query('SELECT * FROM appointments ORDER BY date DESC,time DESC'); res.json(rows); });
app.post('/api/appointments', requireRole('admin','pharmacist'), async (req,res)=>{ const b=req.body; const {rows}=await query('INSERT INTO appointments ("patientId",doctor,date,time,reason,status) VALUES (?,?,?,?,?,?) RETURNING *',[b.patientId||null,b.doctor||'',b.date||'',b.time||'',b.reason||'',b.status||'Scheduled']); res.status(201).json(rows[0]); });
app.put('/api/appointments/:id', requireRole('admin','pharmacist'), async (req,res)=>{ const b=req.body; const {rows}=await query('UPDATE appointments SET "patientId"=COALESCE(?,"patientId"),doctor=COALESCE(?,doctor),date=COALESCE(?,date),time=COALESCE(?,time),reason=COALESCE(?,reason),status=COALESCE(?,status) WHERE id=? RETURNING *',[b.patientId??null,b.doctor??null,b.date??null,b.time??null,b.reason??null,b.status??null,req.params.id]); if(!rows[0]) return res.status(404).json({error:'Appointment not found'}); res.json(rows[0]); });
app.delete('/api/appointments/:id', requireRole('admin','pharmacist'), async (req,res)=>{ const {rowCount}=await query('DELETE FROM appointments WHERE id=?',[req.params.id]); if(!rowCount) return res.status(404).json({error:'Appointment not found'}); res.status(204).end(); });
app.get('/api/sales', requireRole('admin','pharmacist','viewer'), async (req,res)=>{ const {rows}=await query('SELECT * FROM sales ORDER BY "createdAt" DESC'); res.json(rows); });
app.get('/api/invoices', requireRole('admin','pharmacist','viewer'), async (req,res)=>{ const {rows}=await query('SELECT * FROM invoices ORDER BY "createdAt" DESC'); res.json(rows); });
app.post('/api/sales', requireRole('admin','pharmacist','cashier'), async (req,res)=>{
    const {items,patientId,paymentMethod,discount,prescriptionVerified}=req.body;
    if(!Array.isArray(items)||!items.length) return res.status(400).json({error:'Cart is empty'});
    const client=await pool.connect();
    try {
        await client.query('BEGIN'); let subtotal=0; const checked=[];
        for(const item of items){
            const q=Number(item.quantity); if(!Number.isInteger(q)||q<=0) throw new Error('Invalid item quantity');
            const found=await client.query('SELECT * FROM products WHERE id=$1 FOR UPDATE',[item.productId]); const p=found.rows[0];
            if(!p||p.stock<q) throw new Error(`Not enough stock for ${p?.name||'item'}`);
            if(p.expiry && p.expiry < new Date().toISOString().slice(0,10)) throw new Error(`${p.name} is expired`);
            if(p.prescriptionRequired && (!prescriptionVerified || !['admin','pharmacist'].includes(req.user.role))) throw new Error(`Pharmacist verification required for ${p.name}`);
            checked.push({p,q}); subtotal+=Number(p.price)*q;
        }
        const discountPct=Math.min(100,Math.max(0,Number(discount)||0)); const total=Math.max(0,subtotal-subtotal*discountPct/100+subtotal*0.08);
        const saleId=`SALE-${crypto.randomUUID()}`, invoiceId=`INV-${crypto.randomUUID()}`, now=new Date();
        await client.query('INSERT INTO sales (id,"patientId",amount,"paymentMethod","createdAt",status,"prescriptionVerified","createdBy") VALUES ($1,$2,$3,$4,$5,$6,$7,$8)',[saleId,patientId||null,total,paymentMethod||'Cash',now,'Paid',Boolean(prescriptionVerified),req.user.id]);
        await client.query('INSERT INTO invoices (id,"patientId",total,"paymentMethod",status,"createdAt","createdBy") VALUES ($1,$2,$3,$4,$5,$6,$7)',[invoiceId,patientId||null,total,paymentMethod||'Cash','Paid',now,req.user.id]);
        for(const {p,q} of checked){ await client.query('UPDATE products SET stock=stock-$1 WHERE id=$2',[q,p.id]); await client.query('INSERT INTO sale_items ("saleId","productId","productName",quantity,"unitPrice","unitCost","lineProfit") VALUES ($1,$2,$3,$4,$5,$6,$7)',[saleId,p.id,p.name,q,p.price,p.costPrice, p.costPrice==null?null:(Number(p.price)-Number(p.costPrice))*q]); }
        await client.query('COMMIT'); res.status(201).json({saleId,invoiceId,total});
    } catch(e){ await client.query('ROLLBACK'); res.status(400).json({error:e.message}); } finally { client.release(); }
});
app.get('/api/reports', requireRole('admin','pharmacist','viewer'), async (req,res)=>{
    const [patients,appointments,products,sales,profit]=await Promise.all([query('SELECT COUNT(*)::int AS count FROM patients'),query('SELECT COUNT(*)::int AS count FROM appointments'),query('SELECT * FROM products'),query('SELECT * FROM sales'),query('SELECT COALESCE(SUM("lineProfit"),0) AS gross_profit, COUNT(*) FILTER (WHERE "lineProfit" IS NOT NULL)::int AS known_lines, COUNT(*)::int AS sale_lines FROM sale_items')]);
    const ps=products.rows, ss=sales.rows, grossProfit=Number(profit.rows[0].gross_profit); res.json({patientCount:patients.rows[0].count,appointmentCount:appointments.rows[0].count,inventoryValue:ps.reduce((n,p)=>n+Number(p.price||0)*p.stock,0),revenue:ss.reduce((n,s)=>n+Number(s.amount||0),0),lowStock:ps.filter(p=>p.stock<10),topProducts:[...ps].sort((a,b)=>b.stock-a.stock).slice(0,5),grossProfit,unknownCostLines:profit.rows[0].sale_lines-profit.rows[0].known_lines});
});
app.post('/api/chat', async (req,res)=>{
    const text=String(req.body.message||'').trim().toLowerCase();
    const guides=[['dashboard','dashboard','Opening the dashboard.'],['pos','pos','Opening the POS. Sign in with a cashier, pharmacist, or administrator account to record a sale.'],['inventory','inventory','Opening inventory. Pharmacist or administrator access is required.'],['billing','billing','Opening billing. Pharmacist or administrator access is required.'],['report','reports','Opening reports. Sign in with an authorized account to view records.']];
    const destination=guides.find(([word])=>text.includes(word));
    if(destination) return res.json({reply:destination[2],section:destination[1]});
    if(/low stock|reorder|running low/.test(text)){
        const {rows}=await query('SELECT name,stock FROM products WHERE stock<10 ORDER BY stock,name LIMIT 8');
        return res.json({reply:rows.length?`Low stock: ${rows.map(p=>`${p.name} (${p.stock})`).join('; ')}.`:'There are no low-stock items.',section:'pos'});
    }
    res.json({reply:'I can help you open the dashboard, POS, inventory, billing, or reports, and list low-stock products. What would you like to do?',section:null});
});

app.get('/', (req,res)=>res.sendFile(path.join(__dirname,'index.html')));
app.get('/index.html', (req,res)=>res.sendFile(path.join(__dirname,'index.html')));
app.get('/app.js', (req,res)=>res.sendFile(path.join(__dirname,'app.js')));
app.get('/styles.css', (req,res)=>res.sendFile(path.join(__dirname,'styles.css')));
app.use((req,res)=>res.status(404).json({error:'Not found'}));
app.use(errorHandler);

if (require.main === module) {
    const port=process.env.PORT||3000;
    appReady.then(()=>app.listen(port,()=>console.log(`CareMax API listening on port ${port}`))).catch(error=>{console.error('Database initialization failed:',error);process.exit(1);});
}
module.exports=app;
