import csv
import datetime
import os
import uuid
from functools import wraps

from bson import ObjectId
from flask import Blueprint, Flask, flash, redirect, render_template, request, url_for, jsonify
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from pymongo import MongoClient, ASCENDING

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class Config:
    SECRET_KEY = 'measiconnect_secret_dev_key_12345'
    MONGO_URI = 'mongodb+srv://umiraoutlook_db_user:umira123@cluster0.x4b4h0j.mongodb.net/measiconnect?appName=Cluster0'
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    DEFAULT_DEPARTMENT = 'MCA'
    DEFAULT_SEMESTER = 1
    STUDENT_CSV = os.path.join(BASE_DIR, 'student_register_list.csv')

    @classmethod
    def init_app(cls, app):
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(os.path.join(cls.UPLOAD_FOLDER, 'files'), exist_ok=True)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
_client = None
_db = None
_db_initialized = False


def get_db():
    global _client, _db
    if _db is not None:
        return _db
    mongo_uri = Config.MONGO_URI
    if not mongo_uri:
        raise ValueError('MONGO_URI not configured. Set it in your .env file.')
    db_name = 'measiconnect'
    try:
        path_part = mongo_uri.split('/')[-1]
        potential = path_part.split('?')[0]
        if potential:
            db_name = potential
    except Exception:
        pass
    _client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    _db = _client[db_name]
    return _db


