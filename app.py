"""Lucas Barbershop: agenda própria (SQLite local, PostgreSQL em produção)."""
import os, re, json, hmac, hashlib, secrets, time, sqlite3, threading
from datetime import datetime, date, timedelta, time as dt_time
from contextlib import contextmanager
from zoneinfo import ZoneInfo
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo('America/Sao_Paulo')
DATABASE_URL = os.environ.get('DATABASE_URL', '').replace('postgres://', 'postgresql://', 1)
SQLITE_PATH = os.environ.get('SQLITE_PATH', str(ROOT / 'data' / 'agenda.sqlite3'))
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
SESSION_SECRET = os.environ.get('SESSION_SECRET', '')
PROD = os.environ.get('ENVIRONMENT') == 'production'
if PROD and (len(ADMIN_PASSWORD) < 12 or len(SESSION_SECRET) < 32 or not DATABASE_URL):
    raise RuntimeError('Produção requer ADMIN_PASSWORD forte, SESSION_SECRET (32+) e DATABASE_URL PostgreSQL.')
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = 'trocar-antes-de-publicar'
if not SESSION_SECRET:
    SESSION_SECRET = 'chave-local-somente-para-testes'
POSTGRES = bool(DATABASE_URL)
app = FastAPI(title='Lucas Barbershop | Agenda Própria', docs_url=None if PROD else '/api/docs', redoc_url=None)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

class DB:
    def __init__(self, conn, pg): self.conn, self.pg = conn, pg
    def execute(self, sql, params=()):
        if self.pg: sql = sql.replace('?', '%s')
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur
    def all(self, sql, params=()):
        rows = self.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    def one(self, sql, params=()):
        r = self.execute(sql, params).fetchone()
        return dict(r) if r else None
    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self): self.conn.close()

