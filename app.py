from flask import Flask, render_template, request, session, jsonify, send_from_directory, redirect, url_for
from datetime import datetime, timedelta
import pytz
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps, lru_cache
import random
import json
import os
import time
import re
import html
import hmac, hashlib, base64

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'pentagon-church-secret-2025-ENCRYPTED-@2026#')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('data', exist_ok=True)
os.makedirs('static/testimonies', exist_ok=True)
os.makedirs('static/uploads/members', exist_ok=True)
for sub in ['videos','gallery','notes','sermons','events','members']:
    os.makedirs(f'static/uploads/{sub}', exist_ok=True)

TZ = pytz.timezone('Africa/Nairobi')
DATA_DIR = 'data'
QR_SECRET = os.getenv('QR_SECRET', app.secret_key)

try:
    from flask_caching import Cache
    cache = Cache(app, config={'CACHE_TYPE':'SimpleCache','CACHE_DEFAULT_TIMEOUT':60})
except:
    cache = None
try:
    from flask_compress import Compress
    Compress(app)
except:
    pass

ADMIN_USERNAME = os.getenv('ADMIN_USER', "admin")
ADMIN_PASSWORD_HASH = generate_password_hash(os.getenv('ADMIN_PASS', "SouthB@2026!Chapel#Secure"))
PASTOR_PASSWORD = os.getenv('PASTOR_KEY', "PastorKey2025")
COUNSEL_PWD = os.getenv('COUNSELOR_KEY', "CounselorKey2025")

login_attempts = {}
rate_limit = {}

CONTACT_FILE = os.path.join(DATA_DIR, 'contacts.json')
COUNSELLING_FILE = os.path.join(DATA_DIR, 'counselling_requests.json')
MEMBERS_FILE = os.path.join(DATA_DIR, 'members.json')
TESTIMONY_FILE = os.path.join(DATA_DIR, 'testimonies.json')
ENCOUNTER_FILE = os.path.join(DATA_DIR, 'encounters.json')
TRANSCRIPTS_FILE = os.path.join(DATA_DIR, 'transcripts.json')
CHECKIN_FILE = os.path.join(DATA_DIR, 'checkins.json')

_json_cache = {}
_json_mtime = {}
def load_json(file, default=[]):
    try:
        mtime = os.path.getmtime(file) if os.path.exists(file) else 0
        if file in _json_cache and _json_mtime.get(file)==mtime:
            return _json_cache[file]
        if os.path.exists(file):
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                _json_cache[file]=data
                _json_mtime[file]=mtime
                return data
    except: pass
    return default

def save_json(file, data):
    os.makedirs(os.path.dirname(file) or '.', exist_ok=True)
    tmp = file + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, file)
    _json_cache[file]=data
    try: _json_mtime[file]=os.path.getmtime(file)
    except: _json_mtime[file]=time.time()

def check_rate(ip, key, limit=10, window=60):
    now = time.time()
    bucket = rate_limit.get(f"{ip}_{key}", [])
    bucket = [t for t in bucket if now - t < window]
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    rate_limit[f"{ip}_{key}"] = bucket
    return True

def clear_image_cache():
    try:
        find_file_cached.cache_clear()
        get_images_dict_cached.cache_clear()
    except: pass

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return render_template('admin_login.html')
        if time.time() - session.get('admin_time', 0) > 1800:
            session.clear()
            return render_template('admin_login.html', error="Session expired - Please login again")
        session['admin_time'] = time.time()
        if request.method == 'POST' and request.path.startswith('/api/admin/'):
            token = request.headers.get('X-CSRF-Token') or request.headers.get('X-CSRFToken')
            sess_token = session.get('csrf_token')
            if sess_token and token!= sess_token:
                if not token:
                    token = request.form.get('csrf_token','')
                if token!= sess_token:
                    return jsonify({"error": "CSRF failed"}), 403
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename, allowed):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed

def extract_yt_id(url_or_id):
    if not url_or_id: return ""
    m = re.search(r'(?:v=|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})', url_or_id)
    if m: return m.group(1)
    if len(url_or_id.strip()) == 11: return url_or_id.strip()
    return url_or_id.strip()

def sanitize_text(s, max_len=500):
    if not s: return ""
    s = html.escape(str(s).strip())
    return s[:max_len]

def verify_pwd(req_pwd, expected):
    return req_pwd == expected

@lru_cache(maxsize=128)
def find_file_cached(base_name: str) -> str:
    base_name = re.sub(r'[^a-zA-Z0-9_\-/]', '', base_name.strip())
    base_name = base_name.strip('/').strip('\\')
    if '..' in base_name:
        return "uploads/god_key.jpg"
    static_dir = Path(app.static_folder)
    clean_stem = Path(base_name).name.lower()
    extensions = ['.webp', '.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mov', '.webm']
    for ext in extensions:
        p = static_dir / f"{base_name}{ext}"
        try:
            if p.exists() and p.resolve().is_relative_to(static_dir.resolve()):
                return f"{base_name}{ext}"
        except: pass
        p_lower = static_dir / f"{base_name.lower()}{ext}"
        try:
            if p_lower.exists() and p_lower.resolve().is_relative_to(static_dir.resolve()):
                return str(p_lower.relative_to(static_dir)).replace("\\", "/")
        except: pass
    for file in static_dir.rglob("*"):
        if not file.is_file(): continue
        if file.stem.lower() == clean_stem:
            try:
                if file.resolve().is_relative_to(static_dir.resolve()):
                    return str(file.relative_to(static_dir)).replace("\\", "/")
            except: continue
    return f"{base_name}.png"

def find_file(base_name: str) -> str:
    return find_file_cached(base_name)

@lru_cache(maxsize=1)
def get_images_dict_cached():
    return {
        'gate': find_file('gate'),
        'clock': find_file('clock'),
        'mountains': find_file('mountains'),
        'jesus': find_file('jesus'),
        'seasons': find_file('seasons'),
        'bread': find_file('bread'),
        'flower': find_file('flower'),
        'christmas': find_file('holidays/christmas/christmas'),
        'newyear': find_file('holidays/newyear/newyear'),
        'easter': find_file('holidays/easter/easter'),
        'sunday': find_file('holidays/sunday/sunday')
    }

def get_images_dict():
    return get_images_dict_cached()

@lru_cache(maxsize=32)
def get_easter(year: int) -> datetime:
    a = year % 19; b = year // 100; c = year % 100; d = b // 4; e = b % 4
    f = (b + 8) // 25; g = (b - f + 1) // 3; h = (19 * a + b - d - g + 15) % 30
    i = c // 4; k = c % 4; l = (32 + 2 * e + 2 * i - h - k) % 7; m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31; day = ((h + l - 7 * m + 114) % 31) + 1
    return TZ.localize(datetime(year, month, day))