def close_db(e=None):
    pass


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data.get('_id'))
        self.role = user_data.get('role')
        self.email = user_data.get('email')
        self.name = user_data.get('name')
        self.roll_no = user_data.get('roll_no')
        self.department = user_data.get('department', Config.DEFAULT_DEPARTMENT)
        self.semester = user_data.get('semester', Config.DEFAULT_SEMESTER)
        self.profile_pic = user_data.get('profile_pic', 'default.png')
        self.created_at = user_data.get('created_at')

    def get_id(self):
        return self.id

    @staticmethod
    def get_by_id(user_id):
        try:
            user_data = get_db().users.find_one({'_id': ObjectId(user_id)})
            return User(user_data) if user_data else None
        except Exception:
            return None

    @staticmethod
    def get_by_email(email):
        if not email:
            return None
        user_data = get_db().users.find_one({'email': email.lower().strip()})
        return User(user_data) if user_data else None

    @staticmethod
    def get_by_roll_no(roll_no):
        if not roll_no:
            return None
        user_data = get_db().users.find_one({'roll_no': roll_no.upper().strip()})
        return User(user_data) if user_data else None

    @staticmethod
    def create_user(role, name, email=None, roll_no=None, department=None, semester=None):
        db = get_db()
        doc = {
            'role': role,
            'name': name,
            'email': email.lower().strip() if email else None,
            'roll_no': roll_no.upper().strip() if roll_no else None,
            'department': department or Config.DEFAULT_DEPARTMENT,
            'semester': int(semester) if semester else Config.DEFAULT_SEMESTER,
            'profile_pic': 'default.png',
            'created_at': datetime.datetime.utcnow(),
        }
        result = db.users.insert_one(doc)
        doc['_id'] = result.inserted_id
        return User(doc)

    @staticmethod
    def get_or_create_staff(email):
        email = email.lower().strip()
        user = User.get_by_email(email)
        if user:
            return user if user.role == 'staff' else None
        name = email.split('@')[0].replace('.', ' ').title()
        return User.create_user(role='staff', name=name, email=email, department=Config.DEFAULT_DEPARTMENT)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'admin':
            flash('Admin access only.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'staff':
            flash('Staff access only.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def student_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'student':
            flash('Student access only.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def staff_name_map(db=None):
    db = db if db is not None else get_db()
    return {str(s['_id']): s['name'] for s in db.users.find({'role': 'staff'}, {'name': 1})}


def get_subjects_for_class(dept, sem):
    db = get_db()
    subjects = db.timetables.distinct('subject', {'department': dept, 'semester': int(sem)})
    return sorted([s for s in subjects if s])


def save_uploaded_file(file):
    original_name = file.filename
    ext = original_name.rsplit('.', 1)[-1] if '.' in original_name else ''
    filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    upload_path = os.path.join(Config.UPLOAD_FOLDER, 'files')
    os.makedirs(upload_path, exist_ok=True)
    file.save(os.path.join(upload_path, filename))
    return filename, original_name


def notify_syllabus_upload(dept, sem, subject, title):
    db = get_db()
    students = list(db.users.find({'role': 'student', 'department': dept, 'semester': int(sem)}))
    staff = list(db.users.find({'role': 'staff'}))
    link = url_for('student.syllabus')
    for user in students + staff:
        create_notification(
            user_id=user['_id'],
            title=f'Syllabus Updated: {subject}',
            content=f'New syllabus for {subject} ({dept} Sem {sem}) — "{title}".',
            link=link if user['role'] == 'student' else url_for('staff.syllabus'),
        )


# Helper to create notification alerts
def create_notification(user_id, title, content, link=None):
    try:
        db = get_db()
        db.notifications.insert_one({
            'user_id': ObjectId(user_id) if isinstance(user_id, (str, ObjectId)) else user_id,
            'title': title,
            'content': content,
            'link': link,
            'read': False,
            'created_at': datetime.datetime.utcnow()
        })
    except Exception as exc:
        print(f"[WARNING] Notification creation failed: {exc}")


# Helper to get timetable grid
def get_timetable_grid(dept, sem):
    db = get_db()
    records = list(db.timetables.find({'department': dept, 'semester': int(sem)}))
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    grid = {d: {h: {'subject': '', 'staff_id': '', 'staff_name': ''} for h in range(1, 6)} for d in days}
    smap = staff_name_map(db)
    for r in records:
        day = r.get('day')
        hour = int(r.get('hour', 0))
        if day in grid and hour in grid[day]:
            sid = str(r.get('staff_id', '')) if r.get('staff_id') else ''
            grid[day][hour] = {
                'subject': r.get('subject', ''),
                'staff_id': sid,
                'staff_name': smap.get(sid, '') if sid else '-'
            }
    return grid


def init_db():
    global _db_initialized
    if _db_initialized:
        return
    db = get_db()

    for field in ('roll_no', 'email'):
        try:
            db.users.drop_index(f'{field}_1')
        except Exception:
            pass
        db.users.create_index(
            field,
            unique=True,
            partialFilterExpression={field: {'$exists': True, '$type': 'string'}},
        )

    try:
        db.attendance.create_index(
            [('student_id', ASCENDING), ('date', ASCENDING), ('hour', ASCENDING), ('subject', ASCENDING)]
        )
    except Exception:
        pass

    try:
        db.timetables.create_index(
            [('department', ASCENDING), ('semester', ASCENDING), ('day', ASCENDING), ('hour', ASCENDING)],
            unique=True
        )
    except Exception:
        pass

    try:
        db.login_logs.create_index([('timestamp', ASCENDING)])
        db.login_logs.create_index([('user_id', ASCENDING)])
    except Exception:
        pass

    if not db.users.find_one({'role': 'admin'}):
        User.create_user(
            role='admin', name='System Admin',
            email='admin@measiit.edu.in', department=Config.DEFAULT_DEPARTMENT, semester=Config.DEFAULT_SEMESTER
        )

    if os.path.isfile(Config.STUDENT_CSV):
        existing = {u['roll_no'] for u in db.users.find({'role': 'student'}, {'roll_no': 1})}
        batch = []
        with open(Config.STUDENT_CSV, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                reg = (row.get('Register Number') or row.get('roll_no') or '').strip().upper()
                name = (row.get('Name') or row.get('name') or '').strip()
                if not reg or not name or reg in existing:
                    continue
                batch.append({
                    'role': 'student', 'name': name, 'email': None, 'roll_no': reg,
                    'department': Config.DEFAULT_DEPARTMENT, 'semester': Config.DEFAULT_SEMESTER,
                    'profile_pic': 'default.png', 'created_at': datetime.datetime.utcnow(),
                })
        if batch:
            db.users.insert_many(batch, ordered=False)

    if db.events.count_documents({}) == 0:
        today = datetime.date.today()
        db.events.insert_many([
            {
                'title': 'Semester End Examinations',
                'description': 'Final semester examinations begin. Check your hall ticket and seating arrangement.',
                'event_date': datetime.datetime.combine(today + datetime.timedelta(days=30), datetime.time.min),
                'event_type': 'exam',
                'location': 'Main Campus',
                'created_at': datetime.datetime.utcnow(),
            },
            {
                'title': 'Industry Expert Guest Lecture',
                'description': 'Guest lecture on Cloud Computing and DevOps by industry professionals.',
                'event_date': datetime.datetime.combine(today + datetime.timedelta(days=7), datetime.time.min),
                'event_type': 'lecture',
                'location': 'Seminar Hall A',
                'created_at': datetime.datetime.utcnow(),
            },
            {
                'title': 'Annual Sports Day',
                'description': 'Inter-department sports competitions. Register with your class representative.',
                'event_date': datetime.datetime.combine(today + datetime.timedelta(days=14), datetime.time.min),
                'event_type': 'event',
                'location': 'College Ground',
                'created_at': datetime.datetime.utcnow(),
            },
        ])

    _db_initialized = True


def log_login_event(user_id, role, identifier, success=True):
    """Persist login attempts to MongoDB for audit tracking."""
    try:
        db = get_db()
        db.login_logs.insert_one({
            'user_id': ObjectId(user_id) if user_id else None,
            'role': role,
            'identifier': identifier,
            'success': success,
            'ip_address': request.remote_addr,
            'timestamp': datetime.datetime.utcnow(),
        })
    except Exception:
        pass


def get_login_stats():
    """Load live portal statistics from MongoDB for the login page."""
    try:
        db = get_db()
        db.command('ping')
        return {
            'student_count': db.users.count_documents({'role': 'student'}),
            'staff_count': db.users.count_documents({'role': 'staff'}),
            'db_connected': True,
        }
    except Exception:
        return {'student_count': 0, 'staff_count': 0, 'db_connected': False}


def render_login_page():
    return render_template('login.html', stats=get_login_stats(), now=datetime.datetime.utcnow())


# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------
auth_bp = Blueprint('auth', __name__)
student_bp = Blueprint('student', __name__)
staff_bp = Blueprint('staff', __name__)
admin_bp = Blueprint('admin', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        role = request.form.get('role', 'student')
        if role == 'student':
            register_no = request.form.get('register_no', '').strip().upper()
            if not register_no:
                flash('Enter your register number.', 'warning')
                return render_login_page()
            user = User.get_by_roll_no(register_no)
            if user and user.role == 'student':
                login_user(user)
                log_login_event(user.id, 'student', register_no, success=True)
                flash(f'Welcome, {user.name}!', 'success')
                return redirect(url_for('index'))
            log_login_event(None, 'student', register_no, success=False)
            flash('Register number not found in database.', 'error')
        elif role == 'staff':
            email = request.form.get('email', '').strip().lower()
            if not email or '@' not in email:
                flash('Enter a valid email.', 'warning')
                return render_login_page()
            user = User.get_or_create_staff(email)
            if user:
                login_user(user)
                log_login_event(user.id, 'staff', email, success=True)
                flash(f'Welcome, {user.name}!', 'success')
                return redirect(url_for('index'))
            log_login_event(None, 'staff', email, success=False)
            flash('Could not sign in.', 'error')
        elif role == 'admin':
            email = request.form.get('email', '').strip().lower()
            user = User.get_by_email(email)
            if user and user.role == 'admin':
                login_user(user)
                log_login_event(user.id, 'admin', email, success=True)
                flash(f'Welcome, {user.name}!', 'success')
                return redirect(url_for('index'))
            log_login_event(None, 'admin', email, success=False)
            flash('Use admin@measiit.edu.in', 'error')
    return render_login_page()


@auth_bp.route('/logout')
def logout():
    logout_user()
    flash('Logged out.', 'success')
    return redirect(url_for('auth.login'))


# ---------------------------------------------------------------------------
# Student BP Routes
# ---------------------------------------------------------------------------
@student_bp.route('/dashboard')
@login_required
@student_required
def dashboard():
    db = get_db()
    sid = ObjectId(current_user.id)
    dept = current_user.department
    sem = int(current_user.semester or 1)

    total_present = db.attendance.count_documents({'student_id': sid, 'status': 'present'})
    total_absent = db.attendance.count_documents({'student_id': sid, 'status': 'absent'})
    total_late = db.attendance.count_documents({'student_id': sid, 'status': 'late'})
    total = total_present + total_absent + total_late
    attendance_pct = round(((total_present + total_late) / total) * 100, 1) if total else 0.0

    # Today's attendance timeline (Hour 1 to 5)
    today_dt = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
    today_records = list(db.attendance.find({'student_id': sid, 'date': today_dt}))
    today_timeline = {h: {'status': 'not-marked', 'subject': '-'} for h in range(1, 6)}
    for tr in today_records:
        h = tr.get('hour', 1)
        if h in today_timeline:
            today_timeline[h] = {
                'status': tr['status'],
                'subject': tr['subject']
            }

    # Announcements
    ann_query = {
        'target_role': {'$in': ['all', 'student']},
        'target_dept': {'$in': ['all', dept]},
        'target_sem': {'$in': [0, sem]}
    }
    announcements = list(db.announcements.find(ann_query).sort('created_at', -1).limit(5))

    # Recent files
    recent_files = list(db.files.find({
        'department': dept,
        'semester': sem,
        'file_type': {'$in': ['study_material', 'assignment']}
    }).sort('uploaded_at', -1).limit(5))

    upcoming_events = list(db.events.find({
        'event_date': {'$gte': datetime.datetime.combine(datetime.date.today(), datetime.time.min)}
    }).sort('event_date', 1).limit(3))

    # Today's slots
    import calendar
    today_day = calendar.day_name[datetime.date.today().weekday()]
    today_schedule = list(db.timetables.find({'department': dept, 'semester': sem, 'day': today_day}))
    schedule_map = {int(s['hour']): s for s in today_schedule}
    today_slots = []
    smap = staff_name_map(db)
    for h in range(1, 6):
        slot = schedule_map.get(h)
        if slot:
            today_slots.append({
                'hour': h,
                'subject': slot['subject'],
                'teacher': smap.get(str(slot.get('staff_id', '')), 'Staff')
            })
        else:
            today_slots.append({
                'hour': h,
                'subject': 'Free Period',
                'teacher': '-'
            })

    return render_template('student/dashboard.html',
                           attendance_pct=attendance_pct, total_present=total_present,
                           total_absent=total_absent, today_timeline=today_timeline,
                           announcements=announcements, recent_files=recent_files,
                           today_slots=today_slots, upcoming_events=upcoming_events)


@student_bp.route('/attendance')
@login_required
@student_required
def attendance():
    db = get_db()
    sid = ObjectId(current_user.id)
    smap = staff_name_map(db)
    records = list(db.attendance.find({'student_id': sid}).sort('date', -1))
    for r in records:
        r['marked_name'] = smap.get(str(r.get('marked_by', '')), 'Staff')
    
    subjects = db.attendance.distinct('subject', {'student_id': sid})
    subject_stats = []
    for sub in subjects:
        p = db.attendance.count_documents({'student_id': sid, 'subject': sub, 'status': 'present'})
        a = db.attendance.count_documents({'student_id': sid, 'subject': sub, 'status': 'absent'})
        l = db.attendance.count_documents({'student_id': sid, 'subject': sub, 'status': 'late'})
        tot = p + a + l
        subject_stats.append({
            'subject': sub, 'present': p, 'absent': a, 'late': l, 'total': tot,
            'percentage': round(((p + l) / tot) * 100, 1) if tot else 0.0,
        })

    # Hourly logs grid grouped by date
    from collections import defaultdict
    daily_grid = defaultdict(lambda: {h: {'status': '-', 'subject': ''} for h in range(1, 6)})
    for r in records:
        d_str = r['date'].strftime('%Y-%m-%d')
        h = r.get('hour', 1)
        daily_grid[d_str][h] = {
            'status': r['status'],
            'subject': r['subject']
        }

    sorted_daily = []
    for d_str in sorted(daily_grid.keys(), reverse=True)[:15]:
        sorted_daily.append({
            'date': d_str,
            'hours': daily_grid[d_str]
        })

    return render_template('student/attendance.html', records=records, subject_stats=subject_stats, sorted_daily=sorted_daily)


@student_bp.route('/timetable')
@login_required
@student_required
def timetable():
    dept = current_user.department
    sem = int(current_user.semester or 1)
    grid = get_timetable_grid(dept, sem)
    return render_template('student/timetable.html', grid=grid, dept=dept, sem=sem)


@student_bp.route('/files')
@login_required
@student_required
def files():
    db = get_db()
    dept = current_user.department
    sem = int(current_user.semester or 1)
    dept_files = list(db.files.find({
        'department': dept,
        'semester': sem,
        'file_type': {'$in': ['study_material', 'assignment']}
    }).sort('uploaded_at', -1))
    return render_template('student/files.html', files=dept_files)


@student_bp.route('/syllabus')
@login_required
@student_required
def syllabus():
    db = get_db()
    dept = current_user.department
    sem = int(current_user.semester or 1)
    syllabus_files = list(db.files.find({
        'department': dept,
        'semester': sem,
        'file_type': 'syllabus',
    }).sort([('subject', ASCENDING), ('uploaded_at', -1)]))
    return render_template('student/syllabus.html', files=syllabus_files, dept=dept, sem=sem)


@student_bp.route('/announcements')
@login_required
@student_required
def announcements():
    db = get_db()
    dept = current_user.department
    sem = int(current_user.semester or 1)
    ann_query = {
        'target_role': {'$in': ['all', 'student']},
        'target_dept': {'$in': ['all', dept]},
        'target_sem': {'$in': [0, sem]}
    }
    announcements_list = list(db.announcements.find(ann_query).sort('created_at', -1))
    return render_template('student/announcements.html', announcements=announcements_list)


@student_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@student_required
def profile():
    db = get_db()
    sid = ObjectId(current_user.id)
    user_doc = db.users.find_one({'_id': sid})

    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        db.users.update_one({'_id': sid}, {'$set': {
            'phone': phone,
            'address': address,
            'updated_at': datetime.datetime.utcnow(),
        }})
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('student.profile'))

    total_present = db.attendance.count_documents({'student_id': sid, 'status': 'present'})
    total_absent = db.attendance.count_documents({'student_id': sid, 'status': 'absent'})
    total_late = db.attendance.count_documents({'student_id': sid, 'status': 'late'})
    total = total_present + total_absent + total_late
    attendance_pct = round(((total_present + total_late) / total) * 100, 1) if total else 0.0

    return render_template('student/profile.html', user=user_doc, attendance_pct=attendance_pct)


@student_bp.route('/leave', methods=['GET', 'POST'])
@login_required
@student_required
def leave():
    db = get_db()
    sid = ObjectId(current_user.id)

    if request.method == 'POST':
        from_date = request.form.get('from_date', '').strip()
        to_date = request.form.get('to_date', '').strip()
        reason = request.form.get('reason', '').strip()
        leave_type = request.form.get('leave_type', 'personal')

        if not from_date or not to_date or not reason:
            flash('Please fill all required fields.', 'warning')
            return redirect(url_for('student.leave'))

        db.leave_requests.insert_one({
            'student_id': sid,
            'student_name': current_user.name,
            'student_roll': current_user.roll_no,
            'department': current_user.department,
            'semester': int(current_user.semester or 1),
            'from_date': datetime.datetime.strptime(from_date, '%Y-%m-%d'),
            'to_date': datetime.datetime.strptime(to_date, '%Y-%m-%d'),
            'reason': reason,
            'leave_type': leave_type,
            'status': 'pending',
            'reviewed_by': None,
            'review_note': '',
            'created_at': datetime.datetime.utcnow(),
        })

        staff_list = list(db.users.find({'role': 'staff'}))
        for s in staff_list:
            create_notification(
                user_id=s['_id'],
                title='New Leave Request',
                content=f'{current_user.name} ({current_user.roll_no}) submitted a leave request.',
                link=url_for('staff.leave_mgmt'),
            )

        flash('Leave application submitted successfully.', 'success')
        return redirect(url_for('student.leave'))

    my_requests = list(db.leave_requests.find({'student_id': sid}).sort('created_at', -1))
    return render_template('student/leave.html', requests=my_requests)


@student_bp.route('/directory')
@login_required
@student_required
def directory():
    db = get_db()
    search = request.args.get('search', '').strip()
    query = {'role': 'staff'}
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'email': {'$regex': search, '$options': 'i'}},
            {'department': {'$regex': search, '$options': 'i'}},
        ]
    faculty = list(db.users.find(query).sort('name', 1))
    return render_template('student/directory.html', faculty=faculty, search=search)


@student_bp.route('/events')
@login_required
@student_required
def events():
    db = get_db()
    upcoming = list(db.events.find({'event_date': {'$gte': datetime.datetime.combine(datetime.date.today(), datetime.time.min)}}).sort('event_date', 1))
    past = list(db.events.find({'event_date': {'$lt': datetime.datetime.combine(datetime.date.today(), datetime.time.min)}}).sort('event_date', -1).limit(10))
    return render_template('student/events.html', upcoming=upcoming, past=past)


# ---------------------------------------------------------------------------
# Staff BP Routes
# ---------------------------------------------------------------------------
@staff_bp.route('/dashboard')
@login_required
@staff_required
def dashboard():
    db = get_db()
    today = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
    
    # Announcements targeting staff
    announcements = list(db.announcements.find({
        'target_role': {'$in': ['all', 'staff']}
    }).sort('created_at', -1).limit(5))

    return render_template('staff/dashboard.html',
                           student_count=db.users.count_documents({'role': 'student'}),
                           marked_today=db.attendance.count_documents(
                               {'date': today, 'marked_by': ObjectId(current_user.id)}),
                           files_count=db.files.count_documents({'uploaded_by': ObjectId(current_user.id)}),
                           announcements=announcements,
                           department=current_user.department,
                           pending_leave_count=db.leave_requests.count_documents({'status': 'pending'}))


@staff_bp.route('/attendance', methods=['GET', 'POST'])
@login_required
@staff_required
def attendance():
    db = get_db()
    subject = request.values.get('subject', 'General').strip() or 'General'
    date_str = request.values.get('date', datetime.date.today().strftime('%Y-%m-%d'))
    dept = request.values.get('department', current_user.department).strip()
    sem_str = request.values.get('semester', '1')
    sem = int(sem_str) if sem_str.isdigit() else 1
    hour_str = request.values.get('hour', '1')
    hour = int(hour_str) if hour_str.isdigit() else 1

    target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    students = list(db.users.find({'role': 'student', 'department': dept, 'semester': sem}).sort('roll_no', 1))

    if request.method == 'POST':
        for s in students:
            status = request.form.get(f"status_{s['_id']}", 'absent')
            prev_record = db.attendance.find_one({
                'student_id': s['_id'], 'date': target_date, 'hour': hour, 'subject': subject
            })

            db.attendance.update_one(
                {'student_id': s['_id'], 'date': target_date, 'hour': hour, 'subject': subject},
                {'$set': {
                    'status': status,
                    'marked_by': ObjectId(current_user.id),
                    'department': dept,
                    'semester': sem
                }},
                upsert=True,
            )

            # Raise alerts if student is absent or late
            if status in ['absent', 'late']:
                if not prev_record or prev_record.get('status') != status:
                    create_notification(
                        user_id=s['_id'],
                        title=f"Attendance Alert: {status.upper()}",
                        content=f"You were marked {status} for Hour {hour} ({subject}) on {date_str}.",
                        link=url_for('student.attendance')
                    )

        flash(f'Attendance saved for Hour {hour} ({subject}) on {date_str}.', 'success')
        return redirect(url_for('staff.attendance', subject=subject, date=date_str, department=dept, semester=sem, hour=hour))

    existing = list(db.attendance.find({
        'date': target_date, 'hour': hour, 'subject': subject,
        'student_id': {'$in': [s['_id'] for s in students]},
    }))
    existing_map = {str(r['student_id']): r['status'] for r in existing}
    for s in students:
        s['marked_status'] = existing_map.get(str(s['_id']))

    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']

    return render_template('staff/attendance.html', students=students, subject_filter=subject,
                           date_filter=date_str, dept_filter=dept, sem_filter=sem, hour_filter=hour,
                           marked_already=len(existing) > 0, departments=departments)


@staff_bp.route('/timetable', methods=['GET', 'POST'])
@login_required
@staff_required
def timetable_view():
    db = get_db()
    uid = ObjectId(current_user.id)
    
    if request.method == 'POST':
        # Staff can assign their own slots
        day = request.form.get('day')
        hour = int(request.form.get('hour', 1))
        dept = request.form.get('department')
        sem = int(request.form.get('semester', 1))
        subject = request.form.get('subject', '').strip()
        
        db.timetables.update_one(
            {'department': dept, 'semester': sem, 'day': day, 'hour': hour},
            {'$set': {
                'subject': subject,
                'staff_id': uid,
                'updated_at': datetime.datetime.utcnow()
            }},
            upsert=True
        )
        flash('Timetable slot updated successfully.', 'success')
        return redirect(url_for('staff.timetable_view'))

    # Load slots taught by this staff member
    slots = list(db.timetables.find({'staff_id': uid}))
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    grid = {d: {h: {'subject': '', 'department': '', 'semester': ''} for h in range(1, 6)} for d in days}
    for s in slots:
        day = s.get('day')
        hour = int(s.get('hour', 0))
        if day in grid and hour in grid[day]:
            grid[day][hour] = {
                'subject': s.get('subject', ''),
                'department': s.get('department', ''),
                'semester': s.get('semester', '')
            }
            
    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']
        
    return render_template('staff/timetable.html', grid=grid, departments=departments)


@staff_bp.route('/syllabus')
@login_required
@staff_required
def syllabus():
    db = get_db()
    dept = request.args.get('department', current_user.department).strip()
    sem_str = request.args.get('semester', str(current_user.semester or 1))
    sem = int(sem_str) if sem_str.isdigit() else 1
    syllabus_files = list(db.files.find({
        'department': dept,
        'semester': sem,
        'file_type': 'syllabus',
    }).sort([('subject', ASCENDING), ('uploaded_at', -1)]))
    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']
    return render_template('staff/syllabus.html', files=syllabus_files,
                           dept=dept, sem=sem, departments=departments)


@staff_bp.route('/files', methods=['GET', 'POST'])
@login_required
@staff_required
def files_mgmt():
    db = get_db()
    staff_id = ObjectId(current_user.id)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        file_type = request.form.get('file_type', 'study_material')
        dept = request.form.get('department', current_user.department)
        sem = int(request.form.get('semester', 1))

        file = request.files.get('file')
        if not file or file.filename == '':
            flash('No file selected.', 'error')
            return redirect(url_for('staff.files_mgmt'))

        original_name = file.filename
        ext = original_name.split('.')[-1] if '.' in original_name else ''
        filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex

        upload_path = os.path.join(Config.UPLOAD_FOLDER, 'files')
        os.makedirs(upload_path, exist_ok=True)
        file.save(os.path.join(upload_path, filename))

        db.files.insert_one({
            'title': title,
            'description': description,
            'file_type': file_type,
            'filename': filename,
            'original_name': original_name,
            'department': dept,
            'semester': sem,
            'uploaded_by': staff_id,
            'uploaded_by_name': current_user.name,
            'uploaded_at': datetime.datetime.utcnow()
        })

        # Alert students
        students = list(db.users.find({'role': 'student', 'department': dept, 'semester': sem}))
        for stud in students:
            create_notification(
                user_id=stud['_id'],
                title=f"New {file_type.replace('_', ' ').title()}",
                content=f"'{title}' was uploaded by {current_user.name}.",
                link=url_for('student.files') if file_type != 'syllabus' else url_for('student.syllabus')
            )

        flash(f'File "{original_name}" uploaded successfully.', 'success')
        return redirect(url_for('staff.files_mgmt'))

    my_files = list(db.files.find({'uploaded_by': staff_id}).sort('uploaded_at', -1))
    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']
    return render_template('staff/files.html', files=my_files, departments=departments)


@staff_bp.route('/files/delete/<file_id>', methods=['POST'])
@login_required
@staff_required
def delete_file(file_id):
    db = get_db()
    staff_id = ObjectId(current_user.id)
    file_doc = db.files.find_one({'_id': ObjectId(file_id)})

    if not file_doc:
        flash('File not found.', 'error')
    elif str(file_doc['uploaded_by']) != str(staff_id):
        flash('Permission denied.', 'error')
    else:
        filepath = os.path.join(Config.UPLOAD_FOLDER, 'files', file_doc['filename'])
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        db.files.delete_one({'_id': ObjectId(file_id)})
        flash('File deleted.', 'success')
    return redirect(url_for('staff.files_mgmt'))


@staff_bp.route('/announcements', methods=['GET', 'POST'])
@login_required
@staff_required
def announcements_mgmt():
    db = get_db()
    staff_id = ObjectId(current_user.id)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        target_role = request.form.get('target_role', 'all')
        target_dept = request.form.get('target_dept', 'all')
        target_sem_str = request.form.get('target_semester', '0')
        target_sem = int(target_sem_str) if target_sem_str.isdigit() else 0

        db.announcements.insert_one({
            'title': title,
            'content': content,
            'target_role': target_role,
            'target_dept': target_dept,
            'target_sem': target_sem,
            'created_by': staff_id,
            'created_by_name': current_user.name,
            'created_by_role': current_user.role,
            'created_at': datetime.datetime.utcnow()
        })

        # Send notifications
        notify_query = {}
        if target_role != 'all':
            notify_query['role'] = target_role
        if target_dept != 'all':
            notify_query['department'] = target_dept
        if target_sem != 0:
            notify_query['semester'] = target_sem

        targets = list(db.users.find(notify_query))
        for t in targets:
            if str(t['_id']) != str(staff_id):
                create_notification(
                    user_id=t['_id'],
                    title="New Announcement",
                    content=f"'{title}' posted by {current_user.name}.",
                    link=url_for('student.announcements')
                )

        flash('Announcement posted.', 'success')
        return redirect(url_for('staff.announcements_mgmt'))

    my_announcements = list(db.announcements.find({'created_by': staff_id}).sort('created_at', -1))
    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']
    return render_template('staff/announcements.html', announcements=my_announcements, departments=departments)


@staff_bp.route('/announcements/delete/<ann_id>', methods=['POST'])
@login_required
@staff_required
def delete_announcement(ann_id):
    db = get_db()
    staff_id = ObjectId(current_user.id)
    ann = db.announcements.find_one({'_id': ObjectId(ann_id)})
    if not ann:
        flash('Announcement not found.', 'error')
    elif str(ann['created_by']) != str(staff_id):
        flash('Permission denied.', 'error')
    else:
        db.announcements.delete_one({'_id': ObjectId(ann_id)})
        flash('Announcement deleted.', 'success')
    return redirect(url_for('staff.announcements_mgmt'))


@staff_bp.route('/students')
@login_required
@staff_required
def students():
    db = get_db()
    search = request.args.get('search', '').strip()
    dept = request.args.get('department', current_user.department).strip()
    sem_str = request.args.get('semester', '')
    query = {'role': 'student', 'department': dept}
    if sem_str.isdigit():
        query['semester'] = int(sem_str)
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'roll_no': {'$regex': search, '$options': 'i'}},
        ]
    student_list = list(db.users.find(query).sort('roll_no', 1))
    departments = db.users.distinct('department') or ['MCA', 'MBA', 'B.Tech', 'M.Sc']
    return render_template('staff/students.html', students=student_list, search=search,
                           dept_filter=dept, sem_filter=sem_str, departments=departments)


