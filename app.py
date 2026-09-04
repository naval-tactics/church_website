
from flask import Flask, render_template, request, session, jsonify, send_from_directory, redirect, url_for, Response
from datetime import datetime, timedelta
import pytz
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps, lru_cache
import random, json, os, time, re, html, hmac, hashlib, base64

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
GOOGLE_VERIFICATION = "tY5CbaEWI9pyFRc4Qmr0ya7EXdJqFOA52OX_mbQvXZU"

try:
    import cloudinary, cloudinary.uploader
    cloudinary.config(cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"), api_key=os.environ.get("CLOUDINARY_API_KEY"), api_secret=os.environ.get("CLOUDINARY_API_SECRET"), secure=True)
    CLOUDINARY_ENABLED = bool(os.environ.get("CLOUDINARY_CLOUD_NAME") and os.environ.get("CLOUDINARY_API_KEY"))
except Exception:
    CLOUDINARY_ENABLED = False

try:
    from flask_caching import Cache
    cache = Cache(app, config={'CACHE_TYPE':'SimpleCache','CACHE_DEFAULT_TIMEOUT':300})
except Exception:
    cache = None
try:
    from flask_compress import Compress
    Compress(app)
except: pass
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(get_remote_address, app=app, default_limits=["500 per day", "100 per hour"], storage_uri="memory://")
except Exception:
    limiter = None

def armor_limit(limit_str):
    def decorator(f):
        if limiter: return limiter.limit(limit_str)(f)
        return f
    return decorator
def cache_page(timeout=300):
    def decorator(f):
        if cache: return cache.cached(timeout=timeout)(f)
        return f
    return decorator

def upload_to_cloudinary(file_obj, folder="south_b_chapel"):
    if not file_obj or file_obj.filename == "": return ""
    if CLOUDINARY_ENABLED:
        try:
            try: file_obj.stream.seek(0)
            except: pass
            res = cloudinary.uploader.upload(file_obj, folder=folder, resource_type="auto")
            url = res.get('secure_url')
            if url: return url
        except Exception as e:
            print(f"Cloudinary failed: {e}")
    try:
        fn = secure_filename(f"{int(time.time()*1000)}_{file_obj.filename}")
        if 'videos' in folder: local_folder = 'static/uploads/videos'
        elif 'gallery' in folder: local_folder = 'static/uploads/gallery'
        elif 'members' in folder: local_folder = 'static/uploads/members'
        elif 'events' in folder: local_folder = 'static/uploads/events'
        elif 'sermons' in folder: local_folder = 'static/uploads/sermons'
        elif 'notes' in folder: local_folder = 'static/uploads/notes'
        elif 'testimonies' in folder: local_folder = 'static/testimonies'
        elif 'sunday' in folder: local_folder = 'static/uploads/notes'
        else: local_folder = 'static/uploads/gallery'
        os.makedirs(local_folder, exist_ok=True)
        try: file_obj.stream.seek(0)
        except: pass
        path = os.path.join(local_folder, fn)
        file_obj.save(path)
        if 'testimonies' in local_folder: return fn
        return f"{local_folder.replace('static/','')}/{fn}".replace("\\","/")
    except Exception as e:
        print(f"Local save failed: {e}")
        return ""

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
        if file in _json_cache and _json_mtime.get(file)==mtime: return _json_cache[file]
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
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
    os.replace(tmp, file)
    _json_cache[file]=data
    try: _json_mtime[file]=os.path.getmtime(file)
    except: _json_mtime[file]=time.time()
def check_rate(ip, key, limit=10, window=60):
    now = time.time()
    bucket = rate_limit.get(f"{ip}_{key}", [])
    bucket = [t for t in bucket if now - t < window]
    if len(bucket) >= limit: return False
    bucket.append(now)
    rate_limit[f"{ip}_{key}"] = bucket
    return True
def clear_image_cache():
    try:
        find_file_cached.cache_clear()
        get_images_dict_cached.cache_clear()
        if cache: cache.clear()
    except: pass
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            if request.path.startswith('/api/'): return jsonify({"error": "Unauthorized"}), 401
            return render_template('admin_login.html')
        if time.time() - session.get('admin_time', 0) > 1800:
            session.clear()
            return render_template('admin_login.html', error="Session expired")
        session['admin_time'] = time.time()
        if request.method == 'POST' and request.path.startswith('/api/admin/'):
            token = request.headers.get('X-CSRF-Token') or request.headers.get('X-CSRFToken')
            sess_token = session.get('csrf_token')
            if sess_token and token!= sess_token:
                if not token: token = request.form.get('csrf_token','')
                if token!= sess_token: return jsonify({"error": "CSRF failed"}), 403
        return f(*args, **kwargs)
    return decorated
def allowed_file(filename, allowed): return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed
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
def verify_pwd(req_pwd, expected): return req_pwd == expected

@lru_cache(maxsize=128)
def find_file_cached(base_name: str) -> str:
    base_name = re.sub(r'[^a-zA-Z0-9_\-/]', '', base_name.strip())
    base_name = base_name.strip('/').strip('\\')
    if '..' in base_name: return "uploads/logoon.jpeg"
    static_dir = Path(app.static_folder)
    clean_stem = Path(base_name).name.lower()
    extensions = ['.webp', '.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mov', '.webm']
    for ext in extensions:
        p = static_dir / f"{base_name}{ext}"
        try:
            if p.exists() and p.resolve().is_relative_to(static_dir.resolve()): return f"{base_name}{ext}"
        except: pass
        p_lower = static_dir / f"{base_name.lower()}{ext}"
        try:
            if p_lower.exists() and p_lower.resolve().is_relative_to(static_dir.resolve()): return str(p_lower.relative_to(static_dir)).replace("\\", "/")
        except: pass
    for file in static_dir.rglob("*"):
        if not file.is_file(): continue
        if file.stem.lower() == clean_stem:
            try:
                if file.resolve().is_relative_to(static_dir.resolve()): return str(file.relative_to(static_dir)).replace("\\", "/")
            except: continue
    return f"{base_name}.png"
def find_file(base_name: str) -> str: return find_file_cached(base_name)
@lru_cache(maxsize=1)
def get_images_dict_cached():
    return {'gate': find_file('gate'),'clock': find_file('clock'),'mountains': find_file('mountains'),'jesus': find_file('jesus'),'seasons': find_file('seasons'),'bread': find_file('bread'),'flower': find_file('flower'),'christmas': find_file('holidays/christmas/christmas'),'newyear': find_file('holidays/newyear/newyear'),'easter': find_file('holidays/easter/easter'),'sunday': find_file('holidays/sunday/sunday')}
def get_images_dict(): return get_images_dict_cached()
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
            if h['key'] == test: return {'active': h['key'], 'info': h, 'now': now.isoformat(), 'is_countdown': False, 'days_left': 0}
    for h in holidays:
        if h['key'] == 'sunday':
            if is_sunday: return {'active': 'sunday', 'info': h, 'now': now.isoformat(), 'is_countdown': False, 'days_left': 0}
            continue
        if h['theme_start'] <= now <= h['theme_end']: return {'active': h['key'], 'info': h, 'now': now.isoformat(), 'is_countdown': False, 'days_left': (h['date'] - now).days}
        if h['countdown_start'] and h['countdown_start'] <= now < h['theme_start']: return {'active': h['key'], 'info': h, 'now': now.isoformat(), 'is_countdown': True, 'days_left': (h['date'] - now).days}
    return {'active': 'normal', 'info': None, 'now': now.isoformat(), 'is_countdown': False, 'days_left': 0}
def get_next_sunday_8am():
    now = datetime.now(TZ)
    days_ahead = (6 - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= 8: days_ahead = 7
    ns = now + timedelta(days=days_ahead)
    return ns.replace(hour=8, minute=0, second=0, microsecond=0).isoformat()

@app.after_request
def after_request(response):
    if response.content_type and 'text/html' in response.content_type:
        try:
            data = response.get_data(as_text=True)
            if '<head>' in data and 'google-site-verification' not in data:
                meta = f'<meta name="google-site-verification" content="{GOOGLE_VERIFICATION}" />'
                data = data.replace('<head>', f'<head>\n{meta}', 1)
                response.set_data(data)
        except: pass
    if request.path.startswith('/static/'): response.headers["Cache-Control"] = "public, max-age=604800"
    elif request.path.startswith('/api/'): response.headers["Cache-Control"] = "no-store"
    else: response.headers["Cache-Control"] = "public, max-age=60"
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
@cache_page(timeout=300)
def home(): return render_template('index.html', next_sunday=get_next_sunday_8am(), images=get_images_dict(), holiday=get_holiday_info())
@app.route('/events')
@cache_page(timeout=300)
def events_page(): return render_template('events.html', images=get_images_dict(), holiday=get_holiday_info(), events=load_json('data/events.json', []), next_sunday=get_next_sunday_8am())
@app.route('/sermons')
@cache_page(timeout=300)
def sermons_page(): return render_template('sermons.html', images=get_images_dict(), holiday=get_holiday_info(), sermons=load_json('data/sermons.json', []), next_sunday=get_next_sunday_8am())
@app.route('/videos')
@cache_page(timeout=300)
def videos_page(): return render_template('videos.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), items=load_json('data/videos.json', []), videos=load_json('data/videos.json', []))
@app.route('/gallery')
@cache_page(timeout=300)
def gallery_page():
    albums = load_json('data/gallery.json', [])
    for a in albums:
        if 'visibility' not in a: a['visibility'] = 'public'
    if not session.get('member_logged_in'): albums = [a for a in albums if a.get('visibility','public')=='public']
    return render_template('gallery.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), gallery=albums, items=albums)
@app.route('/prayer-wall')
@cache_page(timeout=60)
def prayer_wall(): return render_template('prayer.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), prayers=[p for p in load_json('data/prayers.json', []) if p.get('visibility', 'public') == 'public'])
@app.route('/contact')
def contact(): return render_template('contact.html', images=get_images_dict(), holiday=get_holiday_info(), team=[{'name': 'Caudensha Sawe', 'role': 'Senior Chaplain', 'phone': '0721424392', 'photo': find_file('team/caudensha')}], next_sunday=get_next_sunday_8am())
@app.route('/bible-quiz')
def bible_quiz(): return render_template('quiz.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())
@app.route('/counselling')
@app.route('/counselling-care')
def counselling(): return render_template('counselling-care.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())
@app.route('/sunday-school')
def sunday_school(): return render_template('sunday.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), notes=load_json('data/sunday_school_notes.json', []), sunday_videos=load_json('data/sunday_school_videos.json', []))
@app.route('/faith-arcade')
def faith_arcade(): return render_template('faith_arcade.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())
@app.route('/member-qualifications')
def member_qualifications(): return render_template('member_qualifications.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())
@app.route('/members/register')
def members_register_page(): return render_template('member_register.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())
@app.route('/members/login')
def members_login_page(): return render_template('member_login.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am())
@app.route('/members/dashboard')
def members_dashboard_page():
    if not session.get('member_logged_in'): return render_template('member_login.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), error="Please login as member")
    return render_template('member_dashboard.html', images=get_images_dict(), holiday=get_holiday_info(), next_sunday=get_next_sunday_8am(), member=session.get('member_data'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    ip = request.remote_addr
    attempts = login_attempts.get(ip, {'count': 0, 'time': 0})
    if attempts['count'] >= 5 and time.time() - attempts['time'] < 900: return render_template('admin_login.html', error="Too many attempts. Try after 15 mins")
    if request.method == 'POST':
        u = request.form.get('username','').strip(); p = request.form.get('password','')
        if u == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, p):
            session['admin_logged_in'] = True; session['admin_time'] = time.time(); session['csrf_token'] = os.urandom(16).hex()
            login_attempts[ip] = {'count': 0, 'time': 0}
            return redirect(url_for('admin_dashboard'))
        else:
            login_attempts[ip] = {'count': attempts['count'] + 1, 'time': time.time()}
            return render_template('admin_login.html', error=f"Wrong! Attempt {attempts['count'] + 1}/5")
    return render_template('admin_login.html')

@app.route('/admin/logout', methods=['GET', 'POST'])
def admin_logout(): session.clear(); return redirect(url_for('admin_login'))
@app.route('/admin', methods=['GET', 'POST'])
@app.route('/admin/', methods=['GET', 'POST'])
@app.route('/admin/dashboard', methods=['GET', 'POST'])
@app.route('/admin/dashboard/', methods=['GET', 'POST'])
@admin_required
def admin_dashboard():
    if 'csrf_token' not in session: session['csrf_token'] = os.urandom(16).hex()
    return render_template('admin_dashboard.html', images=get_images_dict(), csrf_token=session['csrf_token'])

@app.errorhandler(405)
def method_not_allowed(e):
    if request.path.startswith('/admin'):
        if session.get('admin_logged_in'): return redirect(url_for('admin_dashboard'))
        return redirect(url_for('admin_login'))
    return "Method Not Allowed", 405

@app.route('/api/videos')
def api_videos(): return jsonify(load_json('data/videos.json', []))
@app.route('/api/gallery')
def api_gallery():
    albums = load_json('data/gallery.json', [])
    for a in albums:
        if 'visibility' not in a: a['visibility'] = 'public'
    if not session.get('member_logged_in'): albums = [a for a in albums if a.get('visibility','public')=='public']
    return jsonify(albums)
@app.route('/api/admin/gallery/all')
@admin_required
def api_admin_gallery_all(): return jsonify(load_json('data/gallery.json', []))
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
@armor_limit("10 per minute")
def submit_prayer_wall():
    if not check_rate(request.remote_addr, 'prayer', 5, 60): return jsonify({"ok": False, "error": "Too fast"}), 429
    prayers = load_json('data/prayers.json', [])
    prayers.append({"id": int(time.time() * 1000),"category": sanitize_text(request.form.get('category','General'),50),"name": sanitize_text(request.form.get('name',''),100),"anonymous": bool(request.form.get('anonymous')),"visibility": request.form.get('visibility','public') if request.form.get('visibility') in ['public','private'] else 'public',"content": sanitize_text(request.form.get('content',''),1000),"contact": bool(request.form.get('contact')),"date": datetime.now(TZ).strftime('%Y-%m-%d'),"pray_count": 0})
    save_json('data/prayers.json', prayers)
    if cache: cache.delete_memoized(prayer_wall)
    return jsonify({"ok": True})
@app.route('/prayer/pray/<int:pid>', methods=['POST'])
@armor_limit("30 per minute")
def pray_count_wall(pid):
    prayers = load_json('data/prayers.json', []); count=0
    for p in prayers:
        if p['id']==pid: p['pray_count']=p.get('pray_count',0)+1; count=p['pray_count']; break
    save_json('data/prayers.json', prayers)
    return jsonify({"count": count})
@app.route('/api/counselling-request', methods=['POST'])
@armor_limit("5 per minute")
def save_counselling():
    if not check_rate(request.remote_addr, 'counselling', 5, 120): return jsonify({"success": False, "error": "Too many requests"}), 429
    data = request.get_json(); msgs = load_json(COUNSELLING_FILE, [])
    msgs.insert(0, {"id": int(time.time()*1000),"name": sanitize_text(data.get('name',''),100),"phone": sanitize_text(data.get('phone',''),20),"age_group": sanitize_text(data.get('age_group',''),20),"category": sanitize_text(data.get('category',''),50),"description": sanitize_text(data.get('description',''),2000),"is_anonymous": bool(data.get('is_anonymous', False)),"preferred_time": sanitize_text(data.get('preferred_time','Any'),20),"date": datetime.now(TZ).strftime("%Y-%m-%d"),"time": datetime.now(TZ).strftime("%H:%M:%S")})
    save_json(COUNSELLING_FILE, msgs)
    return jsonify({"success": True, "id": msgs[0]['id']})
@app.route('/api/testimony', methods=['POST'])
@armor_limit("3 per minute")
def api_testimony():
    if not check_rate(request.remote_addr, 'testimony', 3, 300): return jsonify(success=False, error='Too many uploads, try later'), 429
    try:
        os.makedirs('static/testimonies', exist_ok=True)
        if 'audio' not in request.files: return jsonify(success=False, error='No audio file'), 400
        f = request.files['audio']
        if f.filename == '': return jsonify(success=False, error='Empty filename'), 400
        cloud_url = upload_to_cloudinary(f, folder="south_b_chapel/testimonies")
        if cloud_url.startswith('http'): filename = cloud_url
        else: filename = cloud_url.split('/')[-1] if '/' in cloud_url else cloud_url
        name = sanitize_text(request.form.get('name','Anonymous'),100) or 'Anonymous'
        phone = sanitize_text(request.form.get('phone',''),20)
        records = load_json(TESTIMONY_FILE, [])
        new_id = int(time.time()*1000)
        records.insert(0, {"id": new_id,"filename": filename,"path": f"testimonies/{filename}" if not filename.startswith('http') else filename,"cloud_url": filename if filename.startswith('http') else "","name": name,"phone": phone,"date": datetime.now(TZ).strftime("%Y-%m-%d"),"time": datetime.now(TZ).strftime("%H:%M:%S")})
        save_json(TESTIMONY_FILE, records)
        transcripts = load_json(TRANSCRIPTS_FILE, [])
        transcripts.append({"testimony_id": new_id, "text": f"[{name}] - testimony", "date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")})
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
        if not verify_pwd(pwd, COUNSEL_PWD): return jsonify({"error":"Wrong password"}), 403
    return jsonify(load_json(TESTIMONY_FILE, []))
@app.route('/api/admin/testimonies/count')
@admin_required
def api_testimonies_count(): return jsonify({"count": len(load_json(TESTIMONY_FILE, []))})
@app.route('/api/admin/transcripts', methods=['GET'])
@admin_required
def admin_transcripts(): return jsonify(load_json(TRANSCRIPTS_FILE, []))
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
@armor_limit("10 per minute")
def api_encounter_save():
    if not check_rate(request.remote_addr, 'encounter', 10, 120): return jsonify(success=False, error='Too fast'), 429
    try:
        data = request.get_json()
        text = sanitize_text(data.get('text',''),200)
        lat = data.get('lat'); lng = data.get('lng')
        if not text or lat is None or lng is None: return jsonify(success=False, error='text + lat + lng required'), 400
        try:
            lat_f = float(lat); lng_f = float(lng)
            if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180): return jsonify(success=False, error='Invalid coords'), 400
        except: return jsonify(success=False, error='Invalid coords'), 400
        encounters = load_json(ENCOUNTER_FILE, [])
        new_item = {"id": int(time.time()*1000),"text": text,"lat": lat_f,"lng": lng_f,"name": sanitize_text(data.get('name','Anonymous'),50),"date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),"status": ""}
        encounters.insert(0, new_item)
        save_json(ENCOUNTER_FILE, encounters)
        if data.get('pray'):
            prayers = load_json('data/prayers.json', [])
            prayers.append({"id": int(time.time()*1000)+1,"category": "Encounter","name": new_item['name'],"anonymous": False,"visibility": "private","content": f"Encounter at {lat_f:.4f},{lng_f:.4f}: {text}","contact": False,"date": datetime.now(TZ).strftime('%Y-%m-%d'),"pray_count": 0})
            save_json('data/prayers.json', prayers)
        return jsonify(success=True, id=new_item['id'])
    except Exception as e: return jsonify(success=False, error=str(e)), 500
@app.route('/api/encounters', methods=['GET'])
@admin_required
def api_encounters_list(): return jsonify(load_json(ENCOUNTER_FILE, []))
@app.route('/api/encounters/public-count', methods=['GET'])
def api_encounters_public_count(): return jsonify({"count": len(load_json(ENCOUNTER_FILE, []))})
@app.route('/api/admin/encounters', methods=['GET','POST'])
@admin_required
def api_admin_encounters():
    if request.method == 'POST':
        data = request.get_json() or {}
        pwd = data.get('pwd','')
        if pwd and not verify_pwd(pwd, COUNSEL_PWD): return jsonify({"error":"Wrong password"}), 403
    return jsonify(load_json(ENCOUNTER_FILE, []))
@app.route('/api/admin/encounters/count')
@admin_required
def api_encounters_count(): return jsonify({"count": len(load_json(ENCOUNTER_FILE, []))})
@app.route('/api/admin/update-encounter-status/<int:eid>', methods=['POST'])
@admin_required
def update_encounter_status(eid):
    data = request.get_json() or {}
    status = data.get('status','prayed')
    if status not in ['','prayed','visited','new']: status = 'prayed'
    encounters = load_json(ENCOUNTER_FILE, [])
    for e in encounters:
        if e.get('id')==eid: e['status']=status; e['status_date']=datetime.now(TZ).strftime("%Y-%m-%d %H:%M"); break
    save_json(ENCOUNTER_FILE, encounters)
    return jsonify({"ok": True})
@app.route('/api/admin/delete-encounter/<int:eid>', methods=['POST'])
@admin_required
def delete_encounter(eid):
    encounters = load_json(ENCOUNTER_FILE, [])
    encounters = [e for e in encounters if e.get('id')!= eid]
    save_json(ENCOUNTER_FILE, encounters)
    return jsonify({"ok": True})

# REGISTER - 5 FIELDS WITH PHONE - CLEAN, PRESERVING ALL ACHIEVEMENTS

@app.route('/api/member/register', methods=['POST'])
def api_member_register():
    try:
        fullName = request.form.get('fullName','').strip()
        phone = request.form.get('phone','').strip() or request.form.get('phoneNumber','').strip()
        email = request.form.get('email','').strip()
        ministry = request.form.get('ministry_department','').strip() or request.form.get('ministry','').strip()
        emergencyName = request.form.get('emergency_name','').strip()
        emergencyPhone = request.form.get('emergency_phone','').strip()
        emergencyRel = request.form.get('emergency_relationship','').strip()
        username = request.form.get('username','').strip() or phone
        password = request.form.get('password','').strip()
        photo = request.files.get('photo')

        # Also try parse data json if exists
        data_json = request.form.get('data')
        if data_json:
            try:
                import json
                dj = json.loads(data_json)
                if not fullName and dj.get('personal',{}).get('fullName'):
                    fullName = dj['personal']['fullName']
                if not phone and dj.get('personal',{}).get('phone'):
                    phone = dj['personal']['phone']
                if not ministry and dj.get('ministry',{}).get('department'):
                    ministry = dj['ministry']['department']
                if not emergencyName and dj.get('emergency',{}).get('name'):
                    emergencyName = dj['emergency']['name']
                if not emergencyPhone and dj.get('emergency',{}).get('phone'):
                    emergencyPhone = dj['emergency']['phone']
            except:
                pass

        if not fullName or not phone or not ministry or not emergencyName or not emergencyPhone or not password:
            return jsonify({"ok":False, "error":"All * fields required - Full Name, Phone, Ministry, Emergency Name/Phone, Password"}), 400
        if not photo or photo.filename=='':
            return jsonify({"ok":False, "error":"Photo required"}), 400

        members = load_json(MEMBERS_FILE, [])
        # Check duplicate phone or username
        for m in members:
            if (m.get('personal',{}).get('phone')==phone) or (m.get('phone')==phone) or (m.get('username')==username):
                return jsonify({"ok":False, "error":"Phone or Username already registered - try login"}), 400

        import os, uuid
        from werkzeug.utils import secure_filename
        os.makedirs('static/uploads', exist_ok=True)
        ext = secure_filename(photo.filename).split('.')[-1].lower() if '.' in photo.filename else 'jpg'
        if ext not in ['jpg','jpeg','png','webp','JPG','JPEG','PNG','jpg']:
            ext = 'jpg'
        filename = f"member_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join('static/uploads', filename)
        photo.save(filepath)

        # Compress if still large (phone fix)
        try:
            size = os.path.getsize(filepath)
            if size > 500*1024:
                from PIL import Image
                im = Image.open(filepath)
                if im.mode in ('RGBA','P','LA'):
                    im = im.convert('RGB')
                im.thumbnail((800, 800))
                im.save(filepath, optimize=True, quality=70)
        except Exception as comp_e:
            print(f"Compression warning: {comp_e}")

        new_id = max([m.get('id',0) for m in members], default=0) + 1
        new_member = {
            "id": new_id,
            "username": username,
            "fullName": fullName,
            "personal": {"fullName": fullName, "phone": phone, "email": email},
            "contact": {"phone": phone, "email": email},
            "ministry": {"department": ministry, "preferredMinistry": ministry},
            "emergency": {"name": emergencyName, "relationship": emergencyRel, "phone": emergencyPhone},
            "phone": phone,
            "email": email,
            "photo": f"/static/uploads/{filename}",
            "password": password,
            "status": "pending",
            "approved": False,
            "date": datetime.now().strftime("%Y-%m-%d")
        }
        members.append(new_member)
        save_json(MEMBERS_FILE, members)
        return jsonify({"ok":True, "id": new_id, "message":"Registered, awaiting approval"})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok":False, "error": f"Server error: {str(e)[:150]} - try smaller photo"}), 500


@app.route('/api/member/login', methods=['POST'])
@armor_limit("10 per minute")
def api_member_login():
    if not check_rate(request.remote_addr, 'member_login', 5, 60): return jsonify({"ok":False,"error":"Too many attempts"}),429
    data = request.get_json(); login_val = sanitize_text(data.get('login','').strip(),100); pwd = data.get('password','')
    members = load_json(MEMBERS_FILE, []); user = next((m for m in members if m.get('email','').lower()==login_val.lower() or m.get('username','').lower()==login_val.lower()), None)
    if not user or not check_password_hash(user['account']['password'], pwd): return jsonify({"ok":False,"error":"Wrong credentials"}),401
    if user['status']=="pending": return jsonify({"ok":False,"error":"Your membership is under review by admin.","status":"pending"}),403
    if user['status']=="rejected": return jsonify({"ok":False,"error":"Membership rejected. Contact church office.","status":"rejected"}),403
    session['member_logged_in']=True; session['member_id']=user['id']; session['member_data']={"id":user['id'],"username":user['username'],"email":user['email'],"personal":user.get('personal',{}),"contact":user.get('contact',{}),"ministry":user.get('ministry',{}),"emergency":user.get('emergency',{}),"fullName":user.get('fullName',''),"phone":user.get('phone','') or user.get('personal',{}).get('phone',''),"photo":user.get('photo',''),"status":user['status']}
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
        if allowed_file(file.filename, {'mp4','mov','webm','avi','mkv'}): filename = upload_to_cloudinary(file, folder="south_b_chapel/videos")
    vids = load_json('data/videos.json', []); vids.append({"id": int(time.time()*1000),"title": title,"yt": yt,"yt_raw": sanitize_text(yt_raw,100),"local_file": filename,"category": category,"description": description,"date": datetime.now(TZ).strftime('%Y-%m-%d')}); save_json('data/videos.json', vids); clear_image_cache(); return jsonify({"ok": True})
@app.route('/api/admin/upload-gallery', methods=['POST'])
@admin_required
def admin_upload_gallery():
    title = sanitize_text(request.form.get('title'),200); category = sanitize_text(request.form.get('category','Events'),50); cover = request.form.get('cover','').strip(); visibility = request.form.get('visibility','public');
    if visibility not in ['public','members']: visibility='public'
    files = request.files.getlist('files'); urls_raw = request.form.get('images',''); saved=[]
    for f in files:
        if f and f.filename!= '' and allowed_file(f.filename, {'jpg','jpeg','png','webp','gif'}):
            url = upload_to_cloudinary(f, folder="south_b_chapel/gallery"); saved.append(url)
    if urls_raw:
        for u in urls_raw.split(','):
            if u.strip(): saved.append(sanitize_text(u.strip(),500))
    if cover and cover not in saved: saved.insert(0, sanitize_text(cover,500))
    final_cover = cover if cover else (saved[0] if saved else "uploads/logoon.jpeg")
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
        if allowed_file(file.filename, {'pdf','docx','txt','pptx'}): saved = upload_to_cloudinary(file, folder="south_b_chapel/notes")
    notes = load_json('data/sunday_school_notes.json', []); notes.append({"id": int(time.time()*1000),"title": title,"content": content,"file": saved,"size": f"{random.randint(500, 2000)} KB","date": datetime.now(TZ).strftime('%Y-%m-%d')}); save_json('data/sunday_school_notes.json', notes); return jsonify({"ok": True})
@app.route('/api/admin/sunday-upload-video', methods=['POST'])
@admin_required
def admin_upload_sunday_video():
    title = sanitize_text(request.form.get('title'),200); yt_raw = request.form.get('yt',''); yt = extract_yt_id(yt_raw); file = request.files.get('file'); saved=""
    if file and file.filename!= "":
        if allowed_file(file.filename, {'mp4','mov','webm'}): saved = upload_to_cloudinary(file, folder="south_b_chapel/sunday_videos")
    vids = load_json('data/sunday_school_videos.json', []); vids.append({"id": int(time.time()*1000),"title": title,"yt": yt,"local_file": saved,"date": datetime.now(TZ).strftime('%Y-%m-%d')}); save_json('data/sunday_school_videos.json', vids); return jsonify({"ok": True})
@app.route('/api/admin/upload-sermon', methods=['POST'])
@admin_required
def admin_upload_sermon():
    title = sanitize_text(request.form.get('title'),200); speaker = sanitize_text(request.form.get('speaker'),100); stype = request.form.get('type','video'); series = sanitize_text(request.form.get('series',''),100); desc = sanitize_text(request.form.get('description',''),2000); yt_raw = request.form.get('yt',''); yt = extract_yt_id(yt_raw); file = request.files.get('file'); saved=""
    if file and file.filename!= "": saved = upload_to_cloudinary(file, folder="south_b_chapel/sermons")
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
            if file and file.filename!= "": s['local_file'] = upload_to_cloudinary(file, folder="south_b_chapel/sermons")
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
            if file and file.filename!= "": v['local_file'] = upload_to_cloudinary(file, folder="south_b_chapel/videos")
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
            if file and file.filename!= "": n['file'] = upload_to_cloudinary(file, folder="south_b_chapel/notes")
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
        if allowed_file(file.filename, {'jpg','jpeg','png','webp'}): saved = upload_to_cloudinary(file, folder="south_b_chapel/events")
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
            if file and file.filename!= "": ev['image'] = upload_to_cloudinary(file, folder="south_b_chapel/events")
            break
    save_json('data/events.json', events); return jsonify({"ok": True})
@app.route('/api/events/register', methods=['POST'])
@armor_limit("10 per minute")
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
    if request.method == 'POST': data = request.get_json() or {}; pwd = data.get('pwd','')
    else: pwd = request.args.get('pwd','')
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
@armor_limit("5 per minute")
def contact_send():
    if not check_rate(request.remote_addr, 'contact', 5, 120): return jsonify({"ok": False, "error": "Too fast"}), 429
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
    if request.method == 'POST': data = request.get_json() or {}; pwd = data.get('pwd','')
    else: pwd = request.args.get('pwd','')
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
    data = request.get_json() or {}; pwd = data.get('pwd','') or request.args.get('pwd','')
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
            if file and file.filename!= "": v['local_file'] = upload_to_cloudinary(file, folder="south_b_chapel/sunday_videos")
            break
    save_json('data/sunday_school_videos.json', vids); return jsonify({"ok": True})
@app.route('/api/member/qr-info')
def api_member_qr_info():
    if not session.get('member_logged_in'): return jsonify({"ok": False, "error": "Not logged in"}), 401
    mid = session.get('member_id')
    members = load_json(MEMBERS_FILE, [])
    m = next((x for x in members if x['id']==mid), None)
    if not m: return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "id": m['id'], "username": m['username'], "name": m.get('personal',{}).get('fullName',''), "status": m['status'], "photo": m.get('photo','')})
@app.route('/api/member/my-qr')
def api_member_my_qr():
    if not session.get('member_logged_in'): return jsonify({"ok": False, "error": "Not logged in"}), 401
    mid = session.get('member_id')
    members = load_json(MEMBERS_FILE, [])
    m = next((x for x in members if x['id']==mid), None)
    if not m or m['status']!='approved': return jsonify({"ok": False, "error": "Not approved"}), 403
    expiry = int(time.time()) + 300
    payload = f"{mid}:{expiry}"
    sig = hmac.new(QR_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    token = f"{payload}:{sig}"
    b64 = base64.urlsafe_b64encode(token.encode()).decode().rstrip('=')
    return jsonify({"ok": True, "id": mid, "token": b64, "expires_in": 300, "expiry": expiry})
@app.route('/api/admin/checkin', methods=['POST'])
@admin_required
def api_admin_checkin_secure():
    if not check_rate(request.remote_addr, 'checkin', 30, 60): return jsonify({"ok": False, "error": "Too fast"}), 429
    data = request.get_json() or {}
    raw = data.get('member_id') or data.get('token') or data.get('qr') or data.get('id') or ""
    raw = str(raw).strip(); mid = 0
    try:
        s = raw; pad = '=' * (-len(s) % 4)
        try:
            decoded = base64.urlsafe_b64decode(s+pad).decode()
            parts = decoded.split(':')
            if len(parts)==3:
                mid_p = int(parts[0]); exp = int(parts[1]); sig = parts[2]
                payload = f"{mid_p}:{exp}"
                expected = hmac.new(QR_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
                if not hmac.compare_digest(expected, sig): return jsonify({"ok": False, "error": "Invalid signature"}), 403
                if time.time() > exp: return jsonify({"ok": False, "error": "QR expired - ask member to refresh"}), 403
                mid = mid_p
            else: mid = int(raw)
        except: mid = int(raw)
    except: return jsonify({"ok": False, "error": "Invalid QR"}), 400
    if not mid: return jsonify({"ok": False, "error": "member_id required"}), 400
    members = load_json(MEMBERS_FILE, [])
    member = next((x for x in members if x['id']==mid), None)
    if not member: return jsonify({"ok": False, "error": "Member not found"}), 404
    if member['status']!='approved': return jsonify({"ok": False, "error": "Not approved"}), 403
    checkins = load_json(CHECKIN_FILE, [])
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    already = next((c for c in checkins if c['member_id']==mid and c['date']==today), None)
    if already: return jsonify({"ok": False, "error": f"Already checked-in today at {already['time']}", "member": member})
    new_check = {"id": int(time.time()*1000), "member_id": mid, "username": member['username'], "name": sanitize_text(member.get('personal',{}).get('fullName', member['username']),100), "photo": member.get('photo',''), "date": today, "time": datetime.now(TZ).strftime("%H:%M:%S"), "datetime": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")}
    checkins.insert(0, new_check); save_json(CHECKIN_FILE, checkins)
    return jsonify({"ok": True, "checkin": new_check, "member": member})
@app.route('/api/admin/checkins')
@admin_required
def api_admin_checkins():
    date = sanitize_text(request.args.get('date') or datetime.now(TZ).strftime("%Y-%m-%d"),20)
    checkins = load_json(CHECKIN_FILE, []); filtered = [c for c in checkins if c['date']==date]
    return jsonify(filtered)
@app.route('/api/admin/checkins/count')
@admin_required
def api_checkins_count():
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    checkins = load_json(CHECKIN_FILE, []); today_c = [c for c in checkins if c['date']==today]
    return jsonify({"count": len(today_c), "date": today})
@app.route('/api/seek-counsel', methods=['POST'])
def seek_counsel():
    feeling = sanitize_text(request.json.get('feeling','').lower(),100)
    bible = {'anxious': [{"ref":"Philippians 4:6-7", "text":"Do not be anxious...","counsel":"God will guard your heart."}],'fear': [{"ref":"Isaiah 41:10", "text":"Fear not...","counsel":"God is with you."}],}
    verses=None
    for k in bible:
        if k in feeling: verses=bible[k]; break
    if not verses: verses=[{"ref":"Jeremiah 29:11","text":"For I know the plans...","counsel":"God has a good plan."},{"ref":"Psalm 23:1","text":"The Lord is my shepherd."}]
    return jsonify({"verses": verses})

@app.route('/sitemap.xml')
def sitemap():
    try:
        static_path = os.path.join(app.root_path, 'static')
        if os.path.exists(os.path.join(static_path, 'sitemap.xml')): return send_from_directory(static_path, 'sitemap.xml')
        if os.path.exists(os.path.join(app.root_path, 'sitemap.xml')): return send_from_directory(app.root_path, 'sitemap.xml')
        sm = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://schemas.xmlsoap.org/schemas/sitemap/0.9"><url><loc>https://south-b-police-chapel.onrender.com/</loc></url></urlset>'
        return Response(sm, mimetype='application/xml')
    except Exception as e: return str(e), 500
@app.route('/robots.txt')
def robots():
    try:
        static_path = os.path.join(app.root_path, 'static')
        if os.path.exists(os.path.join(static_path, 'robots.txt')): return send_from_directory(static_path, 'robots.txt')
        robots_content = "User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: https://south-b-police-chapel.onrender.com/sitemap.xml\n"
        return Response(robots_content, mimetype='text/plain')
    except Exception as e: return str(e), 500

@app.route('/google-site-verification.html')
def google_verif_file():
    return Response(f"google-site-verification: google{GOOGLE_VERIFICATION}.html", mimetype='text/plain')



# ============== COMMUNITY PORTAL - FACEBOOK-LIKE - PRIVATE MEMBERS ONLY ==============
COMMUNITY_POSTS_FILE = os.path.join(DATA_DIR, 'community_posts.json')
GROUPS_FILE = os.path.join(DATA_DIR, 'groups.json')
NOTIFICATIONS_FILE = os.path.join(DATA_DIR, 'notifications.json')
COMMUNITY_PRAYERS_FILE = os.path.join(DATA_DIR, 'community_prayers.json')
EVENT_RSVP_FILE = os.path.join(DATA_DIR, 'event_rsvps.json')

def member_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('member_logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Login required"}), 401
            return redirect(url_for('members_login_page'))
        members = load_json(MEMBERS_FILE, [])
        m = next((x for x in members if x['id']==session.get('member_id')), None)
        if not m or m['status']!='approved':
            return render_template('member_pending.html', member=m) if not request.path.startswith('/api/') else jsonify({"error":"Not approved"}), 403
        return f(*args, **kwargs)
    return decorated

def time_ago(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        now = datetime.now(TZ).replace(tzinfo=None)
        diff = now - dt
        if diff.days>0: return f"{diff.days}d ago"
        hours = diff.seconds//3600
        if hours>0: return f"{hours}h ago"
        mins = diff.seconds//60
        if mins>0: return f"{mins}m ago"
        return "Just now"
    except:
        return date_str

# COMMUNITY POSTS
@app.route('/api/community/posts')
@member_required
def api_community_posts():
    mine = request.args.get('mine')
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    members = load_json(MEMBERS_FILE, [])
    # filter by visibility
    current_id = session.get('member_id')
    current_m = next((x for x in members if x['id']==current_id), None)
    my_ministry = current_m.get('ministry',{}).get('department','') if current_m else ''
    my_groups = []
    groups = load_json(GROUPS_FILE, [])
    for g in groups:
        if current_id in g.get('members',[]):
            my_groups.append(g['id'])
    filtered=[]
    for p in posts:
        if mine=='1' and p['member_id']!=current_id:
            continue
        vis = p.get('visibility','church')
        if vis=='church':
            filtered.append(p)
        elif vis=='ministry' and p.get('ministry','')==my_ministry:
            filtered.append(p)
        elif vis=='group' and p.get('group_id') in my_groups:
            filtered.append(p)
        elif p['member_id']==current_id:
            filtered.append(p)
        elif vis not in ['ministry','group']:
            filtered.append(p)
    # enrich
    for p in filtered:
        p['timeAgo']=time_ago(p.get('date',''))
    filtered.sort(key=lambda x: x['id'], reverse=True)
    return jsonify(filtered[:100])

@app.route('/api/community/post', methods=['POST'])
@member_required
def api_community_create_post():
    data = request.get_json()
    content = sanitize_text(data.get('content',''), 2000)
    if not content: return jsonify({"ok":False,"error":"Content required"}),400
    visibility = data.get('visibility','church')
    if visibility not in ['church','ministry','group']: visibility='church'
    ptype = data.get('type','post')
    if ptype not in ['post','prayer','testimony','announcement']: ptype='post'
    members = load_json(MEMBERS_FILE, [])
    current_id = session.get('member_id')
    m = next((x for x in members if x['id']==current_id), None)
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    new_post = {
        "id": int(time.time()*1000),
        "member_id": current_id,
        "username": m['username'],
        "fullName": m.get('fullName') or m.get('personal',{}).get('fullName',''),
        "photo": m.get('photo',''),
        "ministry": m.get('ministry',{}).get('department','') or m.get('personal',{}).get('ministry','Member'),
        "content": content,
        "type": ptype,
        "visibility": visibility,
        "group_id": data.get('group_id'),
        "reactions": {"amen":0,"praying":0,"bless":0},
        "reacted_by": {"amen":[],"praying":[],"bless":[]},
        "comments": [],
        "date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    }
    posts.insert(0, new_post)
    save_json(COMMUNITY_POSTS_FILE, posts)
    # notification
    notifs = load_json(NOTIFICATIONS_FILE, [])
    # notify all members except self (simplified)
    for mem in members:
        if mem['id']!=current_id and mem['status']=='approved':
            notifs.insert(0, {
                "id": int(time.time()*1000)+mem['id'],
                "member_id": mem['id'],
                "text": f"{new_post['fullName']} shared a {ptype}: {content[:60]}...",
                "icon": "fa-heart" if ptype=='testimony' else "fa-pray" if ptype=='prayer' else "fa-comment",
                "date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
                "read": False
            })
    save_json(NOTIFICATIONS_FILE, notifs[:200])
    return jsonify({"ok":True,"post":new_post})

@app.route('/api/community/react/<int:post_id>', methods=['POST'])
@member_required
def api_community_react(post_id):
    data = request.get_json()
    rtype = data.get('type','amen')
    if rtype not in ['amen','praying','bless']: rtype='amen'
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    current_id = session.get('member_id')
    for p in posts:
        if p['id']==post_id:
            if 'reacted_by' not in p: p['reacted_by']={"amen":[],"praying":[],"bless":[]}
            if 'reactions' not in p: p['reactions']={"amen":0,"praying":0,"bless":0}
            # toggle
            if current_id in p['reacted_by'].get(rtype,[]):
                p['reacted_by'][rtype].remove(current_id)
                p['reactions'][rtype]=max(0,p['reactions'][rtype]-1)
            else:
                # remove from other reactions if exists? keep simple allow one type only
                for k in ['amen','praying','bless']:
                    if current_id in p['reacted_by'].get(k,[]):
                        p['reacted_by'][k].remove(current_id)
                        p['reactions'][k]=max(0,p['reactions'][k]-1)
                p['reacted_by'][rtype].append(current_id)
                p['reactions'][rtype]+=1
            break
    save_json(COMMUNITY_POSTS_FILE, posts)
    return jsonify({"ok":True})

@app.route('/api/community/comment/<int:post_id>', methods=['POST'])
@member_required
def api_community_comment(post_id):
    data = request.get_json()
    content = sanitize_text(data.get('content',''), 500)
    if not content: return jsonify({"ok":False}),400
    members = load_json(MEMBERS_FILE, [])
    current_id = session.get('member_id')
    m = next((x for x in members if x['id']==current_id), None)
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    for p in posts:
        if p['id']==post_id:
            if 'comments' not in p: p['comments']=[]
            p['comments'].append({
                "id": int(time.time()*1000),
                "member_id": current_id,
                "username": m['username'],
                "fullName": m.get('fullName',''),
                "photo": m.get('photo',''),
                "content": content,
                "date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
            })
            break
    save_json(COMMUNITY_POSTS_FILE, posts)
    return jsonify({"ok":True})

# DIRECTORY
@app.route('/api/community/members')
@member_required
def api_community_directory():
    q = request.args.get('q','').lower().strip()
    members = load_json(MEMBERS_FILE, [])
    current_id = session.get('member_id')
    current_m = next((x for x in members if x['id']==current_id), None)
    my_ministry = current_m.get('ministry',{}).get('department','') if current_m else ''
    groups = load_json(GROUPS_FILE, [])
    result=[]
    for m in members:
        if m['status']!='approved': continue
        full = f"{m.get('fullName','')} {m.get('username','')} {m.get('ministry',{}).get('department','')}".lower()
        if q and q not in full: continue
        # privacy
        privacy = m.get('privacy',{"phone":"none","email":"none"})
        phone_vis = privacy.get('phone','none')
        email_vis = privacy.get('email','none')
        show_phone=False
        show_email=False
        if phone_vis=='church': show_phone=True
        elif phone_vis=='ministry' and m.get('ministry',{}).get('department','')==my_ministry: show_phone=True
        if email_vis=='church': show_email=True
        elif email_vis=='ministry' and m.get('ministry',{}).get('department','')==my_ministry: show_email=True
        # groups
        my_groups_names=[]
        for g in groups:
            if m['id'] in g.get('members',[]):
                my_groups_names.append(g['name'])
        result.append({
            "id": m['id'],
            "fullName": m.get('fullName',''),
            "username": m['username'],
            "photo": m.get('photo',''),
            "ministry": m.get('ministry',{}).get('department','') or m.get('personal',{}).get('ministry','Member'),
            "phone": m.get('phone','') or m.get('personal',{}).get('phone',''),
            "email": m.get('email',''),
            "phoneVisible": show_phone,
            "emailVisible": show_email,
            "groups": my_groups_names,
            "roles": m.get('roles',['member'])
        })
    return jsonify(result[:100])

# GROUPS
@app.route('/api/community/groups')
@member_required
def api_community_groups():
    groups = load_json(GROUPS_FILE, [])
    return jsonify(groups)

@app.route('/api/community/groups/<int:gid>/join', methods=['POST'])
@member_required
def api_community_join_group(gid):
    groups = load_json(GROUPS_FILE, [])
    current_id = session.get('member_id')
    for g in groups:
        if g['id']==gid:
            if current_id not in g['members']:
                g['members'].append(current_id)
            else:
                # leave
                g['members']=[x for x in g['members'] if x!=current_id]
            break
    save_json(GROUPS_FILE, groups)
    return jsonify({"ok":True})

# PRAYER WALL COMMUNITY
@app.route('/api/community/prayers')
@member_required
def api_community_prayers():
    # combine old prayers + community posts type prayer
    prayers = load_json('data/prayers.json', [])
    community_posts = load_json(COMMUNITY_POSTS_FILE, [])
    # transform community prayer posts to prayer format
    cp=[]
    for p in community_posts:
        if p.get('type')=='prayer':
            cp.append({
                "id": p['id'],
                "fullName": p['fullName'],
                "photo": p['photo'],
                "content": p['content'],
                "date": p['date'].split(' ')[0],
                "prayingCount": p.get('reactions',{}).get('praying',0),
                "prayingBy": [],
                "status": "new",
                "source": "community"
            })
    # add private prayers if user is prayer team? for now show public only
    public_prayers=[]
    for pr in prayers:
        if pr.get('visibility','public')=='public':
            public_prayers.append({
                "id": pr['id'],
                "fullName": pr.get('name','Anonymous'),
                "photo": "",
                "content": pr.get('content',''),
                "date": pr.get('date',''),
                "prayingCount": pr.get('pray_count',0),
                "prayingBy": [],
                "status": "new",
                "source": "old"
            })
    all_p = cp + public_prayers
    all_p.sort(key=lambda x: x['id'], reverse=True)
    return jsonify(all_p[:100])

@app.route('/api/community/prayer/pray/<int:pid>', methods=['POST'])
@member_required
def api_community_pray_prayer(pid):
    # try community posts first
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    found=False
    for p in posts:
        if p['id']==pid and p.get('type')=='prayer':
            if 'reactions' not in p: p['reactions']={"amen":0,"praying":0,"bless":0}
            if 'reacted_by' not in p: p['reacted_by']={"amen":[],"praying":[],"bless":[]}
            current_id=session.get('member_id')
            if current_id not in p['reacted_by']['praying']:
                p['reacted_by']['praying'].append(current_id)
                p['reactions']['praying']+=1
                found=True
            break
    if found:
        save_json(COMMUNITY_POSTS_FILE, posts)
        return jsonify({"ok":True})
    # else old prayer wall
    prayers = load_json('data/prayers.json', [])
    for pr in prayers:
        if pr['id']==pid:
            pr['pray_count']=pr.get('pray_count',0)+1
            break
    save_json('data/prayers.json', prayers)
    return jsonify({"ok":True})

@app.route('/api/community/prayer/answer/<int:pid>', methods=['POST'])
@member_required
def api_community_answer_prayer(pid):
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    for p in posts:
        if p['id']==pid:
            p['status']='answered'
            break
    save_json(COMMUNITY_POSTS_FILE, posts)
    return jsonify({"ok":True})

# PROFILE & PRIVACY
@app.route('/api/community/profile', methods=['POST'])
@member_required
def api_community_update_profile():
    data = request.get_json()
    bio = sanitize_text(data.get('bio',''), 500)
    members = load_json(MEMBERS_FILE, [])
    current_id = session.get('member_id')
    for m in members:
        if m['id']==current_id:
            if 'profile' not in m: m['profile']={}
            m['profile']['bio']=bio
            # update session
            if 'member_data' in session:
                if 'profile' not in session['member_data']:
                    session['member_data']['profile']={}
                session['member_data']['profile']['bio']=bio
            break
    save_json(MEMBERS_FILE, members)
    return jsonify({"ok":True})

@app.route('/api/community/privacy', methods=['POST'])
@member_required
def api_community_update_privacy():
    data = request.get_json()
    phone_vis = data.get('phone','none')
    email_vis = data.get('email','none')
    if phone_vis not in ['none','ministry','church']: phone_vis='none'
    if email_vis not in ['none','ministry','church']: email_vis='none'
    members = load_json(MEMBERS_FILE, [])
    current_id = session.get('member_id')
    for m in members:
        if m['id']==current_id:
            m['privacy']={"phone":phone_vis,"email":email_vis}
            break
    save_json(MEMBERS_FILE, members)
    return jsonify({"ok":True})

# NOTIFICATIONS
@app.route('/api/community/notifications')
@member_required
def api_community_notifications():
    notifs = load_json(NOTIFICATIONS_FILE, [])
    current_id = session.get('member_id')
    my_notifs=[n for n in notifs if n.get('member_id')==current_id]
    my_notifs.sort(key=lambda x: x['id'], reverse=True)
    for n in my_notifs[:20]:
        n['timeAgo']=time_ago(n.get('date',''))
    return jsonify(my_notifs[:20])

# EVENT RSVP
@app.route('/api/events/rsvp/<int:eid>', methods=['POST'])
@member_required
def api_event_rsvp(eid):
    data = request.get_json()
    status = data.get('status','interested')
    if status not in ['interested','attending']: status='interested'
    rsvps = load_json(EVENT_RSVP_FILE, [])
    current_id = session.get('member_id')
    # remove existing
    rsvps=[r for r in rsvps if not (r['event_id']==eid and r['member_id']==current_id)]
    rsvps.append({
        "id": int(time.time()*1000),
        "event_id": eid,
        "member_id": current_id,
        "status": status,
        "date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    })
    save_json(EVENT_RSVP_FILE, rsvps)
    # notification
    notifs = load_json(NOTIFICATIONS_FILE, [])
    notifs.insert(0, {
        "id": int(time.time()*1000),
        "member_id": current_id,
        "text": f"You marked {status} for event ID {eid}",
        "icon": "fa-calendar",
        "date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    })
    save_json(NOTIFICATIONS_FILE, notifs[:200])
    return jsonify({"ok":True})

# ADMIN - COMMUNITY MODERATION
@app.route('/api/admin/community/posts')
@admin_required
def admin_community_posts():
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    return jsonify(posts)

@app.route('/api/admin/community/delete-post/<int:pid>', methods=['POST'])
@admin_required
def admin_delete_community_post(pid):
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    posts=[p for p in posts if p['id']!=pid]
    save_json(COMMUNITY_POSTS_FILE, posts)
    return jsonify({"ok":True})

@app.route('/api/admin/community/groups', methods=['GET','POST'])
@admin_required
def admin_community_groups_manage():
    if request.method=='GET':
        return jsonify(load_json(GROUPS_FILE, []))
    data=request.get_json()
    groups=load_json(GROUPS_FILE, [])
    groups.append({
        "id": int(time.time()*1000),
        "name": sanitize_text(data.get('name','New Group'),100),
        "slug": sanitize_text(data.get('slug',''),50).lower().replace(' ','-'),
        "icon": data.get('icon','👥'),
        "color": "#0f172a",
        "members": [],
        "leader": None,
        "description": sanitize_text(data.get('description',''),200)
    })
    save_json(GROUPS_FILE, groups)
    return jsonify({"ok":True})

# END COMMUNITY PORTAL



@app.route('/api/admin/members/role/<int:mid>', methods=['POST'])
@admin_required
def admin_update_member_role(mid):
    data = request.get_json()
    new_role = data.get('role','member')
    if new_role not in ['member','ministry_member','group_leader','prayer_team','pastor','moderator','admin']:
        new_role='member'
    members = load_json(MEMBERS_FILE, [])
    for m in members:
        if m['id']==mid:
            m['roles']=[new_role]
            break
    save_json(MEMBERS_FILE, members)
    return jsonify({"ok":True})

@app.route('/api/admin/rsvps')
@admin_required
def admin_get_rsvps():
    rsvps = load_json(EVENT_RSVP_FILE, [])
    members = load_json(MEMBERS_FILE, [])
    events = load_json('data/events.json', [])
    enriched=[]
    for r in rsvps:
        m = next((x for x in members if x['id']==r['member_id']), None)
        e = next((x for x in events if x['id']==r['event_id']), None)
        enriched.append({
            "id": r['id'],
            "event_id": r['event_id'],
            "event_title": e['title'] if e else f"Event {r['event_id']}",
            "member_id": r['member_id'],
            "member_name": m.get('fullName','') if m else 'Unknown',
            "ministry": m.get('ministry',{}).get('department','') if m else '',
            "status": r['status'],
            "date": r['date']
        })
    enriched.sort(key=lambda x: x['id'], reverse=True)
    return jsonify(enriched)

@app.route('/api/admin/groups/<int:gid>/remove-member/<int:mid>', methods=['POST'])
@admin_required
def admin_remove_group_member(gid, mid):
    groups = load_json(GROUPS_FILE, [])
    for g in groups:
        if g['id']==gid:
            g['members']=[x for x in g['members'] if x!=mid]
            break
    save_json(GROUPS_FILE, groups)
    return jsonify({"ok":True})

@app.route('/api/admin/groups/<int:gid>/set-leader/<int:mid>', methods=['POST'])
@admin_required
def admin_set_group_leader(gid, mid):
    groups = load_json(GROUPS_FILE, [])
    for g in groups:
        if g['id']==gid:
            g['leader']=mid
            if mid not in g['members']:
                g['members'].append(mid)
            break
    save_json(GROUPS_FILE, groups)
    return jsonify({"ok":True})

@app.route('/api/admin/community/groups/<int:gid>', methods=['DELETE'])
@admin_required
def admin_delete_group(gid):
    groups = load_json(GROUPS_FILE, [])
    groups=[g for g in groups if g['id']!=gid]
    save_json(GROUPS_FILE, groups)
    return jsonify({"ok":True})



# ============== MEMBER UPLOADS WITH APPROVAL QUEUE ==============
MEMBER_EVENTS_FILE = os.path.join(DATA_DIR, 'member_events.json')
MEMBER_GALLERIES_FILE = os.path.join(DATA_DIR, 'member_galleries.json')
MEMBER_VIDEOS_FILE = os.path.join(DATA_DIR, 'member_videos.json')

# Ensure files exist
for _f in [MEMBER_EVENTS_FILE, MEMBER_GALLERIES_FILE, MEMBER_VIDEOS_FILE]:
    if not os.path.exists(_f):
        save_json(_f, [])

@app.route('/api/community/upload/event', methods=['POST'])
@member_required
def api_member_upload_event():
    title = sanitize_text(request.form.get('title',''),200)
    if not title: return jsonify({"ok":False,"error":"Title required"}),400
    date = sanitize_text(request.form.get('date',''),20)
    time_e = sanitize_text(request.form.get('time',''),20)
    location = sanitize_text(request.form.get('location',''),200)
    desc = sanitize_text(request.form.get('description',''),2000)
    file = request.files.get('file')
    saved=""
    if file and file.filename!="":
        if allowed_file(file.filename, {'jpg','jpeg','png','webp'}):
            saved = upload_to_cloudinary(file, folder="south_b_chapel/member_events")
    events = load_json(MEMBER_EVENTS_FILE, [])
    new_ev = {
        "id": int(time.time()*1000),
        "member_id": session.get('member_id'),
        "title": title,
        "date": date,
        "time": time_e,
        "location": location,
        "description": desc,
        "image": saved,
        "status": "pending",
        "created": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    }
    events.insert(0, new_ev)
    save_json(MEMBER_EVENTS_FILE, events)
    return jsonify({"ok":True, "event": new_ev, "message": "Event submitted for admin approval"})

@app.route('/api/community/upload/photo', methods=['POST'])
@member_required
def api_member_upload_photo():
    title = sanitize_text(request.form.get('title',''),200)
    if not title: return jsonify({"ok":False,"error":"Title required"}),400
    desc = sanitize_text(request.form.get('description',''),500)
    files = request.files.getlist('files')
    single = request.files.get('file')
    saved=[]
    if single and single.filename!="":
        if allowed_file(single.filename, {'jpg','jpeg','png','webp','gif'}):
            saved.append(upload_to_cloudinary(single, folder="south_b_chapel/member_galleries"))
    for f in files:
        if f and f.filename!="" and allowed_file(f.filename, {'jpg','jpeg','png','webp','gif'}):
            saved.append(upload_to_cloudinary(f, folder="south_b_chapel/member_galleries"))
    urls_raw = request.form.get('images','')
    if urls_raw:
        for u in urls_raw.split(','):
            if u.strip(): saved.append(sanitize_text(u.strip(),500))
    galleries = load_json(MEMBER_GALLERIES_FILE, [])
    new_gal = {
        "id": int(time.time()*1000),
        "member_id": session.get('member_id'),
        "title": title,
        "description": desc,
        "images": saved,
        "cover": saved[0] if saved else "",
        "status": "pending",
        "created": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    }
    galleries.insert(0, new_gal)
    save_json(MEMBER_GALLERIES_FILE, galleries)
    return jsonify({"ok":True, "gallery": new_gal, "message": "Photos submitted for approval"})

@app.route('/api/community/upload/video', methods=['POST'])
@member_required
def api_member_upload_video():
    title = sanitize_text(request.form.get('title',''),200)
    if not title: return jsonify({"ok":False,"error":"Title required"}),400
    vtype = request.form.get('type','memory_verse')
    if vtype not in ['memory_verse','testimony','opinion','worship','sermon_clip']: vtype='memory_verse'
    desc = sanitize_text(request.form.get('description',''),1000)
    yt_raw = request.form.get('yt','')
    yt = extract_yt_id(yt_raw)
    file = request.files.get('file')
    saved=""
    if file and file.filename!="":
        if allowed_file(file.filename, {'mp4','mov','webm','avi','mkv'}):
            saved = upload_to_cloudinary(file, folder="south_b_chapel/member_videos")
    videos = load_json(MEMBER_VIDEOS_FILE, [])
    new_vid = {
        "id": int(time.time()*1000),
        "member_id": session.get('member_id'),
        "title": title,
        "type": vtype,
        "description": desc,
        "yt": yt,
        "yt_raw": sanitize_text(yt_raw,100),
        "local_file": saved,
        "status": "pending",
        "created": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    }
    videos.insert(0, new_vid)
    save_json(MEMBER_VIDEOS_FILE, videos)
    return jsonify({"ok":True, "video": new_vid, "message": f"{vtype} video submitted for approval"})

# Member CRUD on own uploads
@app.route('/api/community/post/<int:pid>', methods=['DELETE'])
@member_required
def api_member_delete_post(pid):
    current_id = session.get('member_id')
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    p = next((x for x in posts if x['id']==pid), None)
    if not p: return jsonify({"ok":False,"error":"Not found"}),404
    if p['member_id']!=current_id:
        # check admin
        members = load_json(MEMBERS_FILE, [])
        m = next((x for x in members if x['id']==current_id), None)
        if not m or 'admin' not in (m.get('roles',[]) or []):
            return jsonify({"ok":False,"error":"Not yours"}),403
    posts = [x for x in posts if x['id']!=pid]
    save_json(COMMUNITY_POSTS_FILE, posts)
    return jsonify({"ok":True})

@app.route('/api/community/post/<int:pid>', methods=['PUT'])
@member_required
def api_member_edit_post(pid):
    data = request.get_json()
    content = sanitize_text(data.get('content',''),2000)
    if not content: return jsonify({"ok":False}),400
    current_id = session.get('member_id')
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    for p in posts:
        if p['id']==pid and p['member_id']==current_id:
            p['content']=content
            p['edited']=True
            break
    save_json(COMMUNITY_POSTS_FILE, posts)
    return jsonify({"ok":True})

@app.route('/api/community/event/<int:eid>', methods=['DELETE'])
@member_required
def api_member_delete_event(eid):
    current_id = session.get('member_id')
    events = load_json(MEMBER_EVENTS_FILE, [])
    ev = next((x for x in events if x['id']==eid), None)
    if not ev: return jsonify({"ok":False}),404
    if ev['member_id']!=current_id: return jsonify({"ok":False,"error":"Not yours"}),403
    events = [x for x in events if x['id']!=eid]
    save_json(MEMBER_EVENTS_FILE, events)
    return jsonify({"ok":True})

@app.route('/api/community/gallery/<int:gid>', methods=['DELETE'])
@member_required
def api_member_delete_gallery(gid):
    current_id = session.get('member_id')
    gals = load_json(MEMBER_GALLERIES_FILE, [])
    g = next((x for x in gals if x['id']==gid), None)
    if not g: return jsonify({"ok":False}),404
    if g['member_id']!=current_id: return jsonify({"ok":False}),403
    gals = [x for x in gals if x['id']!=gid]
    save_json(MEMBER_GALLERIES_FILE, gals)
    return jsonify({"ok":True})

@app.route('/api/community/video/<int:vid>', methods=['DELETE'])
@member_required
def api_member_delete_video(vid):
    current_id = session.get('member_id')
    vids = load_json(MEMBER_VIDEOS_FILE, [])
    v = next((x for x in vids if x['id']==vid), None)
    if not v: return jsonify({"ok":False}),404
    if v['member_id']!=current_id: return jsonify({"ok":False}),403
    vids = [x for x in vids if x['id']!=vid]
    save_json(MEMBER_VIDEOS_FILE, vids)
    return jsonify({"ok":True})

# Member views - only approved content
@app.route('/api/community/member-events')
@member_required
def api_community_member_events():
    events = load_json(MEMBER_EVENTS_FILE, [])
    # only approved + own pending
    current_id = session.get('member_id')
    filtered = [e for e in events if e['status']=='approved' or e['member_id']==current_id]
    # enrich with member info
    members = load_json(MEMBERS_FILE, [])
    for e in filtered:
        m = next((x for x in members if x['id']==e['member_id']), None)
        e['member_name'] = m.get('fullName','') if m else 'Member'
        e['member_photo'] = m.get('photo','') if m else ''
        e['timeAgo'] = time_ago(e.get('created',''))
    filtered.sort(key=lambda x: x['id'], reverse=True)
    return jsonify(filtered)

@app.route('/api/community/member-galleries')
@member_required
def api_community_member_galleries():
    gals = load_json(MEMBER_GALLERIES_FILE, [])
    current_id = session.get('member_id')
    filtered = [g for g in gals if g['status']=='approved' or g['member_id']==current_id]
    members = load_json(MEMBERS_FILE, [])
    for g in filtered:
        m = next((x for x in members if x['id']==g['member_id']), None)
        g['member_name'] = m.get('fullName','') if m else 'Member'
        g['member_photo'] = m.get('photo','') if m else ''
    filtered.sort(key=lambda x: x['id'], reverse=True)
    return jsonify(filtered)

@app.route('/api/community/member-videos')
@member_required
def api_community_member_videos():
    vids = load_json(MEMBER_VIDEOS_FILE, [])
    current_id = session.get('member_id')
    filtered = [v for v in vids if v['status']=='approved' or v['member_id']==current_id]
    members = load_json(MEMBERS_FILE, [])
    for v in filtered:
        m = next((x for x in members if x['id']==v['member_id']), None)
        v['member_name'] = m.get('fullName','') if m else 'Member'
        v['member_photo'] = m.get('photo','') if m else ''
    filtered.sort(key=lambda x: x['id'], reverse=True)
    return jsonify(filtered)

# Admin approval queue
@app.route('/api/admin/community/pending')
@admin_required
def admin_community_pending():
    posts = load_json(COMMUNITY_POSTS_FILE, [])
    events = load_json(MEMBER_EVENTS_FILE, [])
    galleries = load_json(MEMBER_GALLERIES_FILE, [])
    videos = load_json(MEMBER_VIDEOS_FILE, [])
    pending = []
    for p in posts:
        if p.get('status','approved')=='pending':
            pending.append({"id":p['id'],"type":"post","subtype":p.get('type','post'),"title":p.get('content','')[:80],"member_id":p['member_id'],"date":p.get('date',''),"data":p})
    for e in events:
        if e.get('status')=='pending':
            pending.append({"id":e['id'],"type":"member_event","subtype":"event","title":e['title'],"member_id":e['member_id'],"date":e.get('created',''),"data":e})
    for g in galleries:
        if g.get('status')=='pending':
            pending.append({"id":g['id'],"type":"member_gallery","subtype":"photo","title":g['title'],"member_id":g['member_id'],"date":g.get('created',''),"data":g})
    for v in videos:
        if v.get('status')=='pending':
            pending.append({"id":v['id'],"type":"member_video","subtype":v.get('type','memory_verse'),"title":v['title'],"member_id":v['member_id'],"date":v.get('created',''),"data":v})
    pending.sort(key=lambda x: x['id'], reverse=True)
    return jsonify(pending)

@app.route('/api/admin/community/approve', methods=['POST'])
@admin_required
def admin_community_approve():
    data = request.get_json()
    pid = data.get('id')
    ptype = data.get('type')
    if ptype=='post':
        posts = load_json(COMMUNITY_POSTS_FILE, [])
        for p in posts:
            if p['id']==pid: p['status']='approved'; break
        save_json(COMMUNITY_POSTS_FILE, posts)
    elif ptype=='member_event':
        events = load_json(MEMBER_EVENTS_FILE, [])
        for e in events:
            if e['id']==pid: e['status']='approved'; break
        save_json(MEMBER_EVENTS_FILE, events)
    elif ptype=='member_gallery':
        gals = load_json(MEMBER_GALLERIES_FILE, [])
        for g in gals:
            if g['id']==pid: g['status']='approved'; break
        save_json(MEMBER_GALLERIES_FILE, gals)
    elif ptype=='member_video':
        vids = load_json(MEMBER_VIDEOS_FILE, [])
        for v in vids:
            if v['id']==pid: v['status']='approved'; break
        save_json(MEMBER_VIDEOS_FILE, vids)
    return jsonify({"ok":True})

@app.route('/api/admin/community/reject', methods=['POST'])
@admin_required
def admin_community_reject():
    data = request.get_json()
    pid = data.get('id')
    ptype = data.get('type')
    reason = sanitize_text(data.get('reason',''),200)
    if ptype=='post':
        posts = load_json(COMMUNITY_POSTS_FILE, [])
        posts = [p for p in posts if p['id']!=pid]
        save_json(COMMUNITY_POSTS_FILE, posts)
    elif ptype=='member_event':
        events = load_json(MEMBER_EVENTS_FILE, [])
        events = [e for e in events if e['id']!=pid]
        save_json(MEMBER_EVENTS_FILE, events)
    elif ptype=='member_gallery':
        gals = load_json(MEMBER_GALLERIES_FILE, [])
        gals = [g for g in gals if g['id']!=pid]
        save_json(MEMBER_GALLERIES_FILE, gals)
    elif ptype=='member_video':
        vids = load_json(MEMBER_VIDEOS_FILE, [])
        vids = [v for v in vids if v['id']!=pid]
        save_json(MEMBER_VIDEOS_FILE, vids)
    return jsonify({"ok":True})

@app.route('/api/admin/community/edit/<ptype>/<int:pid>', methods=['POST'])
@admin_required
def admin_community_edit(ptype, pid):
    data = request.get_json()
    if ptype=='post':
        posts = load_json(COMMUNITY_POSTS_FILE, [])
        for p in posts:
            if p['id']==pid:
                if data.get('content'): p['content']=sanitize_text(data.get('content'),2000)
                break
        save_json(COMMUNITY_POSTS_FILE, posts)
    elif ptype=='member_event':
        events = load_json(MEMBER_EVENTS_FILE, [])
        for e in events:
            if e['id']==pid:
                if data.get('title'): e['title']=sanitize_text(data.get('title'),200)
                if data.get('description'): e['description']=sanitize_text(data.get('description'),2000)
                break
        save_json(MEMBER_EVENTS_FILE, events)
    return jsonify({"ok":True})



# ============== ONLINE PRESENCE + CHAT LIKE FACEBOOK/INSTAGRAM - REAL ONLY ==============
ONLINE_FILE = os.path.join(DATA_DIR, 'online_members.json')
CHATS_FILE = os.path.join(DATA_DIR, 'member_chats.json')

for _f in [ONLINE_FILE, CHATS_FILE]:
    if not os.path.exists(_f):
        save_json(_f, [])

@app.route('/api/community/online', methods=['POST'])
@member_required
def api_update_online():
    mid = session.get('member_id')
    online = load_json(ONLINE_FILE, [])
    now = datetime.now(TZ).isoformat()
    # update or add
    found=False
    for o in online:
        if o['member_id']==mid:
            o['last_seen']=now
            o['is_online']=True
            found=True
            break
    if not found:
        online.append({"member_id":mid,"last_seen":now,"is_online":True})
    # clean old offline (>10 min)
    cutoff = datetime.now(TZ) - timedelta(minutes=10)
    for o in online:
        try:
            last = datetime.fromisoformat(o['last_seen'])
            if last.tzinfo is None:
                last = last.replace(tzinfo=TZ)
            o['is_online'] = last > cutoff
        except:
            o['is_online']=False
    save_json(ONLINE_FILE, online)
    return jsonify({"ok":True})

@app.route('/api/community/online/list')
@member_required
def api_online_list():
    online = load_json(ONLINE_FILE, [])
    members = load_json(MEMBERS_FILE, [])
    cutoff = datetime.now(TZ) - timedelta(minutes=5)
    result=[]
    for o in online:
        if not o.get('is_online'): continue
        try:
            last = datetime.fromisoformat(o['last_seen'])
            if last.tzinfo is None: last = last.replace(tzinfo=TZ)
            if last < cutoff: continue
        except: continue
        m = next((x for x in members if x['id']==o['member_id'] and x['status']=='approved'), None)
        if not m: continue
        if m['id']==session.get('member_id'): continue
        result.append({
            "member_id": m['id'],
            "fullName": m.get('fullName') or m.get('personal',{}).get('fullName') or m.get('username','Real Member'),
            "photo": m.get('photo',''),
            "ministry": m.get('ministry',{}).get('department','Member') or m.get('personal',{}).get('ministry','Member'),
            "is_online": True,
            "last_seen": o['last_seen']
        })
    return jsonify(result)

@app.route('/api/community/chat/send', methods=['POST'])
@member_required
def api_chat_send():
    data = request.get_json()
    to_id = data.get('to_member_id')
    content = sanitize_text(data.get('content',''),2000)
    if not to_id or not content: return jsonify({"ok":False}),400
    members = load_json(MEMBERS_FILE, [])
    if not any(m['id']==to_id and m['status']=='approved' for m in members):
        return jsonify({"ok":False,"error":"Member not found"}),404
    chats = load_json(CHATS_FILE, [])
    chats.append({
        "id": int(time.time()*1000),
        "from_id": session.get('member_id'),
        "to_id": to_id,
        "content": content,
        "date": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "read": False
    })
    save_json(CHATS_FILE, chats)
    return jsonify({"ok":True})

@app.route('/api/community/chat/messages/<int:other_id>')
@member_required
def api_chat_messages(other_id):
    mid = session.get('member_id')
    chats = load_json(CHATS_FILE, [])
    # messages between mid and other_id
    filtered = [c for c in chats if (c['from_id']==mid and c['to_id']==other_id) or (c['from_id']==other_id and c['to_id']==mid)]
    filtered.sort(key=lambda x: x['id'])
    # mark as read
    for c in chats:
        if c['to_id']==mid and c['from_id']==other_id:
            c['read']=True
    save_json(CHATS_FILE, chats)
    # enrich
    members = load_json(MEMBERS_FILE, [])
    for c in filtered:
        m = next((x for x in members if x['id']==c['from_id']), None)
        c['from_name'] = m.get('fullName','') if m else 'Real Member'
        c['from_photo'] = m.get('photo','') if m else ''
    return jsonify(filtered[-50:])  # last 50

@app.route('/api/community/chat/conversations')
@member_required
def api_chat_conversations():
    mid = session.get('member_id')
    chats = load_json(CHATS_FILE, [])
    members = load_json(MEMBERS_FILE, [])
    convs={}
    for c in chats:
        if c['from_id']!=mid and c['to_id']!=mid: continue
        other = c['to_id'] if c['from_id']==mid else c['from_id']
        if other not in convs or c['id']>convs[other]['last_id']:
            convs[other]={'last_id':c['id'],'last_msg':c['content'],'date':c['date'],'unread':0}
    result=[]
    for other_id, info in convs.items():
        m = next((x for x in members if x['id']==other_id), None)
        if not m: continue
        unread = sum(1 for c in chats if c['from_id']==other_id and c['to_id']==mid and not c.get('read'))
        result.append({
            "member_id": other_id,
            "fullName": m.get('fullName') or m.get('personal',{}).get('fullName') or m.get('username','Real Member'),
            "photo": m.get('photo',''),
            "last_msg": info['last_msg'][:40],
            "date": info['date'],
            "unread": unread
        })
    result.sort(key=lambda x: x['date'], reverse=True)
    return jsonify(result)


# ============== FIX FEED AND CHAT PERSISTENCE ==============
# Ensure organized feed shows posts for all members (approved) + author's own posts even if pending

@app.route('/api/community/feed/organized')
def api_feed_organized_fixed():
    try:
        posts = load_json(COMMUNITY_POSTS_FILE, [])
        member_events = load_json(MEMBER_EVENTS_FILE, [])
        galleries = load_json(MEMBER_GALLERIES_FILE, [])
        videos = load_json(MEMBER_VIDEOS_FILE, [])
        members = load_json(MEMBERS_FILE, [])
        church_events = load_json(EVENTS_FILE, []) if 'EVENTS_FILE' in globals() else load_json('data/events.json', [])

        mid = session.get('member_id')

        def get_member_info(m_id):
            m = next((x for x in members if x.get('id')==m_id), None)
            if not m:
                return {"name":"Member","photo":""}
            return {
                "name": m.get('personal',{}).get('fullName') or m.get('fullName') or m.get('username') or 'Member',
                "photo": m.get('photo') or m.get('personal',{}).get('photo') or ''
            }

        feed = []

        # Posts: show approved for all, plus own pending for author
        for p in posts:
            status = p.get('status','approved')
            if status=='approved' or (mid and p.get('member_id')==mid):
                info = get_member_info(p.get('member_id'))
                feed.append({
                    "id": p.get('id'),
                    "type": "post",
                    "subtype": p.get('type','post'),
                    "content": p.get('content',''),
                    "title": p.get('content','')[:60] if p.get('content') else 'Post',
                    "member_id": p.get('member_id'),
                    "member_name": info["name"],
                    "member_photo": info["photo"],
                    "date": p.get('date',''),
                    "likes": len(p.get('reactions',[])),
                    "comments": len(p.get('comments',[])),
                    "data": p,
                    "status": status
                })

        # Member events
        for ev in member_events:
            status = ev.get('status','approved')
            if status=='approved' or (mid and ev.get('member_id')==mid):
                info = get_member_info(ev.get('member_id'))
                feed.append({
                    "id": ev.get('id'),
                    "type": "member_event",
                    "title": ev.get('title','Event'),
                    "member_id": ev.get('member_id'),
                    "member_name": info["name"],
                    "member_photo": info["photo"],
                    "date": ev.get('date',''),
                    "likes": len(ev.get('reactions',[])),
                    "comments": len(ev.get('comments',[])),
                    "data": ev,
                    "status": status
                })

        # Church events (from admin) - always approved
        for ev in church_events:
            feed.append({
                "id": ev.get('id'),
                "type": "church_event",
                "title": ev.get('title','Church Event'),
                "member_id": 0,
                "member_name": "South B Police Chapel",
                "member_photo": "/static/uploads/logoon.jpeg",
                "date": ev.get('date',''),
                "likes": 0,
                "comments": 0,
                "data": ev,
                "status": "approved"
            })

        # Photos
        for g in galleries:
            status = g.get('status','approved')
            if status=='approved' or (mid and g.get('member_id')==mid):
                info = get_member_info(g.get('member_id'))
                feed.append({
                    "id": g.get('id'),
                    "type": "photo",
                    "title": g.get('title','Photos'),
                    "member_id": g.get('member_id'),
                    "member_name": info["name"],
                    "member_photo": info["photo"],
                    "date": g.get('date',''),
                    "likes": len(g.get('reactions',[])),
                    "comments": len(g.get('comments',[])),
                    "data": g,
                    "status": status
                })

        # Videos
        for v in videos:
            status = v.get('status','approved')
            if status=='approved' or (mid and v.get('member_id')==mid):
                info = get_member_info(v.get('member_id'))
                feed.append({
                    "id": v.get('id'),
                    "type": "video",
                    "title": v.get('title','Video'),
                    "member_id": v.get('member_id'),
                    "member_name": info["name"],
                    "member_photo": info["photo"],
                    "date": v.get('date',''),
                    "likes": len(v.get('reactions',[])),
                    "comments": len(v.get('comments',[])),
                    "data": v,
                    "status": status
                })

        # Sort by date desc, approved first
        feed.sort(key=lambda x: (x.get('status')!='approved', x.get('id',0)), reverse=True)
        return jsonify(feed)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify([])

# Fix chat persistence - messages disappear when chat a lot
@app.route('/api/community/chat/messages/<int:other_id>')
def api_chat_messages_fixed(other_id):
    try:
        chats = load_json(CHATS_FILE, [])
        mid = session.get('member_id')
        if not mid:
            return jsonify([])
        # Get all messages between mid and other_id, no limit, sorted asc
        relevant = [c for c in chats if (c.get('from_id')==mid and c.get('to_id')==other_id) or (c.get('from_id')==other_id and c.get('to_id')==mid)]
        relevant.sort(key=lambda x: x.get('id',0))
        # Return last 100 to avoid too large, but sorted, so recent 100
        return jsonify(relevant[-100:])
    except Exception as e:
        return jsonify([])

@app.route('/api/community/chat/send', methods=['POST'])
def api_chat_send_fixed():
    try:
        data = request.get_json()
        mid = session.get('member_id')
        if not mid:
            return jsonify({"ok":False, "error":"Not logged in"}), 401
        to_id = data.get('to_member_id')
        content = data.get('content','').strip()
        if not to_id or not content:
            return jsonify({"ok":False, "error":"Missing"}), 400
        chats = load_json(CHATS_FILE, [])
        new_msg = {
            "id": int(__import__('time').time()*1000),
            "from_id": mid,
            "to_id": to_id,
            "content": content[:500],
            "date": __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        chats.append(new_msg)
        # Keep last 500 messages to prevent file too large, but preserve recent
        if len(chats) > 500:
            chats = chats[-500:]
        save_json(CHATS_FILE, chats)
        return jsonify({"ok":True, "msg": new_msg})
    except Exception as e:
        return jsonify({"ok":False, "error": str(e)}), 500

@app.route('/api/community/chat/conversations')
def api_chat_conversations_fixed():
    try:
        chats = load_json(CHATS_FILE, [])
        members = load_json(MEMBERS_FILE, [])
        mid = session.get('member_id')
        if not mid:
            return jsonify([])
        conv_map = {}
        for c in chats:
            if c.get('from_id')==mid:
                other = c.get('to_id')
            elif c.get('to_id')==mid:
                other = c.get('from_id')
            else:
                continue
            if other not in conv_map or c.get('id',0) > conv_map[other].get('id',0):
                conv_map[other] = c
        
        result = []
        for other_id, last_msg in conv_map.items():
            m = next((x for x in members if x.get('id')==other_id), None)
            if not m:
                continue
            result.append({
                "member_id": other_id,
                "fullName": m.get('personal',{}).get('fullName') or m.get('fullName') or 'Member',
                "photo": m.get('photo') or '',
                "last_msg": last_msg.get('content','')[:40],
                "last_id": last_msg.get('id',0),
                "date": last_msg.get('date','')
            })
        result.sort(key=lambda x: x.get('last_id',0), reverse=True)
        return jsonify(result)
    except Exception as e:
        return jsonify([])


@app.route('/api/bible/verse-of-the-day')
def api_bible_verse_of_day():
    try:
        # Default verses if file missing
        default_verses = [
            {"ref": "John 3:16", "text": "For God so loved the world that he gave his one and only Son, that whoever believes in him shall not perish but have eternal life."},
            {"ref": "Jeremiah 29:11", "text": "For I know the plans I have for you, declares the Lord, plans to prosper you and not to harm you, plans to give you hope and a future."},
            {"ref": "Philippians 4:13", "text": "I can do all this through him who gives me strength."},
            {"ref": "Psalm 23:1", "text": "The Lord is my shepherd, I lack nothing."},
            {"ref": "Isaiah 41:10", "text": "So do not fear, for I am with you; do not be dismayed, for I am your God."},
            {"ref": "Proverbs 3:5-6", "text": "Trust in the Lord with all your heart and lean not on your own understanding; in all your ways submit to him, and he will make your paths straight."},
            {"ref": "Romans 8:28", "text": "And we know that in all things God works for the good of those who love him."},
            {"ref": "Philippians 4:6", "text": "Do not be anxious about anything, but in every situation, by prayer and petition, with thanksgiving, present your requests to God."},
        ]
        verses = load_json(BIBLE_VERSES_FILE, default_verses) if 'BIBLE_VERSES_FILE' in globals() else load_json('data/bible_verses.json', default_verses)
        if not verses or not isinstance(verses, list):
            verses = default_verses
        import datetime
        day = datetime.datetime.now().timetuple().tm_yday
        verse = verses[day % len(verses)]
        # Ensure keys exist
        if 'ref' not in verse and 'verse' in verse:
            verse['ref'] = verse['verse']
        return jsonify(verse)
    except Exception as e:
        print(f"Bible verse error: {e}")
        return jsonify({"ref": "John 3:16", "text": "For God so loved the world that he gave his one and only Son, that whoever believes in him shall not perish but have eternal life."})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
