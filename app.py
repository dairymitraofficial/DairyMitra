
import os
import re
import secrets
import string
import logging
from datetime import datetime, timezone, date, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo   
import MySQLdb.cursors

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_mysqldb import MySQL

from werkzeug.security import generate_password_hash, check_password_hash
from twilio.rest import Client
import smtplib
from flask import send_from_directory
from functools import wraps   
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException


import pandas as pd
from ai.milk_prediction import predict_milk
from ai.anomaly_detection import detect_anomaly
from ai.vendor_analysis import analyze_vendor

from functools import lru_cache

from apscheduler.schedulers.background import BackgroundScheduler

from backup_system import  create_user_backup,  restore_user_backup, create_full_backup, create_backup, upload_to_drive, automatic_backup


load_dotenv()

# ------------------------------
# Basic config & logging
# ------------------------------
app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "d7e5f19e4c2a4a7b93c6f405f3d9a8c3b1a0c9e7e8d5f4c2a7b6f5e3a9d0c8f2") 

app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

# MySQL configuration from environment
app.config['MYSQL_HOST'] = os.getenv("MYSQL_HOST")
app.config['MYSQL_USER'] = os.getenv("MYSQL_USER")
app.config['MYSQL_PASSWORD'] = os.getenv("MYSQL_PASSWORD")
app.config['MYSQL_DB'] = os.getenv("MYSQL_DB")
app.config["MYSQL_PORT"] = int(os.getenv("MYSQL_PORT", 3306))
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

app.config['MYSQL_CONNECT_TIMEOUT'] = 30
app.config['MYSQL_READ_DEFAULT_FILE'] = ''
app.config['MYSQL_AUTOCOMMIT'] = True
mysql = MySQL(app)

class SafeCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, params=None):

        if params:

            fixed = []

            for p in params:

                if isinstance(p, bytes):
                    p = p.decode()

                if isinstance(p, str) and p.isdigit():
                    p = int(p)

                fixed.append(p)

            params = tuple(fixed)

        return self.cursor.execute(query, params)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def close(self):
        return self.cursor.close()

    def __getattr__(self, name):
        return getattr(self.cursor, name)

# Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE")

# Email config
EMAIL_ADDRESS = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASS")

# OTP etc
OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES") or 5)
PASSWORD_RESET_EXPIRY_MINUTES = int(os.getenv("PASSWORD_RESET_EXPIRY_MINUTES") or 15)

# Logging (audit)
LOG_FILE = os.path.join(os.getcwd(), "audit.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def audit_log(user_id, action, details=""):
    """Append an audit log entry (file-based)."""
    try:
        logging.info(f"user_id={user_id} action={action} details={details}")
    except Exception as e:
        print("Audit logging failed:", e)



# ------------------------------
# Helper utilities
# ------------------------------
def send_sms(to, body):
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE:
        logging.warning("Twilio not configured; SMS skipped.")
        return False
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(to=to, from_=TWILIO_PHONE, body=body)
        return True
    except Exception:
        logging.exception("SMS sending failed")
        return False


BREVO_API_KEY = os.getenv("BREVO_API_KEY")

def send_email(to, subject, body):

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = BREVO_API_KEY

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": to}],
        sender={"email": "dairymitra.official@gmail.com", "name": "DairyMitra"},
        subject=subject,
        text_content=body
    )

    try:
        api_instance.send_transac_email(email)
        print("EMAIL SENT SUCCESS")
        return True
    except ApiException as e:
        print("EMAIL ERROR:", e)
        return False


def generate_otp(length=6):
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def ensure_user_id_int():
    """
    Ensure session['id'] is an int (fix bytes->int or string).
    Call near start of requests where needed.
    """
    uid = session.get('id')
    if uid is None:
        return None
    try:
        if isinstance(uid, bytes):
            uid = int(uid.decode())
        else:
            uid = int(uid)
        session['id'] = uid
        return uid
    except Exception:
        return session.get('id')


# ------------------------------
# Auth routes (unchanged behavior except ensuring int user_id)
# ------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():

    if 'loggedin' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':

        email = request.form.get('email')
        password = request.form.get('password')

        cursor = SafeCursor(mysql.connection.cursor())

        # -----------------------------
        # OWNER LOGIN
        # -----------------------------
        cursor.execute(
            'SELECT * FROM users WHERE email = %s',
            (email,)
        )

        account = cursor.fetchone()

        if account and check_password_hash(account['password'], password):

            if account.get('is_verified'):

                session.clear()

                session['id'] = int(account['id'])
                session['loggedin'] = True
                session['role'] = "owner"
                session['email'] = account['email']
                session['dairy_name'] = account.get('dairy_name')

                flash('Logged in successfully!', 'success')

                return redirect(url_for('dashboard'))

        # -----------------------------
        # STAFF LOGIN
        # -----------------------------
        cursor.execute(
            "SELECT * FROM staff WHERE email=%s AND is_active=1",
            (email,)
        )

        staff = cursor.fetchone()

        if staff and check_password_hash(staff['password'], password):

            session.clear()

            session['loggedin'] = True
            session['role'] = "staff"

            session['staff_id'] = staff['id']
            session['owner_id'] = staff['owner_id']
            session['vehicle'] = staff['vehicle_number']

            session['id'] = staff['owner_id']   # important

            flash('Staff login successful', 'success')

            return redirect(url_for('dashboard'))

        flash('Invalid credentials!', 'danger')

    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/signup', methods=['GET', 'POST'])
def signup():

    if 'loggedin' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':

        dairy_name = request.form.get('dairy_name', '').strip()
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        phone = request.form.get('phone', '').strip()

        # password validation
        password_pattern = r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$'

        if not re.match(password_pattern, password):
            flash('पासवर्ड किमान 8 अक्षरे असावा, त्यात अक्षरे, अंक आणि symbol असणे आवश्यक आहे.', 'danger')
            return redirect(url_for('signup'))

        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return redirect(url_for('signup'))

        if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            flash('Invalid email!', 'danger')
            return redirect(url_for('signup'))

        cursor = SafeCursor(mysql.connection.cursor())

        cursor.execute(
            "SELECT id FROM users WHERE email = %s",
            (email,)
        )

        if cursor.fetchone():
            flash('Account already exists!', 'warning')
            return redirect(url_for('signup'))

        # OTP generate
        otp = generate_otp()

        hashed_password = generate_password_hash(password)

        # temporarily store signup data
        session['temp_signup'] = {
            'email': email,
            'password': hashed_password,
            'phone': phone,
            'dairy_name': dairy_name,
            'otp': otp
        }

        email_sent = send_email(
            email,
            "तुमचा OTP",
            f"तुमचा OTP: {otp}"
        )

        flash('OTP sent. Please verify.', 'info')

        return redirect(url_for('verify_account'))

    return render_template('auth/signup.html')