@staff_bp.route('/leave', methods=['GET', 'POST'])
@login_required
@staff_required
def leave_mgmt():
    db = get_db()
    staff_id = ObjectId(current_user.id)

    if request.method == 'POST':
        leave_id = request.form.get('leave_id')
        action = request.form.get('action')
        review_note = request.form.get('review_note', '').strip()
        leave_doc = db.leave_requests.find_one({'_id': ObjectId(leave_id)})

        if leave_doc and action in ('approved', 'rejected'):
            db.leave_requests.update_one({'_id': ObjectId(leave_id)}, {'$set': {
                'status': action,
                'reviewed_by': staff_id,
                'review_note': review_note,
                'reviewed_at': datetime.datetime.utcnow(),
            }})
            create_notification(
                user_id=leave_doc['student_id'],
                title=f'Leave {action.title()}',
                content=f'Your leave request has been {action}. {review_note}',
                link=url_for('student.leave'),
            )
            flash(f'Leave request {action}.', 'success')
        return redirect(url_for('staff.leave_mgmt'))

    filter_status = request.args.get('status', 'pending')
    query = {}
    if filter_status != 'all':
        query['status'] = filter_status
    requests_list = list(db.leave_requests.find(query).sort('created_at', -1))
    return render_template('staff/leave.html', requests=requests_list, filter_status=filter_status)