def get_holiday_info():
    now = datetime.now(TZ); year = now.year
    easter_date = get_easter(year); is_sunday = now.weekday() == 6
    try: test = request.args.get('test', '').lower()
    except: test = ''
    holidays = [
        {'key': 'christmas', 'name': 'Christmas', 'date': TZ.localize(datetime(year, 12, 25)), 'countdown_start': TZ.localize(datetime(year, 12, 15)), 'theme_start': TZ.localize(datetime(year, 12, 15)), 'theme_end': TZ.localize(datetime(year, 12, 27, 23, 59, 59)), 'video': find_file('holidays/christmas/christmas'), 'verse': 'Luke 2:11'},
        {'key': 'newyear', 'name': 'New Year', 'date': TZ.localize(datetime(year + 1, 1, 1)), 'countdown_start': TZ.localize(datetime(year, 12, 22)), 'theme_start': TZ.localize(datetime(year, 12, 27)), 'theme_end': TZ.localize(datetime(year + 1, 1, 2, 23, 59, 59)), 'video': find_file('holidays/newyear/newyear'), 'verse': 'Isaiah 43:19'},
        {'key': 'easter', 'name': 'Easter', 'date': easter_date, 'countdown_start': easter_date - timedelta(days=10), 'theme_start': easter_date - timedelta(days=3), 'theme_end': easter_date + timedelta(days=2, hours=23, minutes=59), 'video': find_file('holidays/easter/easter'), 'verse': 'Matthew 28:6'},
        {'key': 'sunday', 'name': 'Sunday', 'date': now, 'countdown_start': None, 'theme_start': None, 'theme_end': None, 'video': find_file('holidays/sunday/sunday'), 'verse': 'Exodus 20:8', 'only_sunday': True}
    ]
    if test:
        for h in holidays:
            if h['key'] == test:
                return {'active': h['key'], 'info': h, 'now': now.isoformat(), 'is_countdown': False, 'days_left': 0}
    for h in holidays:
        if h['key'] == 'sunday':
            if is_sunday: return {'active': 'sunday', 'info': h, 'now': now.isoformat(), 'is_countdown': False, 'days_left': 0}
            continue
        if h['theme_start'] <= now <= h['theme_end']:
            return {'active': h['key'], 'info': h, 'now': now.isoformat(), 'is_countdown': False, 'days_left': (h['date'] - now).days}
        if h['countdown_start'] and h['countdown_start'] <= now < h['theme_start']:
            return {'active': h['key'], 'info': h, 'now': now.isoformat(), 'is_countdown': True, 'days_left': (h['date'] - now).days}
    return {'active': 'normal', 'info': None, 'now': now.isoformat(), 'is_countdown': False, 'days_left': 0}