@app.route('/verify-account', methods=['GET', 'POST'])
def verify_account():
    temp = session.get('temp_signup')
    if not temp:
        flash('Session expired. Signup again.', 'warning')
        return redirect(url_for('signup'))
    if request.method == 'POST':
        otp_entered = request.form.get('otp')
        if otp_entered == temp.get('otp'):
            cursor = SafeCursor(mysql.connection.cursor())
            cursor.execute("""
                INSERT INTO users (email, password, phone, dairy_name, is_verified)
                VALUES (%s, %s, %s, %s, TRUE)
            """, (temp['email'], temp['password'], temp['phone'], temp['dairy_name']))
            mysql.connection.commit()
            session.pop('temp_signup', None)
            flash('Account verified. Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid OTP.', 'danger')
    return render_template('auth/verify_account.html', email=temp.get('email'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        cursor = SafeCursor(mysql.connection.cursor())
        cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
        account = cursor.fetchone()
        if account:
            otp = generate_otp()
            cursor.execute("""
                UPDATE users SET otp = %s, otp_expiry = DATE_ADD(NOW(), INTERVAL %s MINUTE)
                WHERE email = %s
            """, (otp, OTP_EXPIRY_MINUTES, email))
            mysql.connection.commit()
            send_email(email, 'Password reset OTP', f"Your OTP: {otp}")
            session['reset_email'] = email
            flash('OTP sent to email.', 'info')
            return redirect(url_for('verify_reset_otp'))
        else:
            flash('Email not found.', 'danger')
    return render_template('auth/forgot_password.html')


@app.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    if 'reset_email' not in session:
        flash('Session expired.', 'warning')
        return redirect(url_for('forgot_password'))

    email = session['reset_email']
    if request.method == 'POST':
        otp = request.form.get('otp')
        cursor = SafeCursor(mysql.connection.cursor())
        cursor.execute('SELECT otp, otp_expiry FROM users WHERE email = %s', (email,))
        acc = cursor.fetchone()
        if not acc:
            flash('Invalid request.', 'danger')
            return redirect(url_for('forgot_password'))

        now_utc = datetime.now(timezone.utc)
        otp_expiry = acc.get('otp_expiry')

        # ✅ Fix: ensure both datetimes are comparable
        if otp_expiry and otp_expiry.tzinfo is None:
            otp_expiry = otp_expiry.replace(tzinfo=timezone.utc)

        if otp == acc.get('otp') and (not otp_expiry or now_utc < otp_expiry):
            session['otp_verified'] = True
            flash('OTP verified. Set new password.', 'success')
            return redirect(url_for('reset_password'))
        else:
            flash('Invalid or expired OTP.', 'danger')

    return render_template('auth/verify_reset_otp.html', email=email)

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified') or 'reset_email' not in session:
        flash('Unauthorized access.', 'warning')
        return redirect(url_for('forgot_password'))
    email = session['reset_email']
    if request.method == 'POST':
        pwd = request.form.get('password')
        cpwd = request.form.get('confirm_password')
        if pwd != cpwd:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('reset_password'))
        hashed = generate_password_hash(pwd)
        cursor = SafeCursor(mysql.connection.cursor())
        cursor.execute("UPDATE users SET password = %s, otp = NULL, otp_expiry = NULL WHERE email = %s", (hashed, email))
        mysql.connection.commit()
        session.pop('otp_verified', None)
        session.pop('reset_email', None)
        flash('Password updated. Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('auth/reset_password.html')


@app.before_request
def require_login():
    """
    Basic protection: allow certain endpoints without login.
    Also normalize session['id'] to int if possible.
    """

    allowed = {
        'login', 'signup', 'verify_account', 'forgot_password',
        'verify_reset_otp', 'reset_password', 'static', 'healthcheck', 'favicon'
    }

    if request.endpoint and request.endpoint not in allowed and 'loggedin' not in session:
        return redirect(url_for('login'))

    if 'id' in session:
        uid = session['id']

        if isinstance(uid, bytes):
            uid = uid.decode()

        session['id'] = int(uid)
# ------------------------------
# Dashboard
# ------------------------------
from datetime import date

@app.route("/")
def dashboard():
    if "id" not in session:
        flash("Unauthorized request, please log in.", "danger")
        return redirect(url_for("login"))

    user_id = session["id"]

    cursor = SafeCursor(mysql.connection.cursor())

    # ✅ आजचं दूध (सकाळ/संध्याकाळ) – DATE() वापरलं
    cursor.execute(
        """
        SELECT slot, SUM(quantity) AS total_quantity
        FROM milk_collection
        WHERE user_id = %s AND DATE(date) = CURDATE()
        GROUP BY slot
        """,
        (user_id,)
    )
    milk_data = cursor.fetchall()

    morning_milk = 0
    evening_milk = 0
    for row in milk_data:
        slot = row['slot'].lower()   # ✅ case-insensitive compare
        if slot == 'morning':
            morning_milk = row['total_quantity']
        elif slot == 'evening':
            evening_milk = row['total_quantity']

    # ✅ एकूण ग्राहक
    cursor.execute(
        "SELECT COUNT(*) AS total_vendors FROM vendors WHERE user_id = %s",
        (user_id,)
    )
    vendor_count_result = cursor.fetchone()
    total_vendors = vendor_count_result['total_vendors'] if vendor_count_result else 0

    cursor.close()

    return render_template(
        "dashboard.html",
    
    )




# ------------------------------
# Vendors CRUD
# ------------------------------
@app.route('/add_vendor', methods=['GET', 'POST'])
def add_vendor():

    cursor = SafeCursor(mysql.connection.cursor())

    # NEXT AUTO ID suggestion
    cursor.execute("""
        SELECT MAX(vendor_id) AS max_id
        FROM vendors
        WHERE user_id=%s
    """, (session['id'],))

    res = cursor.fetchone()

    next_vendor_id = 1
    if res and res['max_id']:
        next_vendor_id = int(res['max_id']) + 1

    if request.method == 'POST':

        name = request.form.get('name')
        vendor_id = int(request.form.get('vendor_id'))
        address = request.form.get('address')
        milk_type = request.form.get('milk_type')
        phone = request.form.get('phone')

        # CHECK IF ID EXISTS
        cursor.execute("""
            SELECT 1 FROM vendors
            WHERE vendor_id=%s AND user_id=%s
        """, (vendor_id, session['id']))

        existing = cursor.fetchone()

        if existing:
            flash(f"❌ Vendor already exists at ID {vendor_id}", "danger")

            return render_template(
                'vendors/add_vendor.html',
                next_vendor_id=next_vendor_id,
                name=name,
                address=address,
                milk_type=milk_type,
                phone=phone,
                vendor_id=vendor_id
            )

        # INSERT NEW VENDOR
        cursor.execute("""
            INSERT INTO vendors
            (vendor_id,name,address,milk_type,phone,user_id)
            VALUES(%s,%s,%s,%s,%s,%s)
        """,(vendor_id,name,address,milk_type,phone,session['id']))

        mysql.connection.commit()
        get_vendors_cached.cache_clear() 

        flash("✔ Vendor Added Successfully","success")

        return redirect(url_for('add_vendor'))

    return render_template(
        'vendors/add_vendor.html',
        next_vendor_id=next_vendor_id
    )

@app.route('/vendor_list', methods=['GET'])
def vendor_list():
    search = request.args.get('search', '')
    cursor = SafeCursor(mysql.connection.cursor())

    query = "SELECT * FROM vendors WHERE user_id = %s"
    params = [session['id']]

    if search:
        query += " AND (name LIKE %s OR vendor_id LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += " ORDER BY vendor_id ASC"

    cursor.execute(query, params)
    vendors = cursor.fetchall()
    return render_template('vendors/vendor_list.html', vendors=vendors)


@app.route('/edit_vendor/<string:vendor_id>', methods=['GET', 'POST'])
def edit_vendor(vendor_id):
    cursor = SafeCursor(mysql.connection.cursor())
    cursor.execute("SELECT 1 FROM vendors WHERE vendor_id = %s AND user_id = %s", (vendor_id, session['id']))
    if not cursor.fetchone():
        flash('Unauthorized or vendor not found.', 'danger')
        return redirect(url_for('vendor_list'))
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        milk_type = request.form.get('milk_type')
        phone = request.form.get('phone')
        cursor.execute("""
            UPDATE vendors SET name=%s, address=%s, milk_type=%s, phone=%s
            WHERE vendor_id=%s AND user_id=%s
        """, (name, address, milk_type, phone, vendor_id, session['id']))
        mysql.connection.commit()
        get_vendors_cached.cache_clear() 
        audit_log(session['id'], 'edit_vendor', f"vendor_id={vendor_id}")
        flash('Vendor updated.', 'success')
        return redirect(url_for('vendor_list'))
    cursor.execute("SELECT * FROM vendors WHERE user_id = %s AND vendor_id=%s", (session['id'], vendor_id))
    vendor = cursor.fetchone()
    return render_template('vendors/edit_vendor.html', vendor=vendor)


@app.route('/delete_vendor/<int:vendor_id>', methods=['POST'])
def delete_vendor(vendor_id):

    confirm = request.form.get('confirm')

    if confirm != "1":
        flash("Confirm deletion first","warning")
        return redirect(url_for('vendor_list'))

    cursor = SafeCursor(mysql.connection.cursor())

    # delete vendor
    cursor.execute("""
        DELETE FROM vendors
        WHERE vendor_id=%s AND user_id=%s
    """,(vendor_id,session['id']))

    mysql.connection.commit()
    get_vendors_cached.cache_clear() 
    flash("Vendor Deleted","success")

    return redirect(url_for('vendor_list'))


@app.route('/add_staff', methods=['GET','POST'])
def add_staff():

    if "id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "owner":
        flash("Only owner can add staff", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        name = request.form.get("name")
        email = request.form.get("email")
        password = generate_password_hash(request.form.get("password"))
        vehicle = request.form.get("vehicle")

        cursor = SafeCursor(mysql.connection.cursor())

        cursor.execute("""
        INSERT INTO staff
        (owner_id,name,email,password,vehicle_number)
        VALUES (%s,%s,%s,%s,%s)
        """,(session["id"],name,email,password,vehicle))

        mysql.connection.commit()

        flash("Staff added successfully","success")

        return redirect(url_for("staff_list"))

    return render_template("staff/add_staff.html")

@app.route('/staff_list')
def staff_list():

    if "id" not in session:
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
    SELECT *
    FROM staff
    WHERE owner_id=%s
    ORDER BY id DESC
    """,(session["id"],))

    staff = cursor.fetchall()

    return render_template("staff/staff_list.html",staff=staff)

@app.route('/edit_staff/<int:staff_id>', methods=['GET','POST'])
def edit_staff(staff_id):

    cursor = SafeCursor(mysql.connection.cursor())

    if request.method == "POST":

        name = request.form.get("name")
        email = request.form.get("email")
        vehicle = request.form.get("vehicle")

        cursor.execute("""
        UPDATE staff
        SET name=%s,email=%s,vehicle_number=%s
        WHERE id=%s AND owner_id=%s
        """,(name,email,vehicle,staff_id,session["id"]))

        mysql.connection.commit()

        flash("Staff updated successfully","success")

        return redirect(url_for("staff_list"))

    cursor.execute("""
    SELECT *
    FROM staff
    WHERE id=%s AND owner_id=%s
    """,(staff_id,session["id"]))

    staff = cursor.fetchone()

    return render_template("staff/edit_staff.html",staff=staff)


@app.route('/reset_staff_password/<int:staff_id>', methods=['GET','POST'])
def reset_staff_password(staff_id):

    if "id" not in session:
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())

    if request.method == "POST":

        password = request.form.get("password")
        confirm = request.form.get("confirm_password")

        if password != confirm:
            flash("Passwords do not match","danger")
            return redirect(request.url)

        hashed = generate_password_hash(password)

        cursor.execute("""
        UPDATE staff
        SET password=%s
        WHERE id=%s AND owner_id=%s
        """,(hashed,staff_id,session["id"]))

        mysql.connection.commit()

        flash("Password reset successfully","success")

        return redirect(url_for("staff_list"))

    return render_template("staff/reset_staff_password.html")

@app.route('/disable_staff/<int:staff_id>')
def disable_staff(staff_id):

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
    UPDATE staff
    SET is_active=0
    WHERE id=%s AND owner_id=%s
    """,(staff_id,session["id"]))

    mysql.connection.commit()

    flash("Staff disabled","warning")

    return redirect(url_for("staff_list"))

@app.route('/enable_staff/<int:staff_id>')
def enable_staff(staff_id):

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
    UPDATE staff
    SET is_active=1
    WHERE id=%s AND owner_id=%s
    """,(staff_id,session["id"]))

    mysql.connection.commit()

    flash("Staff enabled","success")

    return redirect(url_for("staff_list"))

@app.route("/vehicle_milk_report")
def vehicle_milk_report():

    if "id" not in session:
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
    SELECT
        s.vehicle_number,
        SUM(m.quantity) AS total_milk
    FROM milk_collection m
    JOIN staff s
        ON m.staff_id = s.id
    WHERE m.user_id=%s
    GROUP BY s.vehicle_number
    ORDER BY total_milk DESC
    """,(session["id"],))

    vehicles = cursor.fetchall()

    return render_template(
        "reports/vehicle_milk_report.html",
        vehicles=vehicles
    )
# ------------------------------
# Milk Rate
# ------------------------------
@app.route('/milk_rate', methods=['GET', 'POST'])
def milk_rate():
    cursor = SafeCursor(mysql.connection.cursor())
    if request.method == 'POST':
        date_from = request.form.get('date')
        rate = float(request.form.get('rate') or 0)
        animal = request.form.get('animal')
        cursor.execute("""
            INSERT INTO milk_rates (user_id, animal, rate, date_from)
            VALUES (%s, %s, %s, %s)
        """, (session['id'], animal, rate, date_from))
        mysql.connection.commit()
        audit_log(session['id'], 'add_milk_rate', f"{animal} {rate} from {date_from}")
        flash('Milk rate added.', 'success')
        return redirect(url_for('milk_rate'))
    cursor.execute("SELECT * FROM milk_rates WHERE user_id = %s ORDER BY date_from DESC", (session['id'],))
    rates = cursor.fetchall()
    return render_template('rates/milk_rate.html', rates=rates)

os.environ["TZ"] = "Asia/Kolkata"

def _auto_slot():
    """System time पाहून default slot ठरवतो (Asia/Kolkata)."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    print("DEBUG TIME (IST):", now.strftime("%Y-%m-%d %H:%M:%S"), "Hour:", now.hour)
    if now.hour < 15:  # 00:00 → 14:59
        return "morning"
    return "evening"

@lru_cache(maxsize=128)
def get_vendors_cached(user_id):

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
    SELECT *
    FROM vendors
    WHERE user_id=%s
    ORDER BY vendor_id ASC
    """,(user_id,))

    return cursor.fetchall()