@staff_bp.route('/events')
@login_required
@staff_required
def events():
    db = get_db()
    upcoming = list(db.events.find({'event_date': {'$gte': datetime.datetime.combine(datetime.date.today(), datetime.time.min)}}).sort('event_date', 1))
    past = list(db.events.find({'event_date': {'$lt': datetime.datetime.combine(datetime.date.today(), datetime.time.min)}}).sort('event_date', -1).limit(10))
    return render_template('staff/events.html', upcoming=upcoming, past=past)


# ---------------------------------------------------------------------------
# Admin BP Routes
# ---------------------------------------------------------------------------
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    db = get_db()
    today = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
    recent_attendance = list(db.attendance.find().sort('date', -1).limit(10))
    smap = staff_name_map(db)
    student_map = {str(u['_id']): u for u in db.users.find({'role': 'student'}, {'name': 1, 'roll_no': 1})}
    for r in recent_attendance:
        r['staff_name'] = smap.get(str(r.get('marked_by', '')), 'Staff')
        st = student_map.get(str(r.get('student_id', '')))
        r['student_name'] = st['name'] if st else 'Unknown'
        r['student_roll'] = st['roll_no'] if st else 'N/A'
    return render_template('admin/dashboard.html',
                           total_students=db.users.count_documents({'role': 'student'}),
                           total_staff=db.users.count_documents({'role': 'staff'}),
                           total_records=db.attendance.count_documents({}),
                           today_records=db.attendance.count_documents({'date': today}),
                           recent_attendance=recent_attendance,
                           recent_users=list(db.users.find().sort('created_at', -1).limit(5)),
                           department=Config.DEFAULT_DEPARTMENT)