@contextmanager
def database(write=False):
    if POSTGRES:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        db = DB(conn, True)
    else:
        Path(SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH, timeout=20, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        db = DB(conn, False)
        conn.execute('PRAGMA busy_timeout=20000')
        conn.execute('PRAGMA foreign_keys=ON')
        if write: conn.execute('BEGIN IMMEDIATE')
    try:
        yield db
        if write: db.commit()
    except Exception:
        if write: db.rollback()
        raise
    finally: db.close()

def setup_db():
    pk = 'BIGSERIAL PRIMARY KEY' if POSTGRES else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    with database(write=True) as db:
        db.execute(f'''CREATE TABLE IF NOT EXISTS services (
            id {pk}, name TEXT NOT NULL, duration INTEGER NOT NULL, price_cents INTEGER,
            active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0)''')
        db.execute(f'''CREATE TABLE IF NOT EXISTS barbers (
            id {pk}, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)''')
        db.execute(f'''CREATE TABLE IF NOT EXISTS bookings (
            id {pk}, service_id INTEGER NOT NULL REFERENCES services(id),
            barber_id INTEGER NOT NULL REFERENCES barbers(id), service_name TEXT NOT NULL,
            duration INTEGER NOT NULL, client_name TEXT NOT NULL, phone TEXT NOT NULL,
            date TEXT NOT NULL, time TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'confirmed',
            created_at TEXT NOT NULL, note TEXT DEFAULT '')''')
        db.execute(f'''CREATE TABLE IF NOT EXISTS closures (
            id {pk}, date TEXT NOT NULL, barber_id INTEGER REFERENCES barbers(id), note TEXT DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS schedules (
            weekday INTEGER PRIMARY KEY, start_time TEXT, end_time TEXT, closed INTEGER NOT NULL DEFAULT 0)''')
        if not db.one('SELECT id FROM services LIMIT 1'):
            for i,(name,duration) in enumerate((('Corte masculino',40),('Barba e bigode',30),('Cabelo e barba',70))):
                db.execute('INSERT INTO services (name,duration,sort_order) VALUES (?,?,?)', (name,duration,i))
        if not db.one('SELECT id FROM barbers LIMIT 1'):
            db.execute('INSERT INTO barbers (name) VALUES (?)', ('Profissional 1 — editar nome',))
        day_hours = [('09:00','20:00'),('09:00','20:00'),('09:00','20:00'),('09:00','21:00'),('08:00','22:00'),('08:00','20:00'),('08:00','13:00')]
        if not db.one('SELECT weekday FROM schedules LIMIT 1'):
            for i,(start,end) in enumerate(day_hours):
                db.execute('INSERT INTO schedules (weekday,start_time,end_time) VALUES (?,?,?)', (i,start,end))

@app.on_event('startup')
def startup(): setup_db()

@app.middleware('http')
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    resp.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api/admin'):
        resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.get('/')
def home(): return FileResponse(ROOT / 'static' / 'index.html')

@app.get('/admin')
def admin(): return FileResponse(ROOT / 'static' / 'admin.html')

def now(): return datetime.now(TZ)
def parse_day(value):
    try: d = date.fromisoformat(value)
    except (ValueError,TypeError): raise HTTPException(400, 'Data inválida')
    if not 0 <= (d - now().date()).days <= 60: raise HTTPException(400, 'Escolha uma data nos próximos 60 dias')
    return d

def time_minutes(s):
    if not isinstance(s,str) or not re.fullmatch(r'\d\d:\d\d',s): raise HTTPException(400,'Horário inválido')
    try: hh,mm = map(int,s.split(':'))
    except ValueError: raise HTTPException(400,'Horário inválido')
    if hh > 23 or mm > 59: raise HTTPException(400,'Horário inválido')
    return hh*60+mm

def slot_time(m): return f'{m//60:02d}:{m%60:02d}'

def current_slots(db, day, barber_id, duration):
    weekday = day.weekday()
    schedule = db.one('SELECT * FROM schedules WHERE weekday=?', (weekday,))
    if not schedule or schedule['closed']: return []
    if db.one('SELECT id FROM closures WHERE date=? AND (barber_id IS NULL OR barber_id=?) LIMIT 1', (str(day), barber_id)): return []
    start, end = time_minutes(schedule['start_time']), time_minutes(schedule['end_time'])
    reservations = db.all('''SELECT time,duration FROM bookings WHERE date=? AND barber_id=? AND status='confirmed' ''', (str(day), barber_id))
    taken = [(time_minutes(x['time']), time_minutes(x['time'])+x['duration']) for x in reservations]
    earliest = now() + timedelta(minutes=45)
    slots=[]
    for m in range(((start+14)//15)*15, end-duration+1, 15):
        slot_datetime = datetime.combine(day, dt_time(m//60,m%60),tzinfo=TZ)
        if slot_datetime <= earliest: continue
        if any(m < b and m+duration > a for a,b in taken): continue
        slots.append(slot_time(m))
    return slots

@app.get('/api/bootstrap')
def bootstrap():
    with database() as db:
        return dict(services=db.all('SELECT id,name,duration,price_cents FROM services WHERE active=1 ORDER BY sort_order,id'),
                    barbers=db.all('SELECT id,name FROM barbers WHERE active=1 ORDER BY id'),
                    today=str(now().date()), max_date=str(now().date()+timedelta(days=60)),
                    timezone='America/Sao_Paulo')

@app.get('/api/availability')
def availability(service_id: int, barber_id: int, date: str):
    day = parse_day(date)
    with database() as db:
        svc=db.one('SELECT * FROM services WHERE id=? AND active=1', (service_id,))
        barber=db.one('SELECT * FROM barbers WHERE id=? AND active=1', (barber_id,))
        if not svc or not barber: raise HTTPException(404, 'Serviço ou profissional indisponível')
        return {'date':date, 'slots':current_slots(db, day, barber_id, svc['duration'])}

class BookingInput(BaseModel):
    service_id: int
    barber_id: int
    date: str
    time: str
    client_name: str = Field(min_length=2,max_length=80)
    phone: str = Field(min_length=10,max_length=25)

_rates = {}
_rate_lock = threading.Lock()
def throttle(request):
    ip = request.client.host if request.client else 'unknown'
    stamp = time.monotonic()
    with _rate_lock:
        hits = [x for x in _rates.get(ip,[]) if stamp-x < 600]
        if len(hits)>=15: raise HTTPException(429,'Muitas tentativas. Aguarde alguns minutos.')
        hits.append(stamp)
        _rates[ip] = hits
        if len(_rates)>5000: _rates.clear()

@app.post('/api/bookings', status_code=201)
def book(payload: BookingInput, request: Request):
    throttle(request)
    day = parse_day(payload.date)
    hour = time_minutes(payload.time)
    if hour%15: raise HTTPException(400,'Horário inválido')
    client = ' '.join(payload.client_name.split())
    digits = re.sub(r'\D','',payload.phone)
    if len(client)<2 or len(digits) not in (10,11,12,13): raise HTTPException(400,'Informe nome e telefone válidos')
    with database(write=True) as db:
        if db.pg: db.execute('SELECT pg_advisory_xact_lock(hashtext(?))', (f'{payload.barber_id}-{payload.date}',))
        svc=db.one('SELECT * FROM services WHERE id=? AND active=1',(payload.service_id,))
        barber=db.one('SELECT * FROM barbers WHERE id=? AND active=1',(payload.barber_id,))
        if not svc or not barber: raise HTTPException(400,'Serviço ou profissional indisponível')
        if payload.time not in current_slots(db,day,payload.barber_id,svc['duration']):
            raise HTTPException(409,'Esse horário não está mais disponível. Selecione outro.')
        created=now().isoformat(timespec='seconds')
        if db.pg:
            row=db.one('''INSERT INTO bookings (service_id,barber_id,service_name,duration,client_name,phone,date,time,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?) RETURNING id''',
                    (svc['id'],barber['id'],svc['name'],svc['duration'],client,digits,str(day),payload.time,created))
            id_=row['id']
        else:
            id_=db.execute('''INSERT INTO bookings (service_id,barber_id,service_name,duration,client_name,phone,date,time,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                    (svc['id'],barber['id'],svc['name'],svc['duration'],client,digits,str(day),payload.time,created)).lastrowid
        return {'id':id_, 'service':svc['name'],'barber':barber['name'],'date':str(day),'time':payload.time,'status':'confirmed'}

# Sessões administrativas assinadas. Não armazenar credenciais no navegador.
def sign_session(ts):
    msg=str(ts)
    mac=hmac.new(SESSION_SECRET.encode(),msg.encode(),hashlib.sha256).hexdigest()
    return f'{msg}.{mac}'

def require_admin(request:Request):
    token=request.cookies.get('lucas_admin','')
    try:
        ts, signature=token.split('.',1)
        valid=hmac.compare_digest(signature,sign_session(int(ts)).split('.')[1])
        if not valid or abs(time.time()-int(ts))>12*3600: raise ValueError
    except (ValueError,TypeError): raise HTTPException(401,'Acesso administrativo necessário')
    if request.method not in ('GET','HEAD'):
        origin=request.headers.get('origin')
        if origin:
            from urllib.parse import urlsplit
            o=urlsplit(origin)
            host=request.headers.get('host','')
            if o.netloc!=host: raise HTTPException(403,'Origem não autorizada')
    return True

class LoginInput(BaseModel): password: str
@app.post('/api/admin/login')
def login(payload:LoginInput, response: Response, request: Request):
    throttle(request)
    if not hmac.compare_digest(payload.password,ADMIN_PASSWORD): raise HTTPException(401,'Senha incorreta')
    response.set_cookie('lucas_admin',sign_session(int(time.time())),max_age=43200,httponly=True,secure=PROD,samesite='strict',path='/')
    return {'ok': True}

@app.get('/api/admin/me')
def me(auth=Depends(require_admin)): return {'ok': True}

@app.post('/api/admin/logout')
def logout(response:Response,auth=Depends(require_admin)):
    response.delete_cookie('lucas_admin',path='/')
    return {'ok':True}

@app.get('/api/admin/overview')
def overview(date: str='',auth=Depends(require_admin)):
    day=date or str(now().date())
    try: datetime.strptime(day,'%Y-%m-%d').date()
    except ValueError: raise HTTPException(400,'Data inválida')
    with database() as db:
        bookings=db.all('''SELECT b.*,r.name AS barber_name FROM bookings b
            JOIN barbers r ON r.id=b.barber_id WHERE b.date=? ORDER BY b.time,b.id''',(day,))
        services=db.all('SELECT * FROM services ORDER BY sort_order,id')
        barbers=db.all('SELECT * FROM barbers ORDER BY id')
        schedules=db.all('SELECT * FROM schedules ORDER BY weekday')
        closures=db.all('SELECT c.*,b.name AS barber_name FROM closures c LEFT JOIN barbers b ON b.id=c.barber_id ORDER BY c.date DESC,c.id DESC LIMIT 80')
        return {'bookings':bookings,'services':services,'barbers':barbers,'schedules':schedules,'closures':closures,'date':day}

class StatusInput(BaseModel): status: str
@app.patch('/api/admin/bookings/{booking_id}')
def edit_booking(booking_id:int, payload:StatusInput,auth=Depends(require_admin)):
    if payload.status not in ('confirmed','cancelled','completed','no_show'): raise HTTPException(400,'Status inválido')
    with database(write=True) as db:
        if not db.one('SELECT id FROM bookings WHERE id=?',(booking_id,)): raise HTTPException(404,'Reserva inexistente')
        db.execute('UPDATE bookings SET status=? WHERE id=?',(payload.status,booking_id))
    return {'ok':True}

class ServiceInput(BaseModel):
    name: str = Field(min_length=2,max_length=80)
    duration: int = Field(ge=15,le=240)
    price_cents: int|None = Field(default=None,ge=0,le=1000000)
    active: bool = True
@app.post('/api/admin/services')
def new_service(payload:ServiceInput,auth=Depends(require_admin)):
    with database(write=True) as db:
        db.execute('INSERT INTO services (name,duration,price_cents,active) VALUES (?,?,?,?)',(payload.name.strip(),payload.duration,payload.price_cents,int(payload.active)))
    return {'ok':True}
@app.put('/api/admin/services/{service_id}')
def update_service(service_id:int,payload:ServiceInput,auth=Depends(require_admin)):
    with database(write=True) as db:
        if not db.one('SELECT id FROM services WHERE id=?',(service_id,)):raise HTTPException(404,'Serviço não encontrado')
        db.execute('UPDATE services SET name=?,duration=?,price_cents=?,active=? WHERE id=?',
                   (payload.name.strip(),payload.duration,payload.price_cents,int(payload.active),service_id))
    return {'ok':True}

class BarberInput(BaseModel):
    name: str = Field(min_length=2,max_length=80)
    active: bool = True
@app.post('/api/admin/barbers')
def new_barber(payload:BarberInput,auth=Depends(require_admin)):
    with database(write=True) as db:
        db.execute('INSERT INTO barbers (name,active) VALUES (?,?)',(payload.name.strip(),int(payload.active)))
    return {'ok':True}
@app.put('/api/admin/barbers/{barber_id}')
def update_barber(barber_id:int,payload:BarberInput,auth=Depends(require_admin)):
    with database(write=True) as db:
        if not db.one('SELECT id FROM barbers WHERE id=?',(barber_id,)):raise HTTPException(404,'Profissional não encontrado')
        db.execute('UPDATE barbers SET name=?,active=? WHERE id=?',(payload.name.strip(),int(payload.active),barber_id))
    return {'ok':True}

class ScheduleInput(BaseModel):
    weekday: int = Field(ge=0,le=6)
    start_time: str
    end_time: str
    closed: bool = False
@app.put('/api/admin/schedule')
def update_schedule(payload:ScheduleInput,auth=Depends(require_admin)):
    st,end=time_minutes(payload.start_time),time_minutes(payload.end_time)
    if not payload.closed and (end<=st or end-st<15): raise HTTPException(400,'Horário de abertura inválido')
    with database(write=True) as db:
        db.execute('UPDATE schedules SET start_time=?,end_time=?,closed=? WHERE weekday=?',
            (payload.start_time,payload.end_time,int(payload.closed),payload.weekday))
    return {'ok':True}

class ClosureInput(BaseModel):
    date: str
    barber_id: int|None = None
    note: str = Field(default='',max_length=120)
@app.post('/api/admin/closures')
def create_closure(payload:ClosureInput,auth=Depends(require_admin)):
    try: date.fromisoformat(payload.date)
    except ValueError: raise HTTPException(400,'Data inválida')
    with database(write=True) as db:
        if payload.barber_id and not db.one('SELECT id FROM barbers WHERE id=?',(payload.barber_id,)): raise HTTPException(400,'Profissional inválido')
        db.execute('INSERT INTO closures (date,barber_id,note) VALUES (?,?,?)',(payload.date,payload.barber_id,payload.note))
    return {'ok':True}
@app.delete('/api/admin/closures/{id}')
def delete_closure(id:int,auth=Depends(require_admin)):
    with database(write=True) as db: db.execute('DELETE FROM closures WHERE id=?',(id,))
    return {'ok':True}