@lru_cache(maxsize=512)
def get_vendor_rate(cursor, vendor_id, animal, entry_date):

    uid = int(session.get('id',0))

    # ensure entry_date is date object
    if isinstance(entry_date, bytes):
        entry_date = entry_date.decode()

    if isinstance(entry_date, str):
        entry_date = datetime.strptime(entry_date, "%Y-%m-%d").date()
    
    # -------------------------
    # vendor special rate
    # -------------------------
    cursor.execute("""
        SELECT cow_rate, buffalo_rate
        FROM vendor_milk_rates
        WHERE vendor_id=%s
        AND user_id=%s
        AND date_from<=%s
        ORDER BY date_from DESC
        LIMIT 1
    """, (vendor_id, uid, entry_date))

    special = cursor.fetchone()

    if special:

        if animal == "cow" and special['cow_rate']:
            return float(special['cow_rate'])

        if animal == "buffalo" and special['buffalo_rate']:
            return float(special['buffalo_rate'])

    # -------------------------
    # fallback default rate
    # -------------------------
    cursor.execute("""
        SELECT rate
        FROM milk_rates
        WHERE user_id=%s
        AND animal=%s
        AND date_from<=%s
        ORDER BY date_from DESC
        LIMIT 1
    """, (uid, animal, entry_date))

    r = cursor.fetchone()

    return float(r['rate']) if r else 0

@app.route('/vendor_rate', methods=['GET','POST'])
def vendor_rate():

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
        SELECT vendor_id,name
        FROM vendors
        WHERE user_id=%s
        ORDER BY vendor_id ASC
    """,(session['id'],))

    vendors = cursor.fetchall()

    if request.method=='POST':

        vendor_id = request.form.get("vendor_id")
        cow_rate = request.form.get("cow_rate")
        buffalo_rate = request.form.get("buffalo_rate")
        date_from = request.form.get("date")

        cursor.execute("""
            INSERT INTO vendor_milk_rates
            (vendor_id,user_id,cow_rate,buffalo_rate,date_from)
            VALUES(%s,%s,%s,%s,%s)
        """,(vendor_id,session['id'],cow_rate,buffalo_rate,date_from))

        mysql.connection.commit()

        flash("Vendor special rate saved","success")

        return redirect(url_for("vendor_rate"))

    cursor.execute("""
        SELECT v.name,r.*
        FROM vendor_milk_rates r
        JOIN vendors v
        ON v.vendor_id=r.vendor_id
        AND v.user_id=r.user_id
        WHERE r.user_id=%s
        ORDER BY r.date_from DESC
    """,(session['id'],))

    rates = cursor.fetchall()

    return render_template(
        "rates/vendor_rate.html",
        vendors=vendors,
        rates=rates
    )

@app.route('/delete_milk_rate/<int:rate_id>', methods=['POST'])
def delete_milk_rate(rate_id):
    confirm = request.form.get('confirm') or request.args.get('confirm')
    if str(confirm) != '1':
        flash('Please confirm deletion.', 'warning')
        return redirect(url_for('milk_rate'))
    try:
        cursor = SafeCursor(mysql.connection.cursor())
        cursor.execute("DELETE FROM milk_rates WHERE id = %s AND user_id = %s", (rate_id, session['id']))
        mysql.connection.commit()
        audit_log(session['id'], 'delete_milk_rate', f"id={rate_id}")
        flash('Milk rate deleted.', 'success')
    except Exception:
        logging.exception("Error deleting milk rate")
        flash('Error deleting milk rate.', 'danger')
    return redirect(url_for('milk_rate'))






def _get_date_slot_from_request(req):

    date_val = req.form.get("date") or req.args.get("date")
    slot_val = req.form.get("slot") or req.args.get("slot")

    today = date.today().isoformat()

    # अगर date नसली किंवा जुनी असेल → आजची date
    if not date_val or date_val < today:
        date_val = today

    # slot validation
    if slot_val not in ("morning", "evening"):
        slot_val = _auto_slot()

    return date_val, slot_val

# ------------------------------
# Milk Collection (with improved logic)
# ------------------------------

@app.route('/milk_collection', methods=['GET', 'POST'])
def milk_collection():

    vendors = get_vendors_cached(session['id'])

    # GET / POST मधून date आणि slot घ्या
    today_date, current_slot = _get_date_slot_from_request(request)

    if request.method == 'POST' and 'set_date_slot' in request.form:

        date_val = request.form.get('date') or date.today().isoformat()
        slot_val = request.form.get('slot')

        if slot_val not in ("morning", "evening"):
            slot_val = _auto_slot()

        return redirect(url_for(
            'milk_collection',
            date=date_val,
            slot=slot_val
        ))

    return render_template(
        'milk_operations/milk_collection.html',
        vendors=vendors,
        today_date=today_date,
        current_slot=current_slot,
        selected_date=today_date,
        selected_slot=current_slot
    )

@app.route('/submit_milk_ajax', methods=['POST'])
def submit_milk_ajax():

    ensure_user_id_int()

    data = request.get_json(silent=True) or {}

    vendor_id = data.get('vendor_id')
    milk_type = data.get('milk_type')
    quantity = data.get('quantity')
    force_save = data.get('force_save', False)

    date_val, slot_val = _get_date_slot_from_request(request)

    if data.get('date'):
        date_val = data.get('date')

    if data.get('slot'):
        slot_val = data.get('slot')

    if not vendor_id or quantity is None:
        return jsonify({"message": "Missing vendor_id or quantity"}), 400

    try:
        qty = float(quantity)
    except:
        return jsonify({"message": "Invalid quantity"}), 400

    cursor = SafeCursor(mysql.connection.cursor())

    # ===============================
    # Vendor ownership + phone
    # ===============================
    cursor.execute(
        "SELECT phone FROM vendors WHERE vendor_id = %s AND user_id = %s",
        (vendor_id, session['id'])
    )

    vendor = cursor.fetchone()

    if not vendor:
        return jsonify({"message": "Unauthorized vendor."}), 403

    # ===============================
    # Duplicate prevention
    # ===============================
    cursor.execute("""
        SELECT id FROM milk_collection
        WHERE vendor_id=%s AND user_id=%s AND date=%s AND slot=%s AND milk_type=%s
    """, (vendor_id, session['id'], date_val, slot_val, milk_type))

    if cursor.fetchone():
        return jsonify({
            "message": "Data already exists for this vendor/date/slot/milk_type."
        }), 409

    # ===============================
    # AI Anomaly Detection
    # ===============================
    try:
        cursor.execute("""
            SELECT quantity
            FROM milk_collection
            WHERE vendor_id=%s AND user_id=%s
            ORDER BY date DESC
            LIMIT 20
        """, (vendor_id, session['id']))

        rows = cursor.fetchall()
        previous_values = [r['quantity'] for r in rows]

        if detect_anomaly(previous_values, qty) and not force_save:
            return jsonify({
                "warning": "असामान्य दूध प्रमाण आढळले. कृपया तपासा."
            })

    except Exception:
        logging.exception("AI anomaly detection failed")

    # ===============================
    # Insert milk entry
    # ===============================
    try:

        staff_id = session.get("staff_id")  # staff login असेल तर id येईल

        cursor.execute("""
            INSERT INTO milk_collection
            (vendor_id, user_id, staff_id, date, slot, milk_type, quantity)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            vendor_id,
            session['id'],
            staff_id,
            date_val,
            slot_val,
            milk_type,
            qty
        ))

        mysql.connection.commit()

        # Audit log
        audit_log(
            session['id'],
            'insert_milk',
            f"{vendor_id} {date_val} {slot_val} {milk_type} {qty}"
        )

        # ===============================
        # Send SMS to vendor
        # ===============================
        if vendor and vendor.get("phone"):

            slot_map = {
                "morning": "सकाळ",
                "evening": "संध्याकाळ"
            }

            milk_map = {
                "cow": "गाय",
                "buffalo": "म्हैस"
            }

            slot_marathi = slot_map.get(slot_val.lower(), slot_val)
            milk_marathi = milk_map.get(milk_type.lower(), milk_type)

            message = f"{date_val} रोजी तुमचे {milk_marathi}चे {slot_marathi}चे {qty} लिटर दूध जमा झाले."

            send_sms(vendor["phone"], message)

        return jsonify({
            "message": f"Saved for {vendor_id} ({milk_type})"
        }), 200

    except Exception:
        logging.exception("Error inserting milk_collection")
        return jsonify({
            "message": "Server error saving data."
        }), 500