@admin_bp.route('/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users_mgmt():
    db = get_db()
    if request.method == 'POST' and request.form.get('action') == 'create':
        role = request.form.get('role')
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        roll_no = request.form.get('roll_no', '').strip()
        dept = request.form.get('department', Config.DEFAULT_DEPARTMENT).strip()
        sem_str = request.form.get('semester', str(Config.DEFAULT_SEMESTER))
        sem = int(sem_str) if sem_str.isdigit() else 1

        try:
            if role == 'student':
                if not roll_no:
                    raise ValueError('Roll number required.')
                if db.users.find_one({'roll_no': roll_no.upper()}):
                    raise ValueError('Roll number exists.')
                User.create_user(role='student', name=name, roll_no=roll_no,
                                 department=dept, semester=sem)
            else:
                if not email:
                    raise ValueError('Email required.')
                if db.users.find_one({'email': email.lower()}):
                    raise ValueError('Email exists.')
                User.create_user(role=role, name=name, email=email, department=dept)
            flash(f"User '{name}' created.", 'success')
        except ValueError as e:
            flash(str(e), 'error')
        return redirect(url_for('admin.users_mgmt'))

    search = request.args.get('search', '').strip()
    filter_role = request.args.get('role', '')
    query = {}
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'email': {'$regex': search, '$options': 'i'}},
            {'roll_no': {'$regex': search, '$options': 'i'}},
        ]
    if filter_role:
        query['role'] = filter_role
        
    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']

    return render_template('admin/users.html',
                           users=list(db.users.find(query).sort('name', 1)),
                           search=search, role_filter=filter_role, departments=departments)