def get_next_sunday_8am():
    now = datetime.now(TZ)
    days_ahead = (6 - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= 8: days_ahead = 7
    ns = now + timedelta(days=days_ahead)
    return ns.replace(hour=8, minute=0, second=0, microsecond=0).isoformat()

@app.after_request
def after_request(response):
    if request.path.startswith('/static/'):
        response.headers["Cache-Control"] = "public, max-age=604800"
    elif request.path.startswith('/api/'):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

QUIZ_FILE = 'bible_database.json'
DEFAULT_QUIZ = {"sunday": [{"id": 1, "q": "Who built the ark?", "options": ["Moses", "Noah", "Abraham", "David"], "answer": 1, "ref": "Genesis 6:14", "book": "Genesis"}], "youth": [], "adult": [], "pastors": []}
BOOKS_POOL = ["Exodus","Leviticus","Numbers","Joshua","Judges","Ruth","1 Samuel","Psalms","Proverbs","Isaiah","Matthew","Mark","Luke","John","Acts","Romans","Revelation"]
for i in range(2, 101):
    DEFAULT_QUIZ["sunday"].append({"id": i, "q": f"Sunday Q {i}", "options": ["Genesis","Exodus","Leviticus","Numbers"], "answer": 0, "ref": "Genesis 1:1", "book": "Genesis"})
    DEFAULT_QUIZ["youth"].append({"id": i, "q": f"Youth Q {i} - {BOOKS_POOL[i % len(BOOKS_POOL)]}", "options": ["Healed","Preached","Prayed","All"], "answer": 3, "ref": f"{BOOKS_POOL[i % len(BOOKS_POOL)]} 1:1", "book": BOOKS_POOL[i % len(BOOKS_POOL)]})
    DEFAULT_QUIZ["adult"].append({"id": i, "q": f"Adult Q {i}", "options": ["Love","Faith","Grace","Salvation"], "answer": 0, "ref": f"{BOOKS_POOL[i % len(BOOKS_POOL)]} 3:16", "book": BOOKS_POOL[i % len(BOOKS_POOL)]})
    DEFAULT_QUIZ["pastors"].append({"id": i, "q": f"Pastors Q {i}", "options": ["Agape","Logos","Shalom","Ekklesia"], "answer": 1, "ref": f"{BOOKS_POOL[i % len(BOOKS_POOL)]} 1:1", "book": BOOKS_POOL[i % len(BOOKS_POOL)]})

if not os.path.exists(QUIZ_FILE): save_json(QUIZ_FILE, DEFAULT_QUIZ)
def get_quiz(): return load_json(QUIZ_FILE, DEFAULT_QUIZ)

@app.route('/')
def home():
    return render_template('index.html', next_sunday=get_next_sunday_8am(), images=get_images_dict(), holiday=get_holiday_info())

@app.route('/events')
def events_page():
    return render_template('events.html', images=get_images_dict(), holiday=get_holiday_info(), events=load_json('data/events.json', []), next_sunday=get_next_sunday_8am())

@app.route('/sermons')
def sermons_page():
    return render_template('sermons.html', images=get_images_dict(), holiday=get_holiday_info(), sermons=load_json('data/sermons.json', []), next_sunday=get_next_sunday_8am())

@app.route('/videos')
def videos_page():
    return render_template('videos.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), items=load_json('data/videos.json', []), videos=load_json('data/videos.json', []))

@app.route('/gallery')
def gallery_page():
    albums = load_json('data/gallery.json', [])
    for a in albums:
        if 'visibility' not in a: a['visibility'] = 'public'
    if not session.get('member_logged_in'):
        albums = [a for a in albums if a.get('visibility','public')=='public']
    return render_template('gallery.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), gallery=albums, items=albums)

@app.route('/prayer-wall')
def prayer_wall():
    return render_template('prayer.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), prayers=[p for p in load_json('data/prayers.json', []) if p.get('visibility', 'public') == 'public'])

@app.route('/contact')
def contact():
    return render_template('contact.html', images=get_images_dict(), holiday=get_holiday_info(), team=[{'name': 'Caudensha Sawe', 'role': 'Senior Chaplain', 'phone': '0721424392', 'photo': find_file('team/caudensha')}], next_sunday=get_next_sunday_8am())

@app.route('/bible-quiz')
def bible_quiz():
    return render_template('quiz.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())

@app.route('/counselling')
@app.route('/counselling-care')
def counselling():
    return render_template('counselling.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())

@app.route('/sunday-school')
def sunday_school():
    return render_template('sunday.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), notes=load_json('data/sunday_school_notes.json', []), sunday_videos=load_json('data/sunday_school_videos.json', []))

@app.route('/faith-arcade')
def faith_arcade():
    return render_template('faith_arcade.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())

@app.route('/member-qualifications')
def member_qualifications():
    return render_template('member_qualifications.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())

@app.route('/members/register')
def members_register_page():
    return render_template('member_register.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())

@app.route('/members/login')
def members_login_page():
    return render_template('member_login.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())

@app.route('/members/dashboard')
def members_dashboard_page():
    if not session.get('member_logged_in'):
        return render_template('member_login.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), error="Please login as member")
    return render_template('member_dashboard.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), member=session.get('member_data'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    ip = request.remote_addr
    attempts = login_attempts.get(ip, {'count': 0, 'time': 0})
    if attempts['count'] >= 5 and time.time() - attempts['time'] < 900:
        return render_template('admin_login.html', error="Too many attempts. Try after 15 mins")
    if request.method == 'POST':
        u = request.form.get('username','').strip()
        p = request.form.get('password','')
        if u == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, p):
            session['admin_logged_in'] = True
            session['admin_time'] = time.time()
            session['csrf_token'] = os.urandom(16).hex()
            login_attempts[ip] = {'count': 0, 'time': 0}
            return redirect(url_for('admin_dashboard'))
        else:
            login_attempts[ip] = {'count': attempts['count'] + 1, 'time': time.time()}
            return render_template('admin_login.html', error=f"Wrong! Attempt {attempts['count'] + 1}/5")
    return render_template('admin_login.html')

@app.route('/admin/logout', methods=['GET', 'POST'])
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin', methods=['GET', 'POST'])
@app.route('/admin/', methods=['GET', 'POST'])
@app.route('/admin/dashboard', methods=['GET', 'POST'])
@app.route('/admin/dashboard/', methods=['GET', 'POST'])
@admin_required
def admin_dashboard():
    if 'csrf_token' not in session:
        session['csrf_token'] = os.urandom(16).hex()
    return render_template('admin_dashboard.html', images=get_images_dict(), csrf_token=session['csrf_token'])

@app.errorhandler(405)
def method_not_allowed(e):
    if request.path.startswith('/admin'):
        if session.get('admin_logged_in'): return redirect(url_for('admin_dashboard'))
        return redirect(url_for('admin_login'))
    return "Method Not Allowed", 405

@app.route('/api/videos')
def api_videos(): return jsonify(load_json('data/videos.json', []))

# FIXED: public API filters private
@app.route('/api/gallery')
def api_gallery():
    albums = load_json('data/gallery.json', [])
    for a in albums:
        if 'visibility' not in a: a['visibility'] = 'public'
    if not session.get('member_logged_in'):
        albums = [a for a in albums if a.get('visibility','public')=='public']
    return jsonify(albums)

@app.route('/api/admin/gallery/all')
@admin_required
def api_admin_gallery_all():
    return jsonify(load_json('data/gallery.json', []))

@app.route('/api/sunday-notes')
def api_sunday_notes(): return jsonify(load_json('data/sunday_school_notes.json', []))

@app.route('/api/sunday-videos')
def api_sunday_videos(): return jsonify(load_json('data/sunday_school_videos.json', []))

@app.route('/api/sermons')
def api_sermons(): return jsonify(load_json('data/sermons.json', []))

@app.route('/api/events')
def api_events(): return jsonify(load_json('data/events.json', []))

@app.route('/api/prayers')
def api_prayers_list(): return jsonify(load_json('data/prayers.json', []))

SUNDAY_POOL = [{"q": "Who built the ark?", "options": ["Noah","Moses","David","Peter"], "answer": 0, "ref": "Genesis 6"},{"q": "How many disciples?", "options": ["3","7","12","10"], "answer": 2, "ref": "Matthew 10"},{"q": "David defeated Goliath with?", "options": ["Sword","Stone","Spear","Bow"], "answer": 1, "ref": "1 Sam 17"}]

@app.route('/api/sunday-quiz')
def api_sunday_quiz():
    pool = load_json('data/sunday_school_quiz.json', SUNDAY_POOL)
    seen = session.get('sunday_seen', [])
    remaining = [q for q in pool if q['q'] not in seen]
    if len(remaining) < 5: seen = []; remaining = pool
    pick = random.sample(remaining, min(5, len(remaining)))
    seen.extend([q['q'] for q in pick]); session['sunday_seen'] = seen
    return jsonify(pick)

@app.route('/api/quiz/<level>')
def api_quiz(level):
    data = get_quiz().get(level, [])
    if not data: return jsonify({"questions": []})
    seen = session.get(f'seen_{level}', [])
    remaining = [q for q in data if q['id'] not in seen]
    if len(remaining) < 15: seen = []; remaining = data
    pick = random.sample(remaining, min(15, len(remaining)))
    seen.extend([q['id'] for q in pick]); session[f'seen_{level}'] = seen
    return jsonify({"questions": pick})

@app.route('/prayer/submit', methods=['POST'])
def submit_prayer_wall():
    if not check_rate(request.remote_addr, 'prayer', 5, 60):
        return jsonify({"ok": False, "error": "Too fast"}), 429
    prayers = load_json('data/prayers.json', [])
    prayers.append({"id": int(time.time() * 1000),"category": sanitize_text(request.form.get('category','General'),50),"name": sanitize_text(request.form.get('name',''),100),"anonymous": bool(request.form.get('anonymous')),"visibility": request.form.get('visibility','public') if request.form.get('visibility') in ['public','private'] else 'public',"content": sanitize_text(request.form.get('content',''),1000),"contact": bool(request.form.get('contact')),"date": datetime.now(TZ).strftime('%Y-%m-%d'),"pray_count": 0})
    save_json('data/prayers.json', prayers)
    return jsonify({"ok": True})

@app.route('/prayer/pray/<int:pid>', methods=['POST'])
def pray_count_wall(pid):
    prayers = load_json('data/prayers.json', []); count=0
    for p in prayers:
        if p['id']==pid: p['pray_count']=p.get('pray_count',0)+1; count=p['pray_count']; break
    save_json('data/prayers.json', prayers)
    return jsonify({"count": count})

@app.route('/api/counselling-request', methods=['POST'])
def save_counselling():
    if not check_rate(request.remote_addr, 'counselling', 5, 120):
        return jsonify({"success": False, "error": "Too many requests"}), 429
    data = request.get_json(); msgs = load_json(COUNSELLING_FILE, [])
    msgs.insert(0, {"id": int(time.time()*1000),"name": sanitize_text(data.get('name',''),100),"phone": sanitize_text(data.get('phone',''),20),"age_group": sanitize_text(data.get('age_group',''),20),"category": sanitize_text(data.get('category',''),50),"description": sanitize_text(data.get('description',''),2000),"is_anonymous": bool(data.get('is_anonymous', False)),"preferred_time": sanitize_text(data.get('preferred_time','Any'),20),"date": datetime.now(TZ).strftime("%Y-%m-%d"),"time": datetime.now(TZ).strftime("%H:%M:%S")})
    save_json(COUNSELLING_FILE, msgs)
    return jsonify({"success": True, "id": msgs[0]['id']})

@app.route('/api/testimony', methods=['POST'])
def api_testimony():
    if not check_rate(request.remote_addr, 'testimony', 3, 300):
        return jsonify(success=False, error='Too many uploads, try later'), 429
    try:
        os.makedirs('static/testimonies', exist_ok=True)
        if 'audio' not in request.files:
            return jsonify(success=False, error='No audio file'), 400
        f = request.files['audio']
        if f.filename == '':
            return jsonify(success=False, error='Empty filename'), 400
        ext = f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else 'webm'
        if ext not in ['webm','wav','mp3','m4a','ogg']: ext = 'webm'
        filename = secure_filename(f"testimony_{int(time.time()*1000)}.{ext}")
        save_path = os.path.join('static/testimonies', filename)
        f.save(save_path)
        name = sanitize_text(request.form.get('name','Anonymous'),100) or 'Anonymous'
        phone = sanitize_text(request.form.get('phone',''),20)
        records = load_json(TESTIMONY_FILE, [])
        new_id = int(time.time()*1000)
        records.insert(0, {"id": new_id,"filename": filename,"path": f"testimonies/{filename}","name": name,"phone": phone,"date": datetime.now(TZ).strftime("%Y-%m-%d"),"time": datetime.now(TZ).strftime("%H:%M:%S")})
        save_json(TESTIMONY_FILE, records)
        transcripts = load_json(TRANSCRIPTS_FILE, [])
        transcripts.append({"testimony_id": new_id, "text": f"[{name}] — He brought me back to life — private", "date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")})
        save_json(TRANSCRIPTS_FILE, transcripts)
        return jsonify(success=True, filename=filename, id=new_id)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@app.route('/api/admin/testimonies', methods=['GET','POST'])
@admin_required
def api_admin_testimonies():
    if request.method == 'POST':
        data = request.get_json() or {}
        pwd = data.get('pwd','')
        if not verify_pwd(pwd, COUNSEL_PWD):
            return jsonify({"error":"Wrong password"}), 403
    return jsonify(load_json(TESTIMONY_FILE, []))

@app.route('/api/admin/testimonies/count')
@admin_required
def api_testimonies_count():
    return jsonify({"count": len(load_json(TESTIMONY_FILE, []))})

@app.route('/api/admin/transcripts', methods=['GET'])
@admin_required
def admin_transcripts():
    return jsonify(load_json(TRANSCRIPTS_FILE, []))

@app.route('/api/admin/delete-testimony/<int:tid>', methods=['POST'])
@admin_required
def delete_testimony(tid):
    records = load_json(TESTIMONY_FILE, [])
    for r in records:
        if r.get('id') == tid:
            try:
                fp = os.path.join('static', r.get('path',''))
                if os.path.abspath(fp).startswith(os.path.abspath('static')):
                    if os.path.exists(fp): os.remove(fp)
            except: pass
            break
    records = [r for r in records if r.get('id')!= tid]
    save_json(TESTIMONY_FILE, records)
    trans = load_json(TRANSCRIPTS_FILE, [])
    trans = [t for t in trans if t.get('testimony_id')!=tid]
    save_json(TRANSCRIPTS_FILE, trans)
    return jsonify({"ok": True})

@app.route('/api/encounter', methods=['POST'])
def api_encounter_save():
    if not check_rate(request.remote_addr, 'encounter', 10, 120):
        return jsonify(success=False, error='Too fast'), 429
    try:
        data = request.get_json()
        text = sanitize_text(data.get('text',''),200)
        lat = data.get('lat'); lng = data.get('lng')
        if not text or lat is None or lng is None:
            return jsonify(success=False, error='text + lat + lng required'), 400
        try:
            lat_f = float(lat); lng_f = float(lng)
            if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
                return jsonify(success=False, error='Invalid coords'), 400
        except:
            return jsonify(success=False, error='Invalid coords'), 400
        encounters = load_json(ENCOUNTER_FILE, [])
        new_item = {"id": int(time.time()*1000),"text": text,"lat": lat_f,"lng": lng_f,"name": sanitize_text(data.get('name','Anonymous'),50),"date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),"status": ""}
        encounters.insert(0, new_item)
        save_json(ENCOUNTER_FILE, encounters)
        if data.get('pray'):
            prayers = load_json('data/prayers.json', [])
            prayers.append({"id": int(time.time()*1000)+1,"category": "Encounter","name": new_item['name'],"anonymous": False,"visibility": "private","content": f"Encounter at {lat_f:.4f},{lng_f:.4f}: {text}","contact": False,"date": datetime.now(TZ).strftime('%Y-%m-%d'),"pray_count": 0})
            save_json('data/prayers.json', prayers)
        return jsonify(success=True, id=new_item['id'])
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@app.route('/api/encounters', methods=['GET'])
@admin_required
def api_encounters_list():
    return jsonify(load_json(ENCOUNTER_FILE, []))

@app.route('/api/encounters/public-count', methods=['GET'])
def api_encounters_public_count():
    return jsonify({"count": len(load_json(ENCOUNTER_FILE, []))})

@app.route('/api/admin/encounters', methods=['GET','POST'])
@admin_required
def api_admin_encounters():
    if request.method == 'POST':
        data = request.get_json() or {}
        pwd = data.get('pwd','')
        if pwd and not verify_pwd(pwd, COUNSEL_PWD):
            return jsonify({"error":"Wrong password"}), 403
    return jsonify(load_json(ENCOUNTER_FILE, []))

@app.route('/api/admin/encounters/count')
@admin_required
def api_encounters_count():
    return jsonify({"count": len(load_json(ENCOUNTER_FILE, []))})

@app.route('/api/admin/update-encounter-status/<int:eid>', methods=['POST'])
@admin_required
def update_encounter_status(eid):
    data = request.get_json() or {}
    status = data.get('status','prayed')
    if status not in ['','prayed','visited','new']:
        status = 'prayed'
    encounters = load_json(ENCOUNTER_FILE, [])
    for e in encounters:
        if e.get('id')==eid:
            e['status']=status
            e['status_date']=datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
            break
    save_json(ENCOUNTER_FILE, encounters)
    return jsonify({"ok": True})

@app.route('/api/admin/delete-encounter/<int:eid>', methods=['POST'])
@admin_required
def delete_encounter(eid):
    encounters = load_json(ENCOUNTER_FILE, [])
    encounters = [e for e in encounters if e.get('id')!= eid]
    save_json(ENCOUNTER_FILE, encounters)
    return jsonify({"ok": True})

@app.route('/api/member/register', methods=['POST'])
def api_member_register():
    if not check_rate(request.remote_addr, 'register', 3, 300):
        return jsonify({"ok":False,"error":"Too many registrations"}),429
    try:
        photo_path = ""; data = {}
        if request.content_type and 'multipart/form-data' in request.content_type:
            photo_file = request.files.get('photo')
            if photo_file and photo_file.filename!= "":
                if allowed_file(photo_file.filename, {'jpg','jpeg','png','webp','gif'}):
                    fn = secure_filename(f"{int(time.time()*1000)}_{photo_file.filename}")
                    save_to = os.path.join('static/uploads/members', fn)
                    photo_file.save(save_to)
                    photo_path = f"uploads/members/{fn}"
                    clear_image_cache()
            raw = request.form.get('data')
            if raw: data = json.loads(raw)
            else:
                def jload(k):
                    try: return json.loads(request.form.get(k,'{}'))
                    except: return {}
                data = {"personal": jload('personal'),"contact": jload('contact'),"church": jload('church'),"spiritual": jload('spiritual'),"ministry": jload('ministry'),"emergency": jload('emergency'),"username": sanitize_text(request.form.get('username',''),50),"email": sanitize_text(request.form.get('email',''),100),"password": request.form.get('password',''),"terms": request.form.get('terms')=='true',"communication": request.form.get('communication')=='true'}
        else:
            data = request.get_json() or {}
            if data.get('photo_base64'):
                try:
                    import base64
                    fn = secure_filename(f"{int(time.time()*1000)}_member.jpg")
                    save_to = os.path.join('static/uploads/members', fn)
                    with open(save_to, 'wb') as f: f.write(base64.b64decode(data.get('photo_base64').split(',')[-1]))
                    photo_path = f"uploads/members/{fn}"
                    clear_image_cache()
                except: photo_path = ""
        members = load_json(MEMBERS_FILE, [])
        email = data.get('email','').strip().lower(); username = data.get('username','').strip()
        if not email or not username: return jsonify({"ok":False,"error":"Email and username required"}),400
        if '@' not in email: return jsonify({"ok":False,"error":"Invalid email"}),400
        if any(m.get('email','').lower()==email for m in members): return jsonify({"ok":False,"error":"Email already registered"}),400
        if any(m.get('username','').lower()==username.lower() for m in members): return jsonify({"ok":False,"error":"Username taken"}),400
        pwd = data.get('password','')
        if len(pwd) < 6: return jsonify({"ok":False,"error":"Password too short"}),400
        new_member = {"id": int(time.time()*1000),"personal": data.get('personal',{}),"contact": data.get('contact',{}),"church": data.get('church',{}),"spiritual": data.get('spiritual',{}),"ministry": data.get('ministry',{}),"emergency": data.get('emergency',{}),"photo": photo_path,"account": {"username": username, "email": email, "password": generate_password_hash(pwd)},"username": username,"email": email,"status": "pending","date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),"terms_accepted": data.get('terms', False),"communication_consent": data.get('communication', False)}
        members.insert(0, new_member); save_json(MEMBERS_FILE, members)
        return jsonify({"ok":True,"id":new_member['id']})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),500

@app.route('/api/member/login', methods=['POST'])
def api_member_login():
    if not check_rate(request.remote_addr, 'member_login', 5, 60):
        return jsonify({"ok":False,"error":"Too many attempts"}),429
    data = request.get_json(); login_val = sanitize_text(data.get('login','').strip(),100); pwd = data.get('password','')
    members = load_json(MEMBERS_FILE, []); user = next((m for m in members if m.get('email','').lower()==login_val.lower() or m.get('username','').lower()==login_val.lower()), None)
    if not user or not check_password_hash(user['account']['password'], pwd): return jsonify({"ok":False,"error":"Wrong credentials"}),401
    if user['status']=="pending": return jsonify({"ok":False,"error":"Your membership is under review by admin.","status":"pending"}),403
    if user['status']=="rejected": return jsonify({"ok":False,"error":"Membership rejected. Contact church office.","status":"rejected"}),403
    session['member_logged_in']=True; session['member_id']=user['id']; session['member_data']={"id":user['id'],"username":user['username'],"email":user['email'],"personal":user.get('personal',{}),"photo":user.get('photo',''),"status":user['status']}
    return jsonify({"ok":True,"member":session['member_data']})

@app.route('/api/member/me')
def api_member_me():
    if session.get('member_logged_in'):
        members = load_json(MEMBERS_FILE, [])
        m = next((x for x in members if x['id']==session.get('member_id')), None)
        if m and m['status']=='approved': return jsonify({"logged_in":True,"approved":True,"member":session.get('member_data')})
        return jsonify({"logged_in":True,"approved":False,"status":m['status'] if m else 'unknown'})
    return jsonify({"logged_in":False,"approved":False})

@app.route('/api/member/logout', methods=['POST'])
def api_member_logout():
    session.pop('member_logged_in',None); session.pop('member_id',None); session.pop('member_data',None)
    return jsonify({"ok":True})

@app.route('/api/member/change-password', methods=['POST'])
def api_member_change_password():
    if not session.get('member_logged_in'): return jsonify({"ok":False,"error":"Not logged in"}),401
    data = request.get_json(); old = data.get('old_password',''); new = data.get('new_password','')
    members = load_json(MEMBERS_FILE, [])
    for m in members:
        if m['id'] == session.get('member_id'):
            if not check_password_hash(m['account']['password'], old): return jsonify({"ok":False,"error":"Old password wrong"}),400
            if len(new) < 6: return jsonify({"ok":False,"error":"New password too short (min 6)"}),400
            m['account']['password'] = generate_password_hash(new); save_json(MEMBERS_FILE, members)
            return jsonify({"ok":True})
    return jsonify({"ok":False,"error":"Member not found"}),404

@app.route('/api/admin/members')
@admin_required
def api_admin_members(): return jsonify(load_json(MEMBERS_FILE, []))

@app.route('/api/admin/members/count')
@admin_required
def api_members_count():
    members = load_json(MEMBERS_FILE, [])
    pending = len([m for m in members if m['status']=='pending']); approved = len([m for m in members if m['status']=='approved'])
    return jsonify({"total":len(members),"pending":pending,"approved":approved})

@app.route('/api/admin/member/approve/<int:mid>', methods=['POST'])
@admin_required
def api_approve_member(mid):
    members=load_json(MEMBERS_FILE, [])
    for m in members:
        if m['id']==mid: m['status']='approved'; m['approved_date']=datetime.now(TZ).strftime("%Y-%m-%d %H:%M"); break
    save_json(MEMBERS_FILE, members); return jsonify({"ok":True})

@app.route('/api/admin/member/reject/<int:mid>', methods=['POST'])
@admin_required
def api_reject_member(mid):
    data = request.get_json() or {}; reason = sanitize_text(data.get('reason',''),200)
    members=load_json(MEMBERS_FILE, [])
    for m in members:
        if m['id']==mid: m['status']='rejected'; m['reject_reason']=reason; break
    save_json(MEMBERS_FILE, members); return jsonify({"ok":True})

@app.route('/api/admin/member/delete/<int:mid>', methods=['POST'])
@admin_required
def api_delete_member(mid):
    members=load_json(MEMBERS_FILE, []); members=[m for m in members if m['id']!=mid]; save_json(MEMBERS_FILE, members); return jsonify({"ok":True})

@app.route('/api/admin/upload-video', methods=['POST'])
@admin_required
def admin_upload_video():
    title = sanitize_text(request.form.get('title'),200); category = sanitize_text(request.form.get('category','sermon'),50); description = sanitize_text(request.form.get('description',''),1000); yt_raw = request.form.get('yt',''); yt = extract_yt_id(yt_raw); file = request.files.get('file'); filename=""
    if file and file.filename!= "":
        if allowed_file(file.filename, {'mp4','mov','webm','avi','mkv'}):
            filename = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/videos', filename)); filename = f"uploads/videos/{filename}"
    vids = load_json('data/videos.json', []); vids.append({"id": int(time.time()*1000),"title": title,"yt": yt,"yt_raw": sanitize_text(yt_raw,100),"local_file": filename,"category": category,"description": description,"date": datetime.now(TZ).strftime('%Y-%m-%d')}); save_json('data/videos.json', vids); clear_image_cache(); return jsonify({"ok": True})

@app.route('/api/admin/upload-gallery', methods=['POST'])
@admin_required
def admin_upload_gallery():
    title = sanitize_text(request.form.get('title'),200); category = sanitize_text(request.form.get('category','Events'),50); cover = request.form.get('cover','').strip(); visibility = request.form.get('visibility','public');
    if visibility not in ['public','members']: visibility='public'
    files = request.files.getlist('files'); urls_raw = request.form.get('images',''); saved=[]
    for f in files:
        if f and f.filename!= '' and allowed_file(f.filename, {'jpg','jpeg','png','webp','gif'}):
            fn = secure_filename(f"{int(time.time()*1000)}_{f.filename}"); f.save(os.path.join('static/uploads/gallery', fn)); saved.append(f"uploads/gallery/{fn}")
    if urls_raw:
        for u in urls_raw.split(','):
            if u.strip(): saved.append(sanitize_text(u.strip(),500))
    if cover and cover not in saved: saved.insert(0, sanitize_text(cover,500))
    final_cover = cover if cover else (saved[0] if saved else "uploads/god_key.jpg")
    albums = load_json('data/gallery.json', []); albums.append({"id": int(time.time()*1000),"title": title,"category": category,"cover": final_cover,"images": saved,"visibility": visibility,"date": datetime.now(TZ).strftime('%b %d, %Y')}); save_json('data/gallery.json', albums); clear_image_cache(); return jsonify({"ok": True})

@app.route('/api/admin/update-gallery-visibility/<int:gid>', methods=['POST'])
@admin_required
def update_gallery_visibility(gid):
    data = request.get_json(); visibility = data.get('visibility','public');
    if visibility not in ['public','members']: visibility='public'
    albums = load_json('data/gallery.json', [])
    for a in albums:
        if a['id']==gid: a['visibility']=visibility; break
    save_json('data/gallery.json', albums); return jsonify({"ok":True})

@app.route('/api/admin/sunday-upload-note', methods=['POST'])
@admin_required
def admin_upload_note():
    title = sanitize_text(request.form.get('title'),200); content = sanitize_text(request.form.get('content'),2000); file = request.files.get('file'); saved=""
    if file and file.filename!= "":
        if allowed_file(file.filename, {'pdf','docx','txt','pptx'}):
            fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/notes', fn)); saved = f"uploads/notes/{fn}"
    notes = load_json('data/sunday_school_notes.json', []); notes.append({"id": int(time.time()*1000),"title": title,"content": content,"file": saved,"size": f"{random.randint(500, 2000)} KB","date": datetime.now(TZ).strftime('%Y-%m-%d')}); save_json('data/sunday_school_notes.json', notes); return jsonify({"ok": True})

@app.route('/api/admin/sunday-upload-video', methods=['POST'])
@admin_required
def admin_upload_sunday_video():
    title = sanitize_text(request.form.get('title'),200); yt_raw = request.form.get('yt',''); yt = extract_yt_id(yt_raw); file = request.files.get('file'); saved=""
    if file and file.filename!= "":
        if allowed_file(file.filename, {'mp4','mov','webm'}):
            fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/videos', fn)); saved = f"uploads/videos/{fn}"
    vids = load_json('data/sunday_school_videos.json', []); vids.append({"id": int(time.time()*1000),"title": title,"yt": yt,"local_file": saved,"date": datetime.now(TZ).strftime('%Y-%m-%d')}); save_json('data/sunday_school_videos.json', vids); return jsonify({"ok": True})

@app.route('/api/admin/upload-sermon', methods=['POST'])
@admin_required
def admin_upload_sermon():
    title = sanitize_text(request.form.get('title'),200); speaker = sanitize_text(request.form.get('speaker'),100); stype = request.form.get('type','video'); series = sanitize_text(request.form.get('series',''),100); desc = sanitize_text(request.form.get('description',''),2000); yt_raw = request.form.get('yt',''); yt = extract_yt_id(yt_raw); file = request.files.get('file'); saved=""
    if file and file.filename!= "":
        fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/sermons', fn)); saved = f"uploads/sermons/{fn}"
    sermons = load_json('data/sermons.json', []); sermons.append({"id": int(time.time()*1000),"title": title,"speaker": speaker,"type": stype,"series": series,"description": desc,"yt": yt,"yt_raw": sanitize_text(yt_raw,100),"local_file": saved,"date": datetime.now(TZ).strftime('%Y-%m-%d')}); save_json('data/sermons.json', sermons); return jsonify({"ok": True})

@app.route('/api/admin/delete-video/<int:vid>', methods=['POST'])
@admin_required
def del_video(vid):
    vids = load_json('data/videos.json', []); vids = [v for v in vids if v['id']!= vid]; save_json('data/videos.json', vids); return jsonify({"ok": True})

@app.route('/api/admin/delete-gallery/<int:gid>', methods=['POST'])
@admin_required
def del_gallery(gid):
    albums = load_json('data/gallery.json', []); albums = [a for a in albums if a['id']!= gid]; save_json('data/gallery.json', albums); return jsonify({"ok": True})

@app.route('/api/admin/delete-sermon/<int:sid>', methods=['POST'])
@admin_required
def del_sermon(sid):
    sermons = load_json('data/sermons.json', []); sermons = [s for s in sermons if s['id']!= sid]; save_json('data/sermons.json', sermons); return jsonify({"ok": True})

@app.route('/api/admin/delete-note/<int:nid>', methods=['POST'])
@admin_required
def del_note(nid):
    notes = load_json('data/sunday_school_notes.json', []); notes = [n for n in notes if n['id']!= nid]; save_json('data/sunday_school_notes.json', notes); return jsonify({"ok": True})

@app.route('/api/admin/delete-sunday-video/<int:vid>', methods=['POST'])
@admin_required
def del_sunday_video(vid):
    vids = load_json('data/sunday_school_videos.json', []); vids = [v for v in vids if v['id']!= vid]; save_json('data/sunday_school_videos.json', vids); return jsonify({"ok": True})

@app.route('/api/admin/update-sermon/<int:sid>', methods=['POST'])
@admin_required
def update_sermon(sid):
    data = request.form; file = request.files.get('file'); sermons = load_json('data/sermons.json', [])
    for s in sermons:
        if s['id'] == sid:
            s['title'] = sanitize_text(data.get('title', s['title']),200); s['speaker'] = sanitize_text(data.get('speaker', s['speaker']),100); s['type'] = data.get('type', s['type']); s['series'] = sanitize_text(data.get('series', s['series']),100); s['description'] = sanitize_text(data.get('description', s['description']),2000)
            if data.get('yt','').strip(): s['yt'] = extract_yt_id(data.get('yt','')); s['yt_raw'] = sanitize_text(data.get('yt',''),100)
            if file and file.filename!= "": fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/sermons', fn)); s['local_file'] = f"uploads/sermons/{fn}"
            break
    save_json('data/sermons.json', sermons); return jsonify({"ok": True})

@app.route('/api/admin/update-video/<int:vid>', methods=['POST'])
@admin_required
def update_video(vid):
    data = request.form; file = request.files.get('file'); vids = load_json('data/videos.json', [])
    for v in vids:
        if v['id'] == vid:
            v['title'] = sanitize_text(data.get('title', v['title']),200); v['category'] = sanitize_text(data.get('category', v['category']),50); v['description'] = sanitize_text(data.get('description', v.get('description','')),1000)
            if data.get('yt','').strip(): v['yt'] = extract_yt_id(data.get('yt','')); v['yt_raw'] = sanitize_text(data.get('yt',''),100)
            if file and file.filename!= "": fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/videos', fn)); v['local_file'] = f"uploads/videos/{fn}"
            break
    save_json('data/videos.json', vids); return jsonify({"ok": True})

@app.route('/api/admin/update-gallery/<int:gid>', methods=['POST'])
@admin_required
def update_gallery(gid):
    data = request.form; albums = load_json('data/gallery.json', [])
    for a in albums:
        if a['id'] == gid:
            a['title'] = sanitize_text(data.get('title', a['title']),200); a['category'] = sanitize_text(data.get('category', a['category']),50)
            if data.get('cover','').strip(): a['cover'] = sanitize_text(data.get('cover','').strip(),500)
            if data.get('visibility'): a['visibility'] = data.get('visibility') if data.get('visibility') in ['public','members'] else 'public'
            break
    save_json('data/gallery.json', albums); return jsonify({"ok": True})

@app.route('/api/admin/update-note/<int:nid>', methods=['POST'])
@admin_required
def update_note(nid):
    data = request.form; file = request.files.get('file'); notes = load_json('data/sunday_school_notes.json', [])
    for n in notes:
        if n['id'] == nid:
            n['title'] = sanitize_text(data.get('title', n['title']),200); n['content'] = sanitize_text(data.get('content', n.get('content','')),5000)
            if file and file.filename!= "": fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/notes', fn)); n['file'] = f"uploads/notes/{fn}"
            break
    save_json('data/sunday_school_notes.json', notes); return jsonify({"ok": True})

@app.route('/admin/quiz')
@admin_required
def admin_quiz(): return render_template('admin_quiz.html', quiz=get_quiz())

@app.route('/api/admin/upload-event', methods=['POST'])
@admin_required
def admin_upload_event():
    title = sanitize_text(request.form.get('title'),200); date = sanitize_text(request.form.get('date'),20); time_e = sanitize_text(request.form.get('time',''),20); location = sanitize_text(request.form.get('location',''),200); desc = sanitize_text(request.form.get('description',''),2000); file = request.files.get('file'); saved=""
    if file and file.filename!= "":
        if allowed_file(file.filename, {'jpg','jpeg','png','webp'}):
            fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/events', fn)); saved = f"uploads/events/{fn}"
    events = load_json('data/events.json', []); events.append({"id": int(time.time()*1000),"title": title,"date": date,"time": time_e,"location": location,"description": desc,"image": saved,"created": datetime.now(TZ).strftime('%Y-%m-%d')}); save_json('data/events.json', events); clear_image_cache(); return jsonify({"ok": True})

@app.route('/api/admin/delete-event/<int:eid>', methods=['POST'])
@admin_required
def del_event(eid):
    events = load_json('data/events.json', []); events = [e for e in events if e['id']!= eid]; save_json('data/events.json', events); return jsonify({"ok": True})

@app.route('/api/admin/update-event/<int:eid>', methods=['POST'])
@admin_required
def update_event(eid):
    data = request.form; file = request.files.get('file'); events = load_json('data/events.json', [])
    for ev in events:
        if ev['id'] == eid:
            ev['title'] = sanitize_text(data.get('title', ev['title']),200); ev['date'] = sanitize_text(data.get('date', ev['date']),20); ev['time'] = sanitize_text(data.get('time', ev['time']),20); ev['location'] = sanitize_text(data.get('location', ev['location']),200); ev['description'] = sanitize_text(data.get('description', ev['description']),2000)
            if file and file.filename!= "": fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/events', fn)); ev['image'] = f"uploads/events/{fn}"
            break
    save_json('data/events.json', events); return jsonify({"ok": True})

@app.route('/api/events/register', methods=['POST'])
def register_event():
    data = request.get_json(); regs = load_json('data/event_registrations.json', [])
    regs.append({"id": int(time.time() * 1000),"event_id": data.get('event_id'),"event_title": sanitize_text(data.get('event_title'),200),"name": sanitize_text(data.get('name'),100),"phone": sanitize_text(data.get('phone'),20),"email": sanitize_text(data.get('email',''),100),"people": int(data.get('people',1)),"date": datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}); save_json('data/event_registrations.json', regs); return jsonify({"ok": True})

@app.route('/api/events/registrations')
def api_registrations(): return jsonify(load_json('data/event_registrations.json', []))

@app.route('/api/admin/delete-registration/<int:rid>', methods=['POST'])
@admin_required
def del_reg(rid):
    regs = load_json('data/event_registrations.json', []); regs = [r for r in regs if r['id']!= rid]; save_json('data/event_registrations.json', regs); return jsonify({"ok": True})

@app.route('/api/admin/prayers/private', methods=['GET','POST'])
@admin_required
def private_prayers_admin():
    pwd = ""
    if request.method == 'POST':
        data = request.get_json() or {}
        pwd = data.get('pwd','')
    else:
        pwd = request.args.get('pwd','')
    if not verify_pwd(pwd, PASTOR_PASSWORD): return jsonify({"error": "Wrong pastor password"}), 403
    prayers = load_json('data/prayers.json', []); private = [p for p in prayers if p.get('visibility') == 'private']; return jsonify(private)

@app.route('/api/admin/update-prayer/<int:pid>', methods=['POST'])
@admin_required
def update_prayer_admin(pid):
    data = request.form; prayers = load_json('data/prayers.json', [])
    for p in prayers:
        if p['id'] == pid:
            p['category'] = sanitize_text(data.get('category', p['category']),50); p['name'] = sanitize_text(data.get('name', p['name']),100); p['content'] = sanitize_text(data.get('content', p['content']),2000); p['visibility'] = data.get('visibility', p['visibility']) if data.get('visibility') in ['public','private'] else p['visibility']; break
    save_json('data/prayers.json', prayers); return jsonify({"ok": True})

@app.route('/api/admin/delete-prayer/<int:pid>', methods=['POST'])
@admin_required
def delete_prayer_admin(pid):
    prayers = load_json('data/prayers.json', []); prayers = [p for p in prayers if p['id']!= pid]; save_json('data/prayers.json', prayers); return jsonify({"ok": True})

@app.route('/api/admin/quiz-data')
@admin_required
def admin_quiz_data(): return jsonify(get_quiz())

@app.route('/api/admin/add-quiz', methods=['POST'])
@admin_required
def add_quiz():
    data = request.get_json(); quiz = get_quiz(); level = data.get('level','sunday')
    if level not in quiz: quiz[level] = []
    new_id = max([q['id'] for q in quiz[level]], default=0) + 1
    quiz[level].append({"id": new_id,"q": sanitize_text(data['q'],500),"options": [sanitize_text(o,200) for o in data['options']],"answer": int(data['answer']),"ref": sanitize_text(data['ref'],100),"book": sanitize_text(data['book'],100)}); save_json(QUIZ_FILE, quiz); return jsonify({"ok": True})

@app.route('/api/admin/delete-quiz', methods=['POST'])
@admin_required
def delete_quiz_q():
    data = request.get_json(); level = data.get('level'); idd = data.get('id'); quiz = get_quiz(); quiz[level] = [q for q in quiz.get(level, []) if q['id']!= idd]; save_json(QUIZ_FILE, quiz); return jsonify({"ok": True})

@app.route('/contact/send', methods=['POST'])
def contact_send():
    if not check_rate(request.remote_addr, 'contact', 5, 120):
        return jsonify({"ok": False, "error": "Too fast"}), 429
    name = sanitize_text(request.form.get('name','').strip(),100); email = sanitize_text(request.form.get('email','').strip(),100); message = sanitize_text(request.form.get('message','').strip(),2000)
    if not name or not email or not message: return jsonify({"ok": False, "error": "All fields required"}), 400
    contacts = load_json(CONTACT_FILE, []); contacts.insert(0, {"id": int(time.time() * 1000),"name": name,"email": email,"message": message,"date": datetime.now(TZ).strftime("%Y-%m-%d"),"time": datetime.now(TZ).strftime("%H:%M:%S")}); save_json(CONTACT_FILE, contacts); return jsonify({"ok": True})

@app.route('/api/contact/messages')
@admin_required
def api_contact_messages(): return jsonify(load_json(CONTACT_FILE, []))

@app.route('/api/admin/delete-contact/<int:cid>', methods=['POST'])
@admin_required
def delete_contact(cid):
    contacts = load_json(CONTACT_FILE, []); contacts = [c for c in contacts if c['id']!= cid]; save_json(CONTACT_FILE, contacts); return jsonify({"ok": True})

@app.route('/api/admin/counselling/private', methods=['GET','POST'])
@admin_required
def api_counselling_private():
    pwd = ""
    if request.method == 'POST':
        data = request.get_json() or {}
        pwd = data.get('pwd','')
    else:
        pwd = request.args.get('pwd','')
    if not verify_pwd(pwd, COUNSEL_PWD): return jsonify({"error": "Wrong password"}), 403
    return jsonify(load_json(COUNSELLING_FILE, []))

@app.route('/api/admin/counselling/count')
@admin_required
def api_counselling_count(): return jsonify({"count": len(load_json(COUNSELLING_FILE, []))})

@app.route('/api/counselling-requests/count')
@admin_required
def api_counselling_count_public(): return jsonify({"count": len(load_json(COUNSELLING_FILE, []))})

@app.route('/api/admin/delete-counselling/<int:cid>', methods=['POST'])
@admin_required
def delete_counselling(cid):
    data = request.get_json() or {}
    pwd = data.get('pwd','') or request.args.get('pwd','')
    if not verify_pwd(pwd, COUNSEL_PWD): return jsonify({"error": "Wrong password"}), 403
    d = load_json(COUNSELLING_FILE, []); d = [x for x in d if x.get('id')!= cid]; save_json(COUNSELLING_FILE, d); return jsonify({"ok": True})

@app.route('/api/admin/update-sunday-video/<int:vid>', methods=['POST'])
@admin_required
def update_sunday_video(vid):
    data = request.form; file = request.files.get('file'); vids = load_json('data/sunday_school_videos.json', [])
    for v in vids:
        if v['id'] == vid:
            v['title'] = sanitize_text(data.get('title', v['title']),200)
            if data.get('yt','').strip(): v['yt'] = extract_yt_id(data.get('yt',''))
            if file and file.filename!= "": fn = secure_filename(f"{int(time.time()*1000)}_{file.filename}"); file.save(os.path.join('static/uploads/videos', fn)); v['local_file'] = f"uploads/videos/{fn}"
            break
    save_json('data/sunday_school_videos.json', vids); return jsonify({"ok": True})

@app.route('/api/member/qr-info')
def api_member_qr_info():
    if not session.get('member_logged_in'):
        return jsonify({"ok": False, "error": "Not logged in"}), 401
    mid = session.get('member_id')
    members = load_json(MEMBERS_FILE, [])
    m = next((x for x in members if x['id']==mid), None)
    if not m:
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "id": m['id'], "username": m['username'], "name": m.get('personal',{}).get('fullName',''), "status": m['status'], "photo": m.get('photo','')})

@app.route('/api/member/my-qr')
def api_member_my_qr():
    if not session.get('member_logged_in'):
        return jsonify({"ok": False, "error": "Not logged in"}), 401
    mid = session.get('member_id')
    members = load_json(MEMBERS_FILE, [])
    m = next((x for x in members if x['id']==mid), None)
    if not m or m['status']!='approved':
        return jsonify({"ok": False, "error": "Not approved"}), 403
    expiry = int(time.time()) + 300
    payload = f"{mid}:{expiry}"
    sig = hmac.new(QR_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    token = f"{payload}:{sig}"
    b64 = base64.urlsafe_b64encode(token.encode()).decode().rstrip('=')
    return jsonify({"ok": True, "id": mid, "token": b64, "expires_in": 300, "expiry": expiry})

# SINGLE SECURE CHECKIN - handles raw ID + signed token - NO DUPLICATE
@app.route('/api/admin/checkin', methods=['POST'])
@admin_required
def api_admin_checkin_secure():
    if not check_rate(request.remote_addr, 'checkin', 30, 60):
        return jsonify({"ok": False, "error": "Too fast"}), 429
    data = request.get_json() or {}
    raw = data.get('member_id') or data.get('token') or data.get('qr') or data.get('id') or ""
    raw = str(raw).strip()
    mid = 0
    try:
        # try base64 signed token
        s = raw
        pad = '=' * (-len(s) % 4)
        try:
            decoded = base64.urlsafe_b64decode(s+pad).decode()
            parts = decoded.split(':')
            if len(parts)==3:
                mid_p = int(parts[0]); exp = int(parts[1]); sig = parts[2]
                payload = f"{mid_p}:{exp}"
                expected = hmac.new(QR_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
                if not hmac.compare_digest(expected, sig):
                    return jsonify({"ok": False, "error": "Invalid signature"}), 403
                if time.time() > exp:
                    return jsonify({"ok": False, "error": "QR expired — ask member to refresh"}), 403
                mid = mid_p
            else:
                mid = int(raw)
        except:
            mid = int(raw)
    except:
        return jsonify({"ok": False, "error": "Invalid QR"}), 400

    if not mid:
        return jsonify({"ok": False, "error": "member_id required"}), 400
    members = load_json(MEMBERS_FILE, [])
    member = next((x for x in members if x['id']==mid), None)
    if not member:
        return jsonify({"ok": False, "error": "Member not found"}), 404
    if member['status']!='approved':
        return jsonify({"ok": False, "error": "Not approved"}), 403
    checkins = load_json(CHECKIN_FILE, [])
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    already = next((c for c in checkins if c['member_id']==mid and c['date']==today), None)
    if already:
        return jsonify({"ok": False, "error": f"Already checked-in today at {already['time']}", "member": member})
    new_check = {"id": int(time.time()*1000), "member_id": mid, "username": member['username'], "name": sanitize_text(member.get('personal',{}).get('fullName', member['username']),100), "photo": member.get('photo',''), "date": today, "time": datetime.now(TZ).strftime("%H:%M:%S"), "datetime": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")}
    checkins.insert(0, new_check)
    save_json(CHECKIN_FILE, checkins)
    return jsonify({"ok": True, "checkin": new_check, "member": member})

@app.route('/api/admin/checkins')
@admin_required
def api_admin_checkins():
    date = sanitize_text(request.args.get('date') or datetime.now(TZ).strftime("%Y-%m-%d"),20)
    checkins = load_json(CHECKIN_FILE, [])
    filtered = [c for c in checkins if c['date']==date]
    return jsonify(filtered)

@app.route('/api/admin/checkins/count')
@admin_required
def api_checkins_count():
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    checkins = load_json(CHECKIN_FILE, [])
    today_c = [c for c in checkins if c['date']==today]
    return jsonify({"count": len(today_c), "date": today})

@app.route('/api/seek-counsel', methods=['POST'])
def seek_counsel():
    feeling = sanitize_text(request.json.get('feeling','').lower(),100)
    bible = {'anxious': [{"ref":"Philippians 4:6-7", "text":"Do not be anxious about anything...","counsel":"God will guard your heart with peace."}],'fear': [{"ref":"Isaiah 41:10", "text":"Fear not, for I am with you...","counsel":"God is with you."}],}
    verses=None
    for k in bible:
        if k in feeling: verses=bible[k]; break
    if not verses: verses=[{"ref":"Jeremiah 29:11","text":"For I know the plans I have for you...","counsel":"God has a good plan for you."},{"ref":"Psalm 23:1","text":"The Lord is my shepherd, I lack nothing."}]
    return jsonify({"verses": verses})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port)