@app.route('/submit_bulk_milk_ajax', methods=['POST'])
def submit_bulk_milk_ajax():
    """
    Expects JSON: { vendors: [{vendor_id, milk_type, quantity, date, slot}, ...], date?, slot? }
    Returns structured JSON: { saved: [...], skipped: [{vendor_id, reason}], message: "..."}
    """
    ensure_user_id_int()
    payload = request.get_json(silent=True) or {}
    vendors_list = payload.get('vendors') or []
    date_default, slot_default = _get_date_slot_from_request(request)
    date_default = payload.get('date') or date_default
    slot_default = payload.get('slot') or slot_default

    if not vendors_list:
        return jsonify({"message": "No vendor data provided."}), 400

    saved = []
    skipped = []

    cursor = SafeCursor(mysql.connection.cursor())
    for item in vendors_list:
        vendor_id = item.get('vendor_id')
        milk_type = item.get('milk_type')
        quantity = item.get('quantity')
        date_val = item.get('date') or date_default
        slot_val = item.get('slot') or slot_default

        if not vendor_id or quantity is None:
            skipped.append({"vendor_id": vendor_id or "unknown", "reason": "missing fields"})
            continue
        try:
            qty = float(quantity)
        except:
            skipped.append({"vendor_id": vendor_id, "reason": "invalid quantity"})
            continue

        # ownership
        cursor.execute("SELECT 1 FROM vendors WHERE vendor_id = %s AND user_id = %s", (vendor_id, session['id']))
        if not cursor.fetchone():
            skipped.append({"vendor_id": vendor_id, "reason": "unauthorized vendor"})
            continue

        # duplicate?
        cursor.execute("""
            SELECT id FROM milk_collection
            WHERE vendor_id=%s AND user_id=%s AND date=%s AND slot=%s AND milk_type=%s
        """, (vendor_id, session['id'], date_val, slot_val, milk_type))
        if cursor.fetchone():
            skipped.append({"vendor_id": vendor_id, "reason": "already exists"})
            continue

        # insert
        try:
           
            staff_id = session.get("staff_id")

            cursor.execute("""
            INSERT INTO milk_collection
            (vendor_id, user_id, staff_id, date, slot, milk_type, quantity)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
            vendor_id,
            session['id'],
            staff_id,
            date_val,
            slot_val,
            milk_type,
            qty
            ))
            saved.append({"vendor_id": vendor_id, "date": date_val, "slot": slot_val, "milk_type": milk_type, "quantity": qty})

            # send sms (non-blocking)
            pc = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            pc.execute("SELECT phone FROM vendors WHERE vendor_id = %s AND user_id = %s", (vendor_id, session['id']))
            v = pc.fetchone()
            if v and v.get('phone'):
                slot_map = {"morning": "सकाळ", "evening": "संध्याकाळ"}
                milk_map = {"cow": "गाय", "buffalo": "म्हैस"}

                slot_marathi = slot_map.get(slot_val.lower(), slot_val)
                milk_marathi = milk_map.get(milk_type.lower(), milk_type)

                message = f"{date_val} रोजी तुमचे {milk_marathi}चे {slot_marathi}चे {qty} लिटर दूध जमा झाले."
                send_sms(v['phone'], message)

        except Exception:
            logging.exception("Error on bulk insert")
            skipped.append({"vendor_id": vendor_id, "reason": "server error"})
            continue

    mysql.connection.commit()
    audit_log(session['id'], 'bulk_insert_milk', f"saved={len(saved)} skipped={len(skipped)}")
    result = {"saved": saved, "skipped": skipped, "message": f"Saved {len(saved)} entries; skipped {len(skipped)} entries."}
    status = 207 if skipped else 200
    return jsonify(result), status




# ------------------------------
# Advance (safe add/update)
# ------------------------------
@app.route('/advance', methods=['GET', 'POST'])
def advance():
    cursor = SafeCursor(mysql.connection.cursor())
    cursor.execute("""
SELECT * FROM vendors
WHERE user_id = %s
ORDER BY vendor_id ASC
""", (session['id'],))
    vendors = cursor.fetchall()

    if request.method == 'POST':
        # Support both JSON and form POST
        if request.is_json:
            data = request.get_json(silent=True) or {}
            entry_date = data.get('date') or date.today().isoformat()
        else:
            data = request.form
            entry_date = request.form.get('date') or date.today().isoformat()

        for v in vendors:
            vid = v['vendor_id']
            # For JSON payload, the key will match "advance_<vendor_id>"
            amount = data.get(f'advance_{vid}')
            if not amount:
                continue
            try:
                amt = float(amount)
            except:
                continue

            # check existing
            cursor.execute(
                "SELECT id, amount FROM advance WHERE vendor_id=%s AND user_id=%s AND date=%s",
                (vid, session['id'], entry_date)
            )
            existing = cursor.fetchone()
            if existing:
                # update to new total (keep behavior: add amount)
                new_amt = float(existing['amount']) + amt
                cursor.execute("UPDATE advance SET amount=%s WHERE id=%s", (new_amt, existing['id']))
            else:
                cursor.execute(
                    "INSERT INTO advance (vendor_id, user_id, date, amount) VALUES (%s,%s,%s,%s)",
                    (vid, session['id'], entry_date, amt)
                )

        mysql.connection.commit()
        audit_log(session['id'], 'advance_update', f"date={entry_date}")

        # Return JSON if AJAX request
        if request.is_json:
            return jsonify({"success": True, "message": "Advance saved successfully."}), 200
        else:
            flash('Advance saved.', 'success')
            return redirect(url_for('advance'))

    return render_template('milk_operations/advance.html',
                           vendors=vendors,
                           today_date=date.today().isoformat())


# ------------------------------
# Food Sack (safe grouping & update)
# ------------------------------
@app.route('/food_sack', methods=['GET', 'POST'])
def food_sack():
    cursor = SafeCursor(mysql.connection.cursor())
    cursor.execute("""
SELECT * FROM vendors
WHERE user_id = %s
ORDER BY vendor_id ASC
""", (session['id'],))
    vendors = cursor.fetchall()
    cursor.execute("""
SELECT *
FROM food_sack_rates
WHERE user_id = %s
AND is_active = 1
ORDER BY name
""", (session['id'],))
    sack_rates = cursor.fetchall()
    if request.method == 'POST':
        entry_date = request.form.get('date') or date.today().isoformat()
        for v in vendors:
            vid = v['vendor_id']
            qty = request.form.get(f'sack_qty_{vid}')
            sack_id = request.form.get(f'sack_type_{vid}')
            if not qty or not sack_id:
                continue
            try:
                qty_i = int(qty)
                sack_id_i = int(sack_id)
            except:
                continue
            cursor.execute("SELECT rate FROM food_sack_rates WHERE id=%s AND user_id=%s", (sack_id_i, session['id']))
            res = cursor.fetchone()
            if not res:
                continue
            rate = float(res['rate'])
            total = qty_i * rate
            # Check existing entry for same vendor/date/rate
            cursor.execute("""
                SELECT id, sack_qty, total_cost FROM food_sack
                WHERE vendor_id=%s AND user_id=%s AND date=%s AND sack_rate_id=%s
            """, (vid, session['id'], entry_date, sack_id_i))
            existing = cursor.fetchone()
            if existing:
                new_qty = int(existing['sack_qty']) + qty_i
                new_total = float(existing['total_cost']) + total
                cursor.execute("UPDATE food_sack SET sack_qty=%s, total_cost=%s, sack_rate_id=%s WHERE id=%s",
                               (new_qty, new_total, sack_id_i, existing['id']))
            else:
                cursor.execute("INSERT INTO food_sack (vendor_id, user_id, date, sack_qty, sack_rate_id, sack_rate, total_cost) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                               (vid, session['id'], entry_date, qty_i, sack_id_i, rate, total))
        mysql.connection.commit()
        audit_log(session['id'], 'food_sack_update', f"date={entry_date}")
        flash('Food sack data saved.', 'success')
        return redirect(url_for('food_sack'))
    return render_template('milk_operations/food_sack.html', vendors=vendors, sack_rates=sack_rates, today_date=date.today().isoformat())


@app.route('/add_food_sack', methods=['POST'])
def add_food_sack():
    if 'id' not in session:
        return redirect(url_for('login'))
    name = request.form.get('name')
    rate = request.form.get('rate')
    date_from = datetime.today().date()
    try:
        cursor = SafeCursor(mysql.connection.cursor())
        cursor.execute("INSERT INTO food_sack_rates (user_id, name, rate, date_from) VALUES (%s,%s,%s,%s)",
                       (session['id'], name, rate, date_from))
        mysql.connection.commit()
        audit_log(session['id'], 'add_food_sack_rate', f"{name} {rate}")
        flash('Food sack rate added.', 'success')
    except Exception:
        logging.exception("Error adding food_sack_rate")
        flash('Error adding rate.', 'danger')
    return redirect(url_for('food_sack_rate'))


@app.route('/food_sack_rate', methods=['GET', 'POST'])
def food_sack_rate():

    if 'id' not in session:
        return redirect(url_for('login'))

    cursor = SafeCursor(mysql.connection.cursor())

    if request.method == 'POST':

        name = request.form.get('name')
        rate = request.form.get('rate')
        date_from = datetime.today().date()

        cursor.execute("""
        INSERT INTO food_sack_rates
        (user_id,name,rate,date_from)
        VALUES(%s,%s,%s,%s)
        """,(session['id'],name,rate,date_from))

        mysql.connection.commit()

        audit_log(session['id'], 'add_food_sack_rate', f"{name} {rate}")

        flash('Added.', 'success')

        return redirect(url_for('food_sack_rate'))

    # ⚡ optimized select
    cursor.execute("""
    SELECT id,name,rate,date_from
    FROM food_sack_rates
    WHERE user_id=%s
    AND is_active=1
    ORDER BY name
    """,(session['id'],))

    rates = cursor.fetchall()

    cursor.close()

    return render_template(
        'rates/food_sack_rate.html',
        food_sacks=rates
    )
    
    
@app.route('/update_food_sack_rate', methods=['POST'])
def update_food_sack_rate():

    if 'id' not in session:
        return redirect(url_for('login'))

    sack_id = request.form.get('sack_id')
    new_rate = request.form.get('new_rate')
    date_from = request.form.get('date_from')

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
    SELECT name
    FROM food_sack_rates
    WHERE id=%s
    AND user_id=%s
    LIMIT 1
    """,(sack_id,session['id']))

    sack = cursor.fetchone()

    if not sack:
        flash("Invalid sack.", "danger")
        return redirect(url_for('food_sack_rate'))

    name = sack['name']

    # ⚡ insert new rate (history safe)
    cursor.execute("""
    INSERT INTO food_sack_rates
    (user_id,name,rate,date_from)
    VALUES(%s,%s,%s,%s)
    """,(session['id'],name,new_rate,date_from))

    mysql.connection.commit()

    audit_log(session['id'], 'update_food_sack_rate', f"name={name} rate={new_rate}")

    flash("New rate applied.", "success")

    return redirect(url_for('food_sack_rate'))