@admin_bp.route('/users/delete/<user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    db = get_db()
    user = db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'error')
    elif str(user['_id']) == str(current_user.id):
        flash('Cannot delete yourself.', 'error')
    else:
        db.users.delete_one({'_id': ObjectId(user_id)})
        flash(f"Deleted {user['name']}.", 'success')
    return redirect(url_for('admin.users_mgmt'))


@admin_bp.route('/attendance')
@login_required
@admin_required
def attendance_overview():
    db = get_db()
    filter_date = request.args.get('date', '')
    filter_dept = request.args.get('department', '')
    filter_sem = request.args.get('semester', '')
    filter_hour = request.args.get('hour', '')

    query = {}
    if filter_date:
        query['date'] = datetime.datetime.strptime(filter_date, '%Y-%m-%d')
    if filter_dept:
        query['department'] = filter_dept
    if filter_sem:
        query['semester'] = int(filter_sem)
    if filter_hour:
        query['hour'] = int(filter_hour)

    records = list(db.attendance.find(query).sort('date', -1).limit(200))
    smap = staff_name_map(db)
    student_map = {str(u['_id']): u for u in db.users.find({'role': 'student'}, {'name': 1, 'roll_no': 1})}
    for r in records:
        r['staff_name'] = smap.get(str(r.get('marked_by', '')), 'Staff')
        st = student_map.get(str(r.get('student_id', '')))
        r['student_name'] = st['name'] if st else 'Unknown'
        r['student_roll'] = st['roll_no'] if st else 'N/A'

    stats = {
        'present': db.attendance.count_documents({**query, 'status': 'present'}),
        'absent': db.attendance.count_documents({**query, 'status': 'absent'}),
        'late': db.attendance.count_documents({**query, 'status': 'late'}),
    }

    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']

    return render_template('admin/attendance.html', records=records, stats=stats, filter_date=filter_date,
                           filter_dept=filter_dept, filter_sem=filter_sem, filter_hour=filter_hour,
                           departments=departments)