@app.route('/delete_food_sack_rate/<int:sack_id>', methods=['POST'])
def delete_food_sack_rate(sack_id):

    if 'id' not in session:
        return redirect(url_for('login'))

    cursor = SafeCursor(mysql.connection.cursor())

    # check if sack exists
    cursor.execute("""
        SELECT id
        FROM food_sack_rates
        WHERE id=%s AND user_id=%s
    """, (sack_id, session['id']))

    sack = cursor.fetchone()

    if not sack:
        flash("खाद्य पोती दर सापडला नाही.", "danger")
        return redirect(url_for('food_sack_rate'))

    # SOFT DELETE
    cursor.execute("""
        UPDATE food_sack_rates
        SET is_active = 0
        WHERE id=%s AND user_id=%s
    """, (sack_id, session['id']))

    mysql.connection.commit()

    audit_log(session['id'], 'delete_food_sack_rate', f"id={sack_id}")

    flash('खाद्य पोती दर काढण्यात आला.', 'success')

    return redirect(url_for('food_sack_rate'))
# ------------------------------
# Edit Entry & safer update_entries
# ------------------------------

@app.route('/edit_entry', methods=['GET','POST'])
def edit_entry():

    if "id" not in session:
        flash("Please login first.", "danger")
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
        SELECT vendor_id,name,milk_type
        FROM vendors
        WHERE user_id=%s
        ORDER BY vendor_id ASC
    """,(session['id'],))

    vendors = cursor.fetchall()

    data=[]
    selected_vendor_type=None

    vendor_id=request.args.get("vendor_id")
    from_date=request.args.get("from_date")
    to_date=request.args.get("to_date")

    if vendor_id and from_date and to_date:

        cursor.execute("""
            SELECT milk_type
            FROM vendors
            WHERE vendor_id=%s AND user_id=%s
        """,(vendor_id,session['id']))

        vendor_info=cursor.fetchone()

        if not vendor_info:
            flash("Unauthorized vendor.","danger")
            return redirect(url_for("edit_entry"))

        selected_vendor_type=vendor_info["milk_type"]

        # 🔹 LOAD ALL MILK DATA (1 query)
        cursor.execute("""
            SELECT date,slot,milk_type,quantity
            FROM milk_collection
            WHERE vendor_id=%s
            AND user_id=%s
            AND date BETWEEN %s AND %s
        """,(vendor_id,session['id'],from_date,to_date))

        milk_rows=cursor.fetchall()

        milk_map={}
        for r in milk_rows:
            d=r['date'].strftime("%Y-%m-%d")
            key=(d,r['slot'],r['milk_type'])
            milk_map[key]=r['quantity']

        # 🔹 LOAD ADVANCE DATA (1 query)
        cursor.execute("""
            SELECT date,amount
            FROM advance
            WHERE vendor_id=%s
            AND user_id=%s
            AND date BETWEEN %s AND %s
        """,(vendor_id,session['id'],from_date,to_date))

        adv_rows=cursor.fetchall()

        advance_map={}
        for a in adv_rows:
            d=a['date'].strftime("%Y-%m-%d")
            advance_map[d]=a['amount']

        start=datetime.strptime(from_date,"%Y-%m-%d")
        end=datetime.strptime(to_date,"%Y-%m-%d")

        d=start

        while d<=end:

            ds=d.strftime("%Y-%m-%d")

            rec={
                "date":ds,
                "cow_morning":milk_map.get((ds,"morning","cow"),0),
                "cow_evening":milk_map.get((ds,"evening","cow"),0),
                "buffalo_morning":milk_map.get((ds,"morning","buffalo"),0),
                "buffalo_evening":milk_map.get((ds,"evening","buffalo"),0),
                "advance_amt":advance_map.get(ds,0)
            }

            data.append(rec)

            d+=timedelta(days=1)

    return render_template(
        "milk_operations/edit_entry.html",
        vendors=vendors,
        data=data,
        selected_vendor_type=selected_vendor_type
    )


    
@app.route('/update_entries', methods=['POST'])
def update_entries():

    if "id" not in session:
        flash("Please login first.", "danger")
        return redirect(url_for("login"))

    vendor_id = request.form.get("vendor_id")
    from_date = request.form.get("from_date")
    to_date = request.form.get("to_date")

    cursor = SafeCursor(mysql.connection.cursor())

    # Ownership + milk_type
    cursor.execute("""
        SELECT milk_type
        FROM vendors
        WHERE vendor_id=%s AND user_id=%s
    """, (vendor_id, session['id']))
    vendor_info = cursor.fetchone()

    if not vendor_info:
        flash("Unauthorized vendor.", "danger")
        return redirect(url_for("edit_entry"))

    vendor_type = vendor_info["milk_type"]

    # Allowed milk types
    if vendor_type == "cow":
        allowed_types = ["cow"]
    elif vendor_type == "buffalo":
        allowed_types = ["buffalo"]
    else:
        allowed_types = ["cow", "buffalo"]

    # Load existing milk entries
    cursor.execute("""
        SELECT id, date, slot, milk_type, quantity
        FROM milk_collection
        WHERE vendor_id=%s AND user_id=%s
        AND date BETWEEN %s AND %s
    """, (vendor_id, session['id'], from_date, to_date))

    existing = cursor.fetchall() or {}
    existing_map = {}

    for r in existing:
        dstr = r['date'].strftime("%Y-%m-%d")
        existing_map[(dstr, r['slot'], r['milk_type'])] = {
            'id': r['id'],
            'quantity': float(r['quantity'])
        }

    # Advances
    cursor.execute("""
        SELECT id, date, amount
        FROM advance
        WHERE vendor_id=%s AND user_id=%s
        AND date BETWEEN %s AND %s
    """, (vendor_id, session['id'], from_date, to_date))

    advs = cursor.fetchall() or {}
    adv_map = {}

    for a in advs:
        dstr = a['date'].strftime("%Y-%m-%d")
        adv_map[dstr] = {
            'id': a['id'],
            'amount': float(a['amount'])
        }

    cur_date = datetime.strptime(from_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(to_date, "%Y-%m-%d").date()

    while cur_date <= end_date:
        ds = cur_date.strftime("%Y-%m-%d")

        for milk_type in allowed_types:
            for slot in ('morning', 'evening'):

                field_name = f"{milk_type}_{slot}_{ds}"
                qty = float(request.form.get(field_name) or 0)

                key = (ds, slot, milk_type)
                existing_row = existing_map.get(key)

                if qty > 0:
                    if existing_row:
                        if abs(existing_row['quantity'] - qty) > 1e-9:
                            cursor.execute(
                                "UPDATE milk_collection SET quantity=%s WHERE id=%s",
                                (qty, existing_row['id'])
                            )
                    else:
                        cursor.execute("""
                            INSERT INTO milk_collection
                            (vendor_id, user_id, date, slot, milk_type, quantity)
                            VALUES (%s,%s,%s,%s,%s,%s)
                        """, (vendor_id, session['id'], ds, slot, milk_type, qty))
                else:
                    if existing_row:
                        cursor.execute(
                            "DELETE FROM milk_collection WHERE id=%s",
                            (existing_row['id'],)
                        )

        # Advance
        adv_field = f"advance_{ds}"
        adv_amt = float(request.form.get(adv_field) or 0)
        existing_adv = adv_map.get(ds)

        if adv_amt > 0:
            if existing_adv:
                if abs(existing_adv['amount'] - adv_amt) > 1e-9:
                    cursor.execute(
                        "UPDATE advance SET amount=%s WHERE id=%s",
                        (adv_amt, existing_adv['id'])
                    )
            else:
                cursor.execute("""
                    INSERT INTO advance (vendor_id, user_id, date, amount)
                    VALUES (%s,%s,%s,%s)
                """, (vendor_id, session['id'], ds, adv_amt))
        else:
            if existing_adv:
                cursor.execute(
                    "DELETE FROM advance WHERE id=%s",
                    (existing_adv['id'],)
                )

        cur_date += timedelta(days=1)

    mysql.connection.commit()
    flash("Entries updated successfully.", "success")
    return redirect(url_for(
    "edit_entry",
    vendor_id=vendor_id,
    from_date=from_date,
    to_date=to_date
))

@app.route('/delete_entry', methods=['POST'])
def delete_entry():

    if "id" not in session:
        flash("Please login first.", "danger")
        return redirect(url_for("login"))

    vendor_id = request.form.get('vendor_id')
    date_str = request.form.get('date')
    confirm = request.form.get('confirm')

    if str(confirm) != '1':
        flash("Please confirm deletion.", "warning")
        return redirect(url_for('edit_entry'))

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
        SELECT 1 FROM vendors
        WHERE vendor_id=%s AND user_id=%s
    """, (vendor_id, session['id']))

    if not cursor.fetchone():
        flash("Unauthorized to delete.", "danger")
        return redirect(url_for('edit_entry'))

    try:
        cursor.execute("DELETE FROM milk_collection WHERE vendor_id=%s AND user_id=%s AND date=%s",
                       (vendor_id, session['id'], date_str))
        cursor.execute("DELETE FROM advance WHERE vendor_id=%s AND user_id=%s AND date=%s",
                       (vendor_id, session['id'], date_str))
        cursor.execute("DELETE FROM food_sack WHERE vendor_id=%s AND user_id=%s AND date=%s",
                       (vendor_id, session['id'], date_str))

        mysql.connection.commit()
        flash("Entry deleted successfully.", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash("Error deleting entry.", "danger")

    return redirect(url_for(
    "edit_entry",
    vendor_id=vendor_id,
    from_date=request.form.get("from_date"),
    to_date=request.form.get("to_date")
))
# ------------------------------
# Receipts, calculation, payment (kept logic but with small safety)
# ------------------------------
@app.route('/calculation', methods=['GET', 'POST'])
def calculation():

    if 'id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('login'))

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
        SELECT *
        FROM vendors
        WHERE user_id=%s
        ORDER BY vendor_id ASC
    """,(session['id'],))

    vendors = cursor.fetchall()

    results=None

    if request.method=='POST':

        vendor_id = request.form.get('vendor_id')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')

        cursor.execute("""
            SELECT date,slot,milk_type,quantity
            FROM milk_collection
            WHERE vendor_id=%s AND user_id=%s
            AND date BETWEEN %s AND %s
        """,(vendor_id,session['id'],start_date,end_date))

        milk_data = cursor.fetchall()

        mcq=ecq=mbq=ebq=0
        mcp=ecp=mbp=ebp=0

        for row in milk_data:

            rate = get_vendor_rate(cursor, vendor_id, row['milk_type'], row['date'])

            amt = float(row['quantity']) * rate

            if row['milk_type']=="cow":

                if row['slot']=="morning":
                    mcq+=row['quantity']; mcp+=amt
                else:
                    ecq+=row['quantity']; ecp+=amt

            else:

                if row['slot']=="morning":
                    mbq+=row['quantity']; mbp+=amt
                else:
                    ebq+=row['quantity']; ebp+=amt

        cursor.execute("""
            SELECT SUM(amount) total
            FROM advance
            WHERE vendor_id=%s AND user_id=%s
            AND date BETWEEN %s AND %s
        """,(vendor_id,session['id'],start_date,end_date))

        total_advance = cursor.fetchone()['total'] or 0

        cursor.execute("""
            SELECT SUM(total_cost) total
            FROM food_sack
            WHERE vendor_id=%s AND user_id=%s
            AND date BETWEEN %s AND %s
        """,(vendor_id,session['id'],start_date,end_date))

        total_food = cursor.fetchone()['total'] or 0

        milk_total = mcp+ecp+mbp+ebp
        final_payment = milk_total-(total_advance+total_food)

        results={

            'morning_cow_quantity':mcq,
            'evening_cow_quantity':ecq,
            'morning_cow_payment':mcp,
            'evening_cow_payment':ecp,
            'total_cow_quantity':mcq+ecq,
            'total_cow_payment':mcp+ecp,

            'morning_buffalo_quantity':mbq,
            'evening_buffalo_quantity':ebq,
            'morning_buffalo_payment':mbp,
            'evening_buffalo_payment':ebp,
            'total_buffalo_quantity':mbq+ebq,
            'total_buffalo_payment':mbp+ebp,

            'total_milk_quantity':mcq+ecq+mbq+ebq,
            'milk_total':milk_total,
            'total_food_sack_cost':total_food,
            'total_advance':total_advance,
            'final_payable_amount':final_payment

        }

    return render_template(
        'milk_operations/calculation.html',
        vendors=vendors,
        results=results
    )
    
    
@app.route('/payment', methods=['GET', 'POST'])
def payment():

    if 'id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('login'))

    # POST → redirect
    if request.method == 'POST':

        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')

        return redirect(url_for(
            'payment',
            start_date=start_date,
            end_date=end_date
        ))

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    cursor = SafeCursor(mysql.connection.cursor())

    data = []

    if start_date and end_date:

        # load vendors
        cursor.execute("""
            SELECT vendor_id,name
            FROM vendors
            WHERE user_id=%s
            ORDER BY vendor_id ASC
        """,(session['id'],))

        vendors = cursor.fetchall()

        for v in vendors:

            vendor_id = v['vendor_id']

            # milk entries
            cursor.execute("""
                SELECT date,milk_type,SUM(quantity) qty
                FROM milk_collection
                WHERE vendor_id=%s
                AND user_id=%s
                AND date BETWEEN %s AND %s
                GROUP BY date,milk_type
            """,(vendor_id,session['id'],start_date,end_date))

            milk_entries = cursor.fetchall()

            total_cow = 0
            total_buffalo = 0

            cow_cost = 0
            buffalo_cost = 0

            for m in milk_entries:

                rate = get_vendor_rate(
                    cursor,
                    vendor_id,
                    m['milk_type'],
                    m['date']
                )

                qty = float(m['qty'])

                if m['milk_type'] == "cow":

                    total_cow += qty
                    cow_cost += qty * rate

                else:

                    total_buffalo += qty
                    buffalo_cost += qty * rate

            # advance
            cursor.execute("""
                SELECT SUM(amount) AS total_advance
                FROM advance
                WHERE vendor_id=%s
                AND user_id=%s
                AND date BETWEEN %s AND %s
            """,(vendor_id,session['id'],start_date,end_date))

            adv = cursor.fetchone()['total_advance'] or 0


            # food sack
            cursor.execute("""
                SELECT SUM(total_cost) AS total_food
                FROM food_sack
                WHERE vendor_id=%s
                AND user_id=%s
                AND date BETWEEN %s AND %s
            """,(vendor_id,session['id'],start_date,end_date))

            food = cursor.fetchone()['total_food'] or 0


            total_milk_payment = round(cow_cost + buffalo_cost, 2)

            total_payment = round(
                total_milk_payment - adv - food,
                2
            )

            data.append({

                'vendor_id': vendor_id,
                'vendor_name': v['name'],

                'total_cow': total_cow,
                'total_buffalo': total_buffalo,

                'cow_rate': "-",
                'buffalo_rate': "-",

                'total_milk_payment': total_milk_payment,

                'total_advance': adv,
                'total_food': food,

                'total_payment': total_payment
            })

    cursor.close()

    return render_template(
        'milk_operations/payment.html',
        data=data
    )
    
    
@app.route('/receipt_all_vendors', methods=['GET', 'POST'])
def receipt_all_vendors():

    if 'id' not in session:
        return redirect(url_for('login'))

    user_id = int(session['id'])
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':

        from_date = request.form.get('from_date')
        to_date = request.form.get('to_date')

        # -------------------------
        # LOAD VENDORS
        # -------------------------
        cursor.execute("""
            SELECT vendor_id, name, milk_type, address
            FROM vendors
            WHERE user_id=%s
            ORDER BY vendor_id
        """, (user_id,))
        vendors = cursor.fetchall()

        # -------------------------
        # LOAD MILK DATA
        # -------------------------
        cursor.execute("""
            SELECT vendor_id, date, slot, milk_type, quantity
            FROM milk_collection
            WHERE user_id=%s
            AND date BETWEEN %s AND %s
        """, (user_id, from_date, to_date))

        milk_rows = cursor.fetchall()

        milk_map = {}
        for r in milk_rows:
            vid = int(r['vendor_id'])
            milk_map.setdefault(vid, []).append(r)

        # -------------------------
        # LOAD FOOD SACK
        # -------------------------
            cursor.execute("""
            SELECT
                fs.vendor_id,
                fs.sack_qty,
                r.name,
                COALESCE(fs.sack_rate,0) AS rate,
                COALESCE(fs.total_cost,0) AS total
            FROM food_sack fs
            JOIN food_sack_rates r
            ON r.id = fs.sack_rate_id
            WHERE fs.user_id=%s
            AND fs.date BETWEEN %s AND %s
            ORDER BY fs.vendor_id
            """,(user_id,from_date,to_date))

        food_rows = cursor.fetchall()

        food_map = {}
        for f in food_rows:
            vid = int(f['vendor_id'])
            food_map.setdefault(vid, []).append(f)

        # -------------------------
        # LOAD ADVANCE
        # -------------------------
        cursor.execute("""
            SELECT vendor_id, SUM(amount) total
            FROM advance
            WHERE user_id=%s
            AND date BETWEEN %s AND %s
            GROUP BY vendor_id
        """, (user_id, from_date, to_date))

        adv_map = {
            int(a['vendor_id']): float(a['total'] or 0)
            for a in cursor.fetchall()
        }

        # -------------------------
        # PROCESS VENDORS
        # -------------------------
        all_receipts = []

        for vendor in vendors:

            vid = int(vendor['vendor_id'])

            # ⭐ vendor special rate (only once)
            cow_rate = get_vendor_rate(cursor, vid, "cow", from_date)
            buffalo_rate = get_vendor_rate(cursor, vid, "buffalo", from_date)

            milk_data = milk_map.get(vid, [])

            grouped = {}

            totals = {
                'cow_morning': 0,
                'cow_evening': 0,
                'buffalo_morning': 0,
                'buffalo_evening': 0
            }

            cow_cost = 0
            buffalo_cost = 0

            for row in milk_data:

                dt = row['date'].strftime("%Y-%m-%d")
                slot = row['slot']
                mtype = row['milk_type']
                qty = float(row['quantity'])

                rate = cow_rate if mtype == "cow" else buffalo_rate

                if dt not in grouped:
                    grouped[dt] = {
                        'day': row['date'].strftime("%d"),
                        'cow_morning': 0,
                        'cow_evening': 0,
                        'buffalo_morning': 0,
                        'buffalo_evening': 0
                    }

                grouped[dt][f"{mtype}_{slot}"] += qty
                totals[f"{mtype}_{slot}"] += qty

                if mtype == "cow":
                    cow_cost += qty * rate
                else:
                    buffalo_cost += qty * rate

            entries = list(grouped.values())

            food_data = food_map.get(vid, [])
            food_total = sum(float(f['total']) for f in food_data)

            food_sack_details = [
                {
                    "name": f['name'],
                    "rate": float(f['rate'] or 0),
                    "qty": int(f['sack_qty'] or 0),
                    "total": float(f['total'] or 0)
                }
                for f in food_data
            ]

            advance = float(adv_map.get(vid, 0))

            final_payable = round(
                (cow_cost + buffalo_cost) - (advance + food_total),
                2
            )

            all_receipts.append({

                'vendor_id': vid,
                'name': vendor['name'],
                'address': vendor['address'],
                'milk_type': vendor['milk_type'],

                'data': entries,

                'total_cow': totals['cow_morning'] + totals['cow_evening'],
                'total_buffalo': totals['buffalo_morning'] + totals['buffalo_evening'],

                'cow_cost': round(cow_cost, 2),
                'buffalo_cost': round(buffalo_cost, 2),

                'food_sack_details': food_sack_details,
                'food_cost': food_total,

                'advance': advance,
                'final_payable': final_payable,

                'total_cow_morning': totals['cow_morning'],
                'total_cow_evening': totals['cow_evening'],

                'total_buffalo_morning': totals['buffalo_morning'],
                'total_buffalo_evening': totals['buffalo_evening'],

                'cow_rate': cow_rate,
                'buffalo_rate': buffalo_rate
            })

        cursor.close()

        return render_template(
            'receipt_all_vendors.html',
            receipts=all_receipts
        )

    cursor.close()

    return render_template(
        'receipt_all_vendors.html',
        receipts=None
    )
# ------------------------------
# Edit food sack & delete
# ------------------------------
@app.route("/edit_food_sack", methods=["GET", "POST"])
def edit_food_sack():
    if "id" not in session:
        flash("Please login first.", "danger")
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())
    cursor.execute(
        "SELECT vendor_id, name FROM vendors WHERE user_id = %s ORDER BY name ASC",
        (session['id'],)
    )
    vendors = cursor.fetchall()

    sacks = []
    selected_vendor_id = None
    if request.method == "POST":
        selected_vendor_id = request.form.get("vendor_id")
        cursor.execute("""
            SELECT fs.id, fs.date, r.name AS company_name, fs.sack_qty, r.rate, (fs.sack_qty * fs.sack_rate) AS total
            FROM food_sack fs
            JOIN food_sack_rates r ON fs.sack_rate_id = r.id
            WHERE fs.vendor_id=%s AND fs.user_id=%s
            ORDER BY fs.date DESC
        """, (selected_vendor_id, session['id']))
        sacks = cursor.fetchall()

    return render_template(
        "milk_operations/edit_food_sack.html",
        vendors=vendors,
        sacks=sacks,
        selected_vendor_id=selected_vendor_id
    )


@app.route("/delete_food_sack/<int:sack_id>", methods=["POST"])
def delete_food_sack(sack_id):
    if 'id' not in session:
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"success": False, "message": "Please login first."}), 401
        flash('Please login first.', 'danger')
        return redirect(url_for('login'))

    confirm = request.form.get('confirm') or request.args.get('confirm')
    if confirm != '1':
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"success": False, "message": "Please confirm deletion."}), 400
        flash('Please confirm deletion.', 'warning')
        return redirect(url_for('edit_food_sack'))

    try:
        cursor = SafeCursor(mysql.connection.cursor())
        cursor.execute(
            "DELETE FROM food_sack WHERE id = %s AND user_id = %s",
            (sack_id, session['id'])
        )
        mysql.connection.commit()

        audit_log(session['id'], 'delete_food_sack', f"id={sack_id}")

        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"success": True, "message": "Food sack entry deleted."}), 200

        flash('Food sack entry deleted.', 'success')
        return redirect(url_for('edit_food_sack'))

    except Exception as e:
        logging.exception("Error deleting food sack")
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"success": False, "message": "Error deleting entry."}), 500
        flash('Error deleting food sack entry.', 'danger')
        return redirect(url_for('edit_food_sack'))



# ------------------------------
# Milk summary
# ------------------------------
@app.route('/milk_summary', methods=['GET', 'POST'])
def milk_summary():
    # 🔥 POST → REDIRECT (PRG)
    if request.method == 'POST':
        from_date = request.form.get('from_date')
        to_date = request.form.get('to_date')

        return redirect(url_for(
            'milk_summary',
            from_date=from_date,
            to_date=to_date
        ))

    # =========================
    # GET request (real work)
    # =========================
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')

    totals = {
        'cow_morning': 0,
        'cow_evening': 0,
        'buffalo_morning': 0,
        'buffalo_evening': 0
    }

    if from_date and to_date:
        cursor = SafeCursor(mysql.connection.cursor())
        cursor.execute("""
            SELECT milk_type, slot, SUM(quantity) AS total_qty
            FROM milk_collection
            WHERE user_id = %s AND date BETWEEN %s AND %s
            GROUP BY milk_type, slot
        """, (session['id'], from_date, to_date))

        for row in cursor.fetchall():
            key = f"{row['milk_type']}_{row['slot']}"
            if key in totals:
                totals[key] = row['total_qty'] or 0

        cursor.close()

    totals['cow_total'] = (totals['cow_morning'] or 0) + (totals['cow_evening'] or 0)
    totals['buffalo_total'] = (totals['buffalo_morning'] or 0) + (totals['buffalo_evening'] or 0)
    totals['grand_total'] = totals['cow_total'] + totals['buffalo_total']

    return render_template(
        "milk_operations/milk_summary.html",
        from_date=from_date,
        to_date=to_date,
        totals=totals
    )


# ------------------------------
# Vendor Range Summary Page
# ------------------------------
@app.route("/vendor_range_summary", methods=["GET", "POST"])
def vendor_range_summary():

    if "id" not in session:
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())

    # Load vendor list
    cursor.execute("""
        SELECT vendor_id, name 
        FROM vendors 
        WHERE user_id=%s 
        ORDER BY vendor_id ASC
    """, (session["id"],))
    vendors = cursor.fetchall()

    results = []
    from_date = None
    to_date = None

    # GRAND TOTAL VARIABLES
    grand_totals = {
        "cow_morning": 0,
        "cow_evening": 0,
        "buffalo_morning": 0,
        "buffalo_evening": 0,
        "cow_total": 0,
        "buffalo_total": 0
    }

    if request.method == "POST":

        from_date = request.form.get("from_date")
        to_date = request.form.get("to_date")
        selected_vendors = request.form.getlist("vendors")

        for vendor_id in selected_vendors:

            cursor.execute("""
                SELECT name FROM vendors
                WHERE vendor_id=%s AND user_id=%s
            """, (vendor_id, session["id"]))
            vendor = cursor.fetchone()
            if not vendor:
                continue

            cursor.execute("""
                SELECT milk_type, slot, SUM(quantity) as total_qty
                FROM milk_collection
                WHERE vendor_id=%s AND user_id=%s
                AND date BETWEEN %s AND %s
                GROUP BY milk_type, slot
            """, (vendor_id, session["id"], from_date, to_date))

            data = cursor.fetchall()

            summary = {
                "vendor_id": vendor_id,
                "name": vendor["name"],
                "cow_morning": 0,
                "cow_evening": 0,
                "buffalo_morning": 0,
                "buffalo_evening": 0
            }

            for row in data:
                key = f"{row['milk_type']}_{row['slot']}"
                summary[key] = round(row["total_qty"] or 0, 1)

            summary["cow_total"] = summary["cow_morning"] + summary["cow_evening"]
            summary["buffalo_total"] = summary["buffalo_morning"] + summary["buffalo_evening"]
            for k in grand_totals:
                grand_totals[k] = round(grand_totals[k], 1)
            # ADD INTO GRAND TOTALS
            grand_totals["cow_morning"] += summary["cow_morning"]
            grand_totals["cow_evening"] += summary["cow_evening"]
            grand_totals["buffalo_morning"] += summary["buffalo_morning"]
            grand_totals["buffalo_evening"] += summary["buffalo_evening"]
            grand_totals["cow_total"] += summary["cow_total"]
            grand_totals["buffalo_total"] += summary["buffalo_total"]

            results.append(summary)

    cursor.close()

    return render_template(
        "vendor_range_summary.html",
        vendors=vendors,
        results=results,
        from_date=from_date,
        to_date=to_date,
        grand_totals=grand_totals
    )

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}




# -------------------------------
# HEAD ROUTES
# -------------------------------
@app.route("/about", methods=["GET", "POST"])
def about():
    if request.method == "POST":
        name = request.form.get("name")
        email = session.get("email")   # ✅ login झाल्यामुळे session मधून email घ्या
        message = request.form.get("message")

        if not name or not message:
            flash("सर्व फील्ड भरा.", "warning")
            return redirect(url_for("about"))

        try:
            msg = EmailMessage()
            msg["Subject"] = f"New Feedback from {name}"
            msg["From"] = EMAIL_ADDRESS
            msg["To"] = "dairymitra.official@gmail.com"
            msg.set_content(f"Name: {name}\nEmail: {email}\n\nMessage:\n{message}")

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                smtp.send_message(msg)

            flash("Feedback पाठवला. धन्यवाद!", "success")
        except Exception as e:
            logging.exception("Feedback send error")
            flash("Feedback पाठवताना error आला.", "danger")

    return render_template("head/about.html")

@app.route("/milk_prediction")
def milk_prediction_page():

    if 'id' not in session:
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute(
        "SELECT id, name FROM vendors WHERE user_id=%s",
        (session['id'],)
    )

    vendors = cursor.fetchall()

    return render_template("ai/milk_prediction.html", vendors=vendors)


@app.route("/api/predict_milk/<int:vendor_id>")
def api_predict_milk(vendor_id):

    if 'id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
        SELECT date,
               SUM(CASE WHEN slot='morning' THEN quantity ELSE 0 END) AS morning,
               SUM(CASE WHEN slot='evening' THEN quantity ELSE 0 END) AS evening
        FROM milk_collection
        WHERE vendor_id=%s AND user_id=%s
        GROUP BY date
        ORDER BY date DESC
        LIMIT 30
    """, (vendor_id, session['id']))

    data = cursor.fetchall()

    if not data:
        return jsonify({
            "morning_prediction": None,
            "evening_prediction": None
        })

    df = pd.DataFrame(data)

    morning_df = df[["date","morning"]].rename(columns={"morning":"quantity"})
    evening_df = df[["date","evening"]].rename(columns={"evening":"quantity"})

    morning_prediction = predict_milk(morning_df)
    evening_prediction = predict_milk(evening_df)

    return jsonify({
        "morning_prediction": morning_prediction,
        "evening_prediction": evening_prediction
    })
    
    
@app.route("/vendor_performance")
def vendor_performance():

    if 'id' not in session:
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())

    cursor.execute("""
        SELECT vendor_id, quantity
        FROM milk_collection
        WHERE user_id=%s
    """, (session['id'],))

    data = cursor.fetchall()

    vendors = {}

    for row in data:
        vendors.setdefault(row["vendor_id"], []).append(row["quantity"])

    result = []

    for vid, values in vendors.items():

        analysis = analyze_vendor(values)

        if analysis:
            result.append({
                "vendor_id": vid,
                "average": analysis["average"],
                "consistency": analysis["consistency"],
                "rating": analysis["rating"]
            })

    return render_template(
        "ai/vendor_performance.html",
        data=result
    )

@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/learn")
def learn():
    return render_template("head/learn.html")


@app.route("/account")
def account():
    if "id" not in session:
        flash("कृपया login करा.", "warning")
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())
    cursor.execute("SELECT id, email, dairy_name, phone FROM users WHERE id = %s", (session["id"],))
    user = cursor.fetchone()
    return render_template("head/account.html", user=user)


@app.route("/delete_account", methods=["POST"])
def delete_account():
    if "id" not in session:
        flash("Unauthorized request", "danger")
        return redirect(url_for("login"))

    cursor = SafeCursor(mysql.connection.cursor())
    cursor.execute("DELETE FROM users WHERE id = %s", (session["id"],))
    mysql.connection.commit()
    session.clear()
    flash("Account delete केला.", "success")
    return redirect(url_for("signup"))