@admin_bp.route('/timetable', methods=['GET', 'POST'])
@login_required
@admin_required
def timetable_mgmt():
    db = get_db()
    dept = request.args.get('department', Config.DEFAULT_DEPARTMENT).strip()
    sem_str = request.args.get('semester', str(Config.DEFAULT_SEMESTER))
    sem = int(sem_str) if sem_str.isdigit() else 1

    staff_members = list(db.users.find({'role': 'staff'}).sort('name', 1))

    if request.method == 'POST':
        day = request.form.get('day')
        hour = int(request.form.get('hour', 1))
        subject = request.form.get('subject', '').strip()
        staff_id = request.form.get('staff_id', '').strip()

        db.timetables.update_one(
            {'department': dept, 'semester': sem, 'day': day, 'hour': hour},
            {'$set': {
                'subject': subject,
                'staff_id': ObjectId(staff_id) if staff_id else None,
                'updated_at': datetime.datetime.utcnow()
            }},
            upsert=True
        )
        flash(f'Timetable updated for {day} Hour {hour}.', 'success')
        return redirect(url_for('admin.timetable_mgmt', department=dept, semester=sem))

    grid = get_timetable_grid(dept, sem)
    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']

    return render_template('admin/timetable.html', grid=grid, dept=dept, sem=sem,
                           staff_members=staff_members, departments=departments)


@admin_bp.route('/syllabus', methods=['GET', 'POST'])
@login_required
@admin_required
def syllabus_mgmt():
    db = get_db()
    admin_id = ObjectId(current_user.id)
    dept = request.values.get('department', Config.DEFAULT_DEPARTMENT).strip()
    sem_str = request.values.get('semester', str(Config.DEFAULT_SEMESTER))
    sem = int(sem_str) if sem_str.isdigit() else 1

    if request.method == 'POST':
        action = request.form.get('action', 'upload')
        if action == 'delete':
            file_id = request.form.get('file_id')
            file_doc = db.files.find_one({'_id': ObjectId(file_id), 'file_type': 'syllabus'})
            if file_doc:
                filepath = os.path.join(Config.UPLOAD_FOLDER, 'files', file_doc['filename'])
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                db.files.delete_one({'_id': ObjectId(file_id)})
                flash(f"Syllabus for {file_doc.get('subject', 'subject')} deleted.", 'success')
            return redirect(url_for('admin.syllabus_mgmt', department=dept, semester=sem))

        subject = request.form.get('subject', '').strip()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        file = request.files.get('file')

        if not subject:
            flash('Subject name is required.', 'error')
            return redirect(url_for('admin.syllabus_mgmt', department=dept, semester=sem))
        if not file or file.filename == '':
            flash('Please select a syllabus file to upload.', 'error')
            return redirect(url_for('admin.syllabus_mgmt', department=dept, semester=sem))

        filename, original_name = save_uploaded_file(file)
        title = title or f'{subject} Syllabus'

        existing = db.files.find_one({
            'file_type': 'syllabus', 'department': dept, 'semester': sem, 'subject': subject,
        })
        if existing:
            old_path = os.path.join(Config.UPLOAD_FOLDER, 'files', existing['filename'])
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
            db.files.delete_one({'_id': existing['_id']})

        db.files.insert_one({
            'title': title,
            'description': description,
            'subject': subject,
            'file_type': 'syllabus',
            'filename': filename,
            'original_name': original_name,
            'department': dept,
            'semester': sem,
            'uploaded_by': admin_id,
            'uploaded_by_name': current_user.name,
            'uploaded_at': datetime.datetime.utcnow(),
        })
        notify_syllabus_upload(dept, sem, subject, title)
        flash(f'Syllabus uploaded for {subject}.', 'success')
        return redirect(url_for('admin.syllabus_mgmt', department=dept, semester=sem))

    syllabus_files = list(db.files.find({
        'file_type': 'syllabus', 'department': dept, 'semester': sem,
    }).sort([('subject', ASCENDING), ('uploaded_at', -1)]))
    subjects = get_subjects_for_class(dept, sem)
    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']
    return render_template('admin/syllabus.html', files=syllabus_files, dept=dept, sem=sem,
                           subjects=subjects, departments=departments)


@admin_bp.route('/files', methods=['GET', 'POST'])
@login_required
@admin_required
def files_mgmt():
    db = get_db()
    if request.method == 'POST':
        file_id = request.form.get('file_id')
        file_doc = db.files.find_one({'_id': ObjectId(file_id)})
        if file_doc:
            filepath = os.path.join(Config.UPLOAD_FOLDER, 'files', file_doc['filename'])
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            db.files.delete_one({'_id': ObjectId(file_id)})
            flash('File deleted by Admin.', 'success')
        return redirect(url_for('admin.files_mgmt'))

    all_files = list(db.files.find().sort('uploaded_at', -1))
    return render_template('admin/files.html', files=all_files)