@app.route("/contact")
def contact():
    return render_template("head/contact.html")





@app.route("/profile")
def profile():
    return render_template("head/profile.html")  # नसेल तर dummy page बनव

@app.route("/analytics")
def analytics():
    return render_template("head/analytics.html")  # नसेल तर dummy page बनव

@app.route("/terms")
def terms():
    return render_template("head/terms.html")  # Terms & Conditions

@app.route("/privacy")
def privacy():
    return render_template("head/privacy.html")  # Privacy Policy




from flask import send_from_directory

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory("static", "service-worker.js")

@app.after_request
def disable_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


import subprocess

@app.route("/restore_backup/<filename>")
def restore_backup(filename):

    if "id" not in session:
        return {"error": "Unauthorized"}, 401

    filepath = os.path.join("backups", filename)

    if not os.path.exists(filepath):
        return {"error": "Backup file not found"}, 404

    command = [
        "mysql",
        "-h", os.getenv("MYSQL_HOST"),
        "-P", str(os.getenv("MYSQL_PORT")),
        "-u", os.getenv("MYSQL_USER"),
        f"-p{os.getenv('MYSQL_PASSWORD')}",
        os.getenv("MYSQL_DB")
    ]

    try:
        with open(filepath, "rb") as sql_file:
            subprocess.run(
                command,
                stdin=sql_file,
                check=True
            )

        return {"status": "restored"}

    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": str(e)
        }, 500

@app.route("/backup_my_data")
def backup_my_data():

    user_id = session["id"]

    file = create_user_backup(user_id)

    return jsonify({
        "status": "success",
        "file": file
    })

@app.route("/restore_my_data/<filename>")
def restore_my_data(filename):

    if "id" not in session:
        return {"error": "Unauthorized"}, 401

    filepath = os.path.join("backups", filename)

    if not os.path.exists(filepath):
        return {"error": "Backup file not found"}, 404

    try:

        restore_user_backup(filepath, session["id"])

        return {
            "status": "success",
            "message": "Backup restored successfully"
        }

    except Exception as e:

        return {
            "status": "error",
            "message": str(e)
        }, 500
        
        

@app.route("/admin_full_backup")
def admin_full_backup():

    file = create_full_backup()

    return jsonify({
        "status": "success",
        "file": file
    })
    
@app.route("/backup_history")
def backup_history():

    os.makedirs("backups", exist_ok=True)
    files = os.listdir("backups")

    return jsonify({
        "files": files
    })

@app.route("/backup_page")
def backup_page():
    return render_template("backup.html")



# ------------------------------
# Healthcheck (simple)
# ------------------------------
@app.route('/healthcheck')
def healthcheck():
    return "OK"

def cleanup_old_backups():

    backup_dir = "backups"

    if not os.path.exists(backup_dir):
        return

    files = sorted(
        os.listdir(backup_dir),
        key=lambda x: os.path.getmtime(os.path.join(backup_dir, x))
    )

    # keep last 30 backups
    while len(files) > 30:

        oldest = files[0]
        filepath = os.path.join(backup_dir, oldest)

        try:
            os.remove(filepath)
            print("Deleted old backup:", oldest)
        except Exception as e:
            print("Error deleting backup:", e)

        files.pop(0)

def create_local_backup():

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    filename = f"backup_{timestamp}.sql"

    filepath = os.path.join("backups", filename)

    command = [
        "mysqldump",
        "--single-transaction",
        "--quick",
        "--lock-tables=false",
        "-h", DB_HOST,
        "-P", str(DB_PORT),
        "-u", DB_USER,
        f"-p{DB_PASS}",
        DB_NAME
    ]
    with open(filepath, "w") as f:
        subprocess.run(command, stdout=f)

    print("Backup created:", filename)

    # cleanup old backups
    cleanup_old_backups()

    return filename



@app.template_filter('date_indian')
def date_indian(value):

    if not value:
        return ""

    if isinstance(value, str):
        try:
            value = datetime.strptime(value, "%Y-%m-%d")
        except:
            return value

    return value.strftime("%d/%m/%Y")

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit

scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

scheduler.add_job(
    func=automatic_backup,
    trigger=CronTrigger(hour=1, minute=30),
    id="daily_backup",
    replace_existing=True
)

# start scheduler safely (avoid duplicate start)
if not scheduler.running:
    scheduler.start()

# stop scheduler when app stops
atexit.register(lambda: scheduler.shutdown())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)