@admin_bp.route('/announcements', methods=['GET', 'POST'])
@login_required
@admin_required
def announcements_mgmt():
    db = get_db()
    admin_id = ObjectId(current_user.id)

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            ann_id = request.form.get('ann_id')
            db.announcements.delete_one({'_id': ObjectId(ann_id)})
            flash('Announcement deleted.', 'success')
            return redirect(url_for('admin.announcements_mgmt'))

        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        target_role = request.form.get('target_role', 'all')
        target_dept = request.form.get('target_dept', 'all')
        target_sem_str = request.form.get('target_semester', '0')
        target_sem = int(target_sem_str) if target_sem_str.isdigit() else 0

        db.announcements.insert_one({
            'title': title,
            'content': content,
            'target_role': target_role,
            'target_dept': target_dept,
            'target_sem': target_sem,
            'created_by': admin_id,
            'created_by_name': current_user.name,
            'created_by_role': current_user.role,
            'created_at': datetime.datetime.utcnow()
        })

        # Notify
        notify_query = {}
        if target_role != 'all':
            notify_query['role'] = target_role
        if target_dept != 'all':
            notify_query['department'] = target_dept
        if target_sem != 0:
            notify_query['semester'] = target_sem

        targets = list(db.users.find(notify_query))
        for t in targets:
            if str(t['_id']) != str(admin_id):
                create_notification(
                    user_id=t['_id'],
                    title="System Announcement",
                    content=f"'{title}' posted by Admin.",
                    link=url_for('student.announcements')
                )

        flash('Announcement posted.', 'success')
        return redirect(url_for('admin.announcements_mgmt'))

    all_announcements = list(db.announcements.find().sort('created_at', -1))
    departments = db.users.distinct('department')
    if not departments:
        departments = ['MCA', 'MBA', 'B.Tech', 'M.Sc']
    return render_template('admin/announcements.html', announcements=all_announcements, departments=departments)


@admin_bp.route('/events', methods=['GET', 'POST'])
@login_required
@admin_required
def events_mgmt():
    db = get_db()

    if request.method == 'POST':
        action = request.form.get('action', 'create')
        if action == 'delete':
            event_id = request.form.get('event_id')
            db.events.delete_one({'_id': ObjectId(event_id)})
            flash('Event deleted.', 'success')
            return redirect(url_for('admin.events_mgmt'))

        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        event_date = request.form.get('event_date', '').strip()
        event_type = request.form.get('event_type', 'event')
        location = request.form.get('location', '').strip()

        if not title or not event_date:
            flash('Title and date are required.', 'warning')
            return redirect(url_for('admin.events_mgmt'))

        db.events.insert_one({
            'title': title,
            'description': description,
            'event_date': datetime.datetime.strptime(event_date, '%Y-%m-%d'),
            'event_type': event_type,
            'location': location,
            'created_at': datetime.datetime.utcnow(),
        })

        all_users = list(db.users.find({'role': {'$in': ['student', 'staff']}}))
        for u in all_users:
            create_notification(
                user_id=u['_id'],
                title='New College Event',
                content=f'"{title}" scheduled on {event_date}.',
                link=url_for('student.events') if u['role'] == 'student' else url_for('staff.events'),
            )

        flash('Event created successfully.', 'success')
        return redirect(url_for('admin.events_mgmt'))

    all_events = list(db.events.find().sort('event_date', -1))
    return render_template('admin/events.html', events=all_events)


# ---------------------------------------------------------------------------
# App factory & APIs
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    Config.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(user_id)

    @app.before_request
    def ensure_db():
        try:
            init_db()
        except Exception as exc:
            print(f'[WARNING] DB init: {exc}')

    app.teardown_appcontext(close_db)
    
    # Register JSON notifications endpoint
    @app.route('/api/notifications')
    @login_required
    def get_notifications():
        db = get_db()
        uid = ObjectId(current_user.id)
        notifs = list(db.notifications.find({'user_id': uid}).sort('created_at', -1).limit(15))
        for n in notifs:
            n['_id'] = str(n['_id'])
            # Render readable relative time or formatting
            time_diff = datetime.datetime.utcnow() - n['created_at']
            if time_diff.days > 0:
                n['time_ago'] = f"{time_diff.days}d ago"
            elif time_diff.seconds >= 3600:
                n['time_ago'] = f"{time_diff.seconds // 3600}h ago"
            elif time_diff.seconds >= 60:
                n['time_ago'] = f"{time_diff.seconds // 60}m ago"
            else:
                n['time_ago'] = "just now"
        unread_count = db.notifications.count_documents({'user_id': uid, 'read': False})
        return jsonify({
            'notifications': [{
                'id': n['_id'],
                'title': n['title'],
                'content': n['content'],
                'link': n.get('link', ''),
                'read': n['read'],
                'time_ago': n['time_ago']
            } for n in notifs],
            'unread_count': unread_count
        })

    @app.route('/api/notifications/read', methods=['POST'])
    @login_required
    def mark_notifications_read():
        db = get_db()
        uid = ObjectId(current_user.id)
        db.notifications.update_many({'user_id': uid, 'read': False}, {'$set': {'read': True}})
        return jsonify({'success': True})

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(staff_bp, url_prefix='/staff')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    @app.route('/')
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role == 'student':
            return redirect(url_for('student.dashboard'))
        if current_user.role == 'staff':
            return redirect(url_for('staff.dashboard'))
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('auth.logout'))

    @app.errorhandler(404)
    def not_found(e):
        flash('Page not found.', 'warning')
        return redirect(url_for('index'))

    @app.errorhandler(500)
    def server_error(e):
        flash('Something went wrong.', 'error')
        return redirect(url_for('index'))

    @app.context_processor
    def inject_globals():
        ctx = {
            'default_department': Config.DEFAULT_DEPARTMENT,
            'now': datetime.datetime.utcnow(),
        }
        if current_user.is_authenticated and current_user.role == 'staff':
            try:
                ctx['pending_leave_count'] = get_db().leave_requests.count_documents({'status': 'pending'})
            except Exception:
                ctx['pending_leave_count'] = 0
        return ctx

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
