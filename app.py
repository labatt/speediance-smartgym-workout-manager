from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, Response
from api_client import SpeedianceClient, SpeedianceAuthError
from debug_routes import init_debug
import schedule_planner
import progression
import datetime
import json
import os
import sys
import webbrowser
from threading import Timer, Thread
import requests
try:
    import tkinter as tk
    from tkinter import scrolledtext
except Exception:
    tk = None
    scrolledtext = None
from urllib.parse import urlparse

# Determine if running as a script or frozen exe (PyInstaller)
if getattr(sys, 'frozen', False):
    # If frozen, use the temporary folder created by PyInstaller
    base_dir = sys._MEIPASS
    template_folder = os.path.join(base_dir, 'templates')
    static_folder = os.path.join(base_dir, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    # If running as script, use default paths
    app = Flask(__name__)

app.secret_key = "speediance_secret_key" # For Flash Messages
client = SpeedianceClient()
app.register_blueprint(init_debug(client))


def _is_auth_error(error):
    return isinstance(error, SpeedianceAuthError) or str(error) == "Unauthorized"

# --- Media Caching Logic ---
# Define local cache path
# Use base_dir to ensure it works in exe mode (though usually we want cache outside the temp exe folder)
# For the cache, we actually want it next to the executable, not inside the temp folder
if getattr(sys, 'frozen', False):
    # If exe, store cache next to the exe file
    current_dir = os.path.dirname(sys.executable)
else:
    current_dir = app.root_path
    
CACHE_ROOT = os.path.join(current_dir, 'static', 'media_cache')

def get_cache_path(url):
    """Determines local path and subfolder based on URL extension."""
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename: return None, None

    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        subfolder = 'images'
    elif ext in ['.mp4', '.mov', '.webm']:
        subfolder = 'videos'
    elif ext in ['.mp3', '.wav', '.aac']:
        subfolder = 'audio'
    else:
        subfolder = 'misc'
    
    return os.path.join(CACHE_ROOT, subfolder, filename), subfolder

@app.template_filter('local_cache')
def local_cache_filter(url, force=False):
    """Jinja filter to rewrite remote URLs to local proxy URLs."""
    if not url: return ""
    
    # Check if file exists locally
    local_path, _ = get_cache_path(url)
    if local_path and os.path.exists(local_path):
        return url_for('media_proxy', url=url)
    
    # If forced (e.g. on detail page), use proxy to trigger download
    if force:
        return url_for('media_proxy', url=url)
    
    # If not cached and not forced, return original URL to let browser fetch directly
    return url

@app.route('/media_proxy')
def media_proxy():
    """Downloads and serves media files locally."""
    remote_url = request.args.get('url')
    if not remote_url:
        return "No URL provided", 400

    local_path, subfolder = get_cache_path(remote_url)
    if not local_path:
        return redirect(remote_url) # Fallback if filename parsing fails

    filename = os.path.basename(local_path)

    # Serve from cache if exists
    if os.path.exists(local_path):
        size = os.path.getsize(local_path)
        print(f"[CACHE HIT] Served {filename} from disk. Saved {size/1024:.2f} KB of CDN traffic.")
        return send_from_directory(os.path.dirname(local_path), filename)

    # Download if missing
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # Stream download
        print(f"[CACHE MISS] Downloading {filename} from CDN...")
        resp = requests.get(remote_url, stream=True, timeout=10)
        if resp.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            size = os.path.getsize(local_path)
            print(f"[DOWNLOAD] Saved {filename} ({size/1024:.2f} KB) to cache.")
            return send_from_directory(os.path.dirname(local_path), filename)
        else:
            # If download fails, redirect to original URL
            print(f"[ERROR] Failed to download {remote_url} (Status {resp.status_code})")
            return redirect(remote_url)
    except Exception as e:
        print(f"[ERROR] Cache download failed for {remote_url}: {e}")
        return redirect(remote_url)

@app.route('/')
def index():
    if not client.credentials.get("token"):
        return redirect(url_for('settings'))

    try:
        workouts = client.get_user_workouts()
        # Sort workouts from oldest to newest (so newest is closest to Calendar section)
        workouts.sort(key=lambda w: w.get('id', 0))
    except Exception as e:
        if _is_auth_error(e):
            client.logout()
            flash("Session expired. Please login again.", "error")
            return redirect(url_for('settings'))
        flash(f"Error loading workouts: {e}", "error")
        workouts = []

    unit = client.credentials.get('unit', 0)
    return render_template('index.html', workouts=workouts, unit=unit)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        # Manual config save
        device_type = int(request.form.get('device_type', client.credentials.get('device_type', 1)))
        allow_monster_moves = bool(request.form.get('allow_monster_moves'))
        client.save_config(
            request.form['user_id'],
            request.form['token'],
            request.form.get('region', 'Global'),
            int(request.form.get('unit', 0)),
            request.form.get('custom_instruction', ''),
            device_type,
            allow_monster_moves,
            client.credentials.get('owned_accessories', []),
            client.credentials.get('owned_devices', []),
        )
        flash("Settings saved!", "success")
        return redirect(url_for('index'))
    
    creds = client.load_config()
    # Ensure new fields exist for older configs
    if 'owned_accessories' not in creds:
        creds['owned_accessories'] = []
    if 'owned_devices' not in creds:
        creds['owned_devices'] = []
    accessories = []
    if creds.get('token'):
        try:
            accessories = client.get_accessories()
        except Exception as e:
            flash(f"Error loading accessories: {e}", "error")
    return render_template('settings.html', creds=creds, accessories=accessories)

@app.route('/settings/custom_instruction', methods=['POST'])
def update_custom_instruction():
    data = request.json
    instruction = data.get('instruction', '')
    
    # Update only the instruction, keep other settings
    creds = client.credentials
    client.save_config(
        creds.get('user_id'),
        creds.get('token'),
        creds.get('region'),
        creds.get('unit', 0),
        instruction,
        creds.get('device_type', 1),
        creds.get('allow_monster_moves', False),
        creds.get('owned_accessories', []),
        creds.get('owned_devices', []),
    )
    return jsonify({"status": "success"})

@app.route('/settings/unit', methods=['POST'])
def update_unit():
    unit = request.form.get('unit')
    success, msg = client.update_unit(unit)
    if success:
        flash("Unit preference updated!", "success")
    else:
        flash(f"Error updating unit: {msg}", "error")
    return redirect(url_for('settings'))

@app.route('/settings/accessories', methods=['POST'])
def update_accessories():
    selected = request.form.getlist('accessories')
    owned = [int(x) for x in selected]
    creds = client.credentials
    client.save_config(
        creds.get('user_id'),
        creds.get('token'),
        creds.get('region'),
        creds.get('unit', 0),
        creds.get('custom_instruction', ''),
        creds.get('device_type', 1),
        creds.get('allow_monster_moves', False),
        owned,
        creds.get('owned_devices', []),
    )
    flash("Accessory settings updated!", "success")
    return redirect(url_for('settings'))

@app.route('/settings/owned_devices', methods=['POST'])
def update_owned_devices():
    selected = request.form.getlist('owned_devices')
    owned = [int(x) for x in selected]
    creds = client.credentials
    client.save_config(
        creds.get('user_id'),
        creds.get('token'),
        creds.get('region'),
        creds.get('unit', 0),
        creds.get('custom_instruction', ''),
        creds.get('device_type', 1),
        creds.get('allow_monster_moves', False),
        creds.get('owned_accessories', []),
        owned,
    )
    flash("Owned devices updated!", "success")
    return redirect(url_for('settings'))

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    region = request.form.get('region', 'Global')
    
    if not email or not password:
        flash("Email and password required", "error")
        return redirect(url_for('settings'))
    
    # Update client region before login attempt
    client.region = region
    client.host = "euapi.speediance.com" if region == "EU" else "api2.speediance.com"
    client.base_url = "https://" + client.host
        
    remember = bool(request.form.get('remember'))
    success, message, debug_info = client.login(email, password, remember=remember)
    if success:
        flash("Login successful!", "success")
        return redirect(url_for('index'))
    else:
        flash(message, "error")
        if debug_info:
            flash(debug_info, "debug")
        return redirect(url_for('settings'))

@app.route('/logout')
def logout():
    # Keeps any remembered credentials, so signing back in is one click. Use
    # /auth/forget to actually erase them.
    client.logout()
    flash("Logged out successfully", "success")
    return redirect(url_for('settings'))


@app.route('/auth/relogin', methods=['POST'])
def auth_relogin():
    """One-click sign-in using remembered credentials."""
    if not client.has_saved_credentials():
        flash("No saved credentials — sign in once with 'Remember me' first.", "error")
        return redirect(url_for('settings'))

    success, message, debug_info = client.login(
        client.credentials.get('saved_email'),
        client.credentials.get('saved_password'),
        remember=True,
    )
    if success:
        flash("Signed back in.", "success")
        return redirect(request.referrer or url_for('index'))

    flash(f"Automatic sign-in failed: {message}", "error")
    return redirect(url_for('settings'))


@app.route('/auth/forget', methods=['POST'])
def auth_forget():
    """Erase the remembered email/password from config.json."""
    client.forget_credentials()
    flash("Saved credentials erased.", "success")
    return redirect(url_for('settings'))


@app.context_processor
def inject_auth_state():
    """Every page's nav bar shows whether we currently hold a live session.

    Speediance allows one live session per account, so signing in on the phone app
    silently invalidates this app's token. Without this, the app just looks broken.
    """
    return {
        "auth_state": {
            "logged_in": bool(client.credentials.get("token")),
            "email": client.credentials.get("saved_email") or "",
            "can_quick_login": client.has_saved_credentials(),
        }
    }

@app.route('/settings/preload')
def preload_assets():
    """Streamed response that downloads all assets."""
    if not client.credentials.get("token"): return "Unauthorized", 401

    def download_url(url):
        if not url or not url.startswith('http'): return "Skipped (Invalid URL)"
        
        local_path, subfolder = get_cache_path(url)
        if not local_path: return "Skipped (Path error)"
        
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            return "Skipped (Already exists)"
            
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            resp = requests.get(url, stream=True, timeout=20)
            if resp.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return "Downloaded"
            else:
                return f"Failed (Status {resp.status_code})"
        except Exception as e:
            return f"Error: {e}"

    def extract_urls_from_exercise(ex):
        urls = set()
        if ex.get('img'): urls.add(ex['img'])
        
        # Variants
        for variant in ex.get('actionLibraryList', []):
            if variant.get('videoPath'): urls.add(variant['videoPath'])
            if variant.get('leftVideo'): urls.add(variant['leftVideo'])
            if variant.get('rightVideo'): urls.add(variant['rightVideo'])
            if variant.get('endVideo'): urls.add(variant['endVideo'])
            
            if variant.get('startVideo'):
                for v in variant['startVideo'].split(','):
                    if v.strip(): urls.add(v.strip())
            
            if variant.get('coach', {}).get('avatar'):
                urls.add(variant['coach']['avatar'])
                
            for key in ['actionNameVoice', 'completionTimeVoice', 'completionNumberVoice', 'goVoice', 'restConfigVoice']:
                if variant.get(key): urls.add(variant[key])
            
            for i in range(1, 7):
                key = f'guideVoice{i}'
                if variant.get(key): urls.add(variant[key])

        # Steps
        try:
            if ex.get('showDetails'):
                steps = json.loads(ex['showDetails'])
                for step in steps:
                    if step.get('img'): urls.add(step['img'])
        except:
            pass
        return urls

    def generate():
        yield "Starting deep discovery and download of assets...\n"
        yield "This process fetches full details for every exercise to ensure no video is missed.\n"
        yield "It may take several minutes. Please do not close this tab.\n\n"
        
        # 1. Accessories
        yield "--- Processing Accessories ---\n"
        try:
            accessories = client.get_accessories()
            for acc in accessories:
                if acc.get('img'): 
                    res = download_url(acc['img'])
                    yield f"Accessory {acc.get('name', 'Unknown')}: {res}\n"
        except Exception as e:
            yield f"Error scanning accessories: {e}\n"

        # 2. Library
        yield "\n--- Processing Exercise Library ---\n"
        try:
            # Get the list of groups first
            library_groups = client.get_library()
            total_groups = len(library_groups)
            
            for i, group in enumerate(library_groups):
                group_id = group.get('id')
                group_title = group.get('title', f'ID {group_id}')
                yield f"[{i+1}/{total_groups}] Processing: {group_title} ... "
                
                # Fetch FULL details for this exercise group
                # This ensures we get all variants and videos even if the list endpoint was incomplete
                try:
                    detail = client.get_exercise_detail(group_id)
                    if not detail:
                        yield "Failed to fetch details.\n"
                        continue
                        
                    urls = extract_urls_from_exercise(detail)
                    yield f"Found {len(urls)} assets.\n"
                    
                    for url in urls:
                        filename = os.path.basename(urlparse(url).path)
                        res = download_url(url)
                        if "Downloaded" in res:
                            yield f"    -> {filename}: {res}\n"
                            
                except Exception as e:
                    yield f"Error fetching details: {e}\n"
                    
        except Exception as e:
            yield f"Error scanning library: {e}\n"
        
        yield "\nDone! All assets have been processed."

    return Response(generate(), mimetype='text/plain')

# ---------------------------------------------------------------------------
# Recurring schedules
#
# Speediance has no recurrence: `templateReservation` writes ONE dated entry. So the
# repeating pattern lives here, locally, and is materialised into individual dated calls.
# The pattern logic itself is in schedule_planner.py and is pure/unit-tested, because
# applying a schedule deletes calendar entries and that must not be decided by guesswork.
# ---------------------------------------------------------------------------

SCHEDULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schedules.json')
DEFAULT_HORIZON_WEEKS = 12


def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Could not read {SCHEDULE_FILE}: {e}")
    return {
        "enabled": False,
        "mode": "weekly",
        "horizonWeeks": DEFAULT_HORIZON_WEEKS,
        "weekly": {d: None for d in schedule_planner.WEEKDAYS},
        "cycle": {"anchor": datetime.date.today().isoformat(), "sequence": []},
        "appliedThrough": None,
    }


def save_schedule(schedule):
    with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
        json.dump(schedule, f, indent=2)


def _calendar_between(start, end):
    """Merged calendar days across every month the range touches."""
    days = []
    seen = set()
    month = datetime.date(start.year, start.month, 1)
    while month <= end:
        key = month.strftime('%Y-%m')
        if key not in seen:
            seen.add(key)
            days.extend(client.get_calendar_month(key) or [])
        month = (month + datetime.timedelta(days=32)).replace(day=1)
    return days


def _horizon(schedule, from_date=None):
    start = from_date or datetime.date.today()
    weeks = int(schedule.get('horizonWeeks') or DEFAULT_HORIZON_WEEKS)
    return start, start + datetime.timedelta(weeks=weeks)


def _build_changes(schedule, protect_before=None):
    start, end = _horizon(schedule)
    existing = schedule_planner.existing_by_date(_calendar_between(start, end))
    changes = schedule_planner.plan_changes(
        schedule, start, end, existing, protect_before=protect_before
    )
    return start, end, changes


def _apply_changes(changes):
    """Execute the diff. Removals first, then the write, so a day is never doubled up."""
    results = []
    for change in changes:
        if change['action'] == 'noop':
            continue
        date_str, ok, errors = change['date'], True, []

        for victim in change.get('remove') or []:
            try:
                client.schedule_workout(date_str, victim['code'], 0)
            except Exception as e:
                ok = False
                errors.append(f"remove {victim.get('title')}: {e}")

        if change.get('wanted'):
            try:
                client.schedule_workout(date_str, change['wanted'], 1)
            except Exception as e:
                ok = False
                errors.append(f"write: {e}")

        results.append({"date": date_str, "action": change['action'], "ok": ok, "errors": errors})
    return results


@app.route('/schedule')
def schedule_page():
    if not client.credentials.get("token"):
        return redirect(url_for('settings'))

    # An expired token must land the user on the login page, not a 500. Every other page
    # already does this; omitting it here turned a routine token expiry into an Internal
    # Server Error.
    try:
        workouts = client.get_user_workouts()
    except Exception as e:
        if _is_auth_error(e):
            client.logout()
            flash("Session expired. Please login again.", "error")
            return redirect(url_for('settings'))
        flash(f"Error loading workouts: {e}", "error")
        return redirect(url_for('index'))

    return render_template(
        'schedule.html',
        schedule=load_schedule(),
        workouts=workouts,
        today=datetime.date.today().isoformat(),
    )


@app.route('/api/schedule/pattern', methods=['GET', 'PUT'])
def api_schedule_pattern():
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401

    if request.method == 'GET':
        return jsonify(load_schedule())

    incoming = request.json or {}
    schedule = load_schedule()
    for key in ('enabled', 'mode', 'horizonWeeks', 'weekly', 'cycle'):
        if key in incoming:
            schedule[key] = incoming[key]
    save_schedule(schedule)
    return jsonify(schedule)


@app.route('/api/schedule/preview', methods=['POST'])
def api_schedule_preview():
    """Read-only. Says exactly what apply would create and destroy. Touches nothing."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        schedule = request.json or load_schedule()
        start, end, changes = _build_changes(schedule)
        return jsonify({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "summary": schedule_planner.summarize(changes),
            "changes": [c for c in changes if c['action'] != 'noop'],
            "noopCount": sum(1 for c in changes if c['action'] == 'noop'),
        })
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500


@app.route('/api/schedule/apply', methods=['POST'])
def api_schedule_apply():
    """Destructive, and only ever reached by an explicit click after a preview."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        schedule = request.json or load_schedule()
        start, end, changes = _build_changes(schedule)
        results = _apply_changes(changes)

        schedule['appliedThrough'] = end.isoformat()
        schedule['enabled'] = True
        save_schedule(schedule)

        failed = [r for r in results if not r['ok']]
        return jsonify({
            "applied": len(results) - len(failed),
            "failed": len(failed),
            "failures": failed,
            "appliedThrough": schedule['appliedThrough'],
        })
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500


@app.route('/api/schedule/topup', methods=['POST'])
def api_schedule_topup():
    """Called quietly by the dashboard to keep the horizon full.

    This runs unattended, so it is deliberately NOT destructive across the whole horizon:
    `protect_before=appliedThrough` confines it to days beyond what the user has already
    seen and confirmed. A one-off placed inside the reviewed window can never be silently
    eaten by a background top-up.
    """
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401

    schedule = load_schedule()
    if not schedule.get('enabled'):
        return jsonify({"skipped": "not enabled"})

    try:
        applied_through = schedule.get('appliedThrough')
        start, end, changes = _build_changes(schedule, protect_before=applied_through)
        if not changes:
            return jsonify({"extended": 0, "appliedThrough": applied_through})

        results = _apply_changes(changes)
        schedule['appliedThrough'] = end.isoformat()
        save_schedule(schedule)
        return jsonify({"extended": len(results), "appliedThrough": schedule['appliedThrough']})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Training journal
#
# Records a factual snapshot of each completed session plus the athlete's own subjective
# feel (overall, and optionally per exercise — any, all, or none). Deliberately no
# verdicts: the 2026-07-14 session showed a power-only rule calling an easy Leg Curl
# "grinding" and a hard Hip Abduction "too light". The felt rating is the ground truth the
# sensors miss; value comes from comparing facts + feel across sessions, not from a
# same-day oracle. See progression.py.
# ---------------------------------------------------------------------------

JOURNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'journal.json')


def load_journal():
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Could not read journal: {e}")
    return {}


def save_journal(data):
    with open(JOURNAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def _analyze_training(training_id):
    """Facts for one session, enriched with muscle names from the library."""
    detail = client.get_training_detail(training_id, 'custom')
    try:
        lib = {e['id']: e for e in client.get_library()}
        for ex in detail or []:
            g = lib.get(ex.get('actionLibraryGroupId'))
            if g and not ex.get('mainMuscleGroupName'):
                ex['mainMuscleGroupName'] = g.get('mainMuscleGroupName')
    except Exception:
        pass  # names are a nicety; the region rollup works without them
    return progression.analyze_session(detail)


@app.route('/api/session/<int:training_id>/analysis')
def api_session_analysis(training_id):
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        snapshot = _analyze_training(training_id)
        notes = load_journal().get(str(training_id), {})

        # Line up against the previous session of the SAME workout template.
        prev = None
        template_id = request.args.get('template_id')
        if template_id:
            try:
                end = datetime.date.today()
                start = end - datetime.timedelta(days=120)
                records = client.get_training_records(start.isoformat(), end.isoformat())
                earlier = [r for r in records
                           if str(r.get('templateId')) == str(template_id)
                           and r.get('trainingId') != training_id]
                if earlier:
                    prev = _analyze_training(earlier[0]['trainingId'])
            except Exception:
                prev = None

        return jsonify({
            "snapshot": snapshot,
            "notes": notes,
            "comparison": progression.compare_sessions(snapshot, prev) if prev else None,
            "feel_scale": progression.FEEL_SCALE,
        })
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500


@app.route('/api/session/<int:training_id>/notes', methods=['POST'])
def api_session_notes(training_id):
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401

    incoming = request.json or {}
    journal = load_journal()
    entry = journal.get(str(training_id), {})

    # Every field optional. overall: a feel rating or null. exercises: {name: rating}.
    if 'overall' in incoming:
        entry['overall'] = incoming['overall']
    if 'note' in incoming:
        entry['note'] = incoming['note']
    if 'exercises' in incoming and isinstance(incoming['exercises'], dict):
        ex_notes = entry.setdefault('exercises', {})
        for name, feel in incoming['exercises'].items():
            if feel:
                ex_notes[name] = feel
            else:
                ex_notes.pop(name, None)

    journal[str(training_id)] = entry
    save_journal(journal)
    return jsonify(entry)


@app.route('/api/burn_rate')
def api_burn_rate():
    """Your personal kcal/min, measured from what the machine actually recorded.

    The builder used to estimate burn as MET x 70kg x active-time-only, which was wrong
    twice over: nobody's body weight is assumed-70kg, and it threw away rest time, which
    the device plainly counts (it burns calories for the whole session). On a real 75-min
    session that produced ~118 kcal against the device's 739.

    Rather than guess a body weight the API does not expose, calibrate against the user's
    own history: the device's kcal/min turns out to be very stable per user (median 10.44,
    stdev 0.58 over 18 sessions on the account this was built against).
    """
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        end = datetime.date.today()
        start = end - datetime.timedelta(days=90)
        records = client.get_training_records(start.isoformat(), end.isoformat())

        rates = []
        for r in records:
            secs = r.get('trainingTime') or 0
            kcal = r.get('calorie') or 0
            # Skip trivially short sessions — their rate is dominated by rounding.
            if secs > 300 and kcal > 0:
                rates.append(kcal / (secs / 60.0))

        if not rates:
            return jsonify({"kcal_per_min": None, "sessions": 0})

        rates.sort()
        median = rates[len(rates) // 2] if len(rates) % 2 else \
            (rates[len(rates) // 2 - 1] + rates[len(rates) // 2]) / 2.0

        return jsonify({"kcal_per_min": round(median, 2), "sessions": len(rates)})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500


@app.route('/api/stats/<int:group_id>')
def api_stats(group_id):
    """Returns user statistics for a specific exercise."""
    if not client.credentials.get("token"): 
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        # Fetch stats using the client
        result = client.get_user_action_stats(group_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/library')
def library():
    if not client.credentials.get("token"): return redirect(url_for('settings'))
    try:
        exercises = client.get_library()
        accessories = client.get_accessories()
        categories = client.get_categories()
    except Exception as e:
        if _is_auth_error(e):
            client.logout()
            flash("Session expired. Please login again.", "error")
            return redirect(url_for('settings'))
        flash(f"Error loading library: {e}", "error")
        exercises = []
        accessories = []
        categories = []

    accessory_map = {str(acc['id']): acc['name'] for acc in accessories}
    
    # Enrich exercises with equipment names
    for ex in exercises:
        acc_ids = str(ex.get('accessories', '')).split(',')
        names = [accessory_map.get(aid, 'Standard') for aid in acc_ids if aid]
        ex['equipment_name'] = ', '.join(names) if names else 'Standard'
        
    owned_accessories = client.credentials.get('owned_accessories', [])
    owned_devices = client.credentials.get('owned_devices', [])
    return render_template(
        'library.html',
        exercises=exercises,
        categories=categories,
        device_type=client.device_type,
        allow_monster_moves=client.allow_monster_moves,
        owned_accessories=owned_accessories,
        owned_devices=owned_devices,
    )

@app.route('/library/refresh')
def refresh_library():
    if not client.credentials.get("token"): return redirect(url_for('settings'))
    
    # Clear memory and disk cache
    client.library_cache = None
    if os.path.exists(client.library_cache_file):
        try:
            os.remove(client.library_cache_file)
        except Exception as e:
            print(f"Error removing cache file: {e}")
            
    flash("Library cache cleared. Reloading from server...", "info")
    return redirect(url_for('library'))

@app.route('/exercise/<int:ex_id>')
def exercise_detail(ex_id):
    if not client.credentials.get("token"): return redirect(url_for('settings'))
    
    # 1. Load details
    detail = client.get_exercise_detail(ex_id)
    
    # 2. Resolve accessories (IDs -> Objects with Image/Name)
    all_accessories = client.get_accessories()
    required_ids = detail.get('accessories', '').split(',')
    
    mapped_accessories = []
    for acc in all_accessories:
        # Check if the ID is in the required list
        if str(acc['id']) in required_ids:
            mapped_accessories.append(acc)
            
    # 3. "showDetails" is a JSON string in the API response, we need to parse it
    # Format: [{"context": "Text...", "img": "url..."}, ...]
    try:
        if detail.get('showDetails'):
            detail['steps'] = json.loads(detail['showDetails'])
        else:
            detail['steps'] = []
    except Exception as e:
        print(f"JSON Parse Error: {e}")
        detail['steps'] = []

    return render_template('exercise_detail.html', ex=detail, accessories=mapped_accessories)

@app.route('/api/exercise/<int:ex_id>')
def api_exercise_detail(ex_id):
    """Returns details as JSON for the frontend (dropdowns)"""
    if not client.credentials.get("token"): 
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        # Uses the existing cache/request
        detail = client.get_exercise_detail(ex_id)
        return jsonify(detail)
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/api/workout/<code>')
def api_workout_detail(code):
    """Returns workout detail as JSON (used for bulk export)."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        detail = client.get_workout_detail(code)
        return jsonify(detail)
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/api/calendar')
def api_calendar():
    """Returns calendar data for a specific month."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Missing date parameter"}), 400
        
    try:
        data = client.get_calendar_month(date_str)
        return jsonify(data)
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/api/schedule', methods=['POST'])
def api_schedule():
    """Schedules or unschedules a workout."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    date_str = data.get('date')
    template_code = data.get('templateCode')
    status = data.get('status')

    if not date_str or not template_code or status is None:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        success = client.schedule_workout(date_str, template_code, status)
        return jsonify({"success": success})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/api/schedule_course', methods=['POST'])
def api_schedule_course():
    """Schedules or unschedules an official course."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    date_str = data.get('date')
    course_id = data.get('courseId')
    status = data.get('status', 1)

    if not date_str or not course_id:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        success = client.schedule_course(date_str, course_id, status)
        return jsonify({"success": success})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/history')
def history_page():
    if not client.credentials.get("token"):
        return redirect(url_for('settings'))
    unit = client.credentials.get('unit', 0)
    return render_template('history.html', unit=unit)

@app.route('/api/history')
def api_history():
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    start = request.args.get('start')
    end = request.args.get('end')
    if not start or not end:
        return jsonify({"error": "Missing start/end parameters"}), 400
    try:
        records = client.get_training_records(start, end)
        stats = client.get_training_stats(start, end)
        return jsonify({"records": records, "stats": stats})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/api/history/detail/<int:training_id>')
def api_history_detail(training_id):
    """Returns detailed info for a completed training session."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    training_type = request.args.get('type', 'custom')  # 'course' or 'custom'
    try:
        detail = client.get_training_detail(training_id, training_type)
        session_info = client.get_training_session_info(training_id)
        return jsonify({"detail": detail, "session": session_info})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/debug/last_response')
def debug_last_response():
    """Returns the last API request/response info for debugging."""
    return jsonify(client.last_debug_info)

@app.route('/browse')
def browse_page():
    if not client.credentials.get("token"):
        return redirect(url_for('settings'))
    unit = client.credentials.get('unit', 0)
    owned_accessories = client.credentials.get('owned_accessories', [])
    owned_devices = client.credentials.get('owned_devices', [])
    return render_template('browse.html', unit=unit, owned_accessories=owned_accessories, owned_devices=owned_devices)

@app.route('/api/browse/courses')
def api_browse_courses():
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        all_courses = []
        seen_ids = set()
        for page in range(1, 20):
            batch = client.get_courses_page(page, 200)
            if not batch:
                break
            for c in batch:
                if c.get('id') not in seen_ids:
                    seen_ids.add(c['id'])
                    all_courses.append(c)
            if len(batch) < 200:
                break
        return jsonify({"courses": all_courses})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/api/browse/course/<int:course_id>')
def api_browse_course_detail(course_id):
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        detail = client.get_course_detail(course_id)
        return jsonify(detail)
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/api/browse/programs')
def api_browse_programs():
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        page = request.args.get('page', 1, type=int)
        programs = client.get_programs_page(page, 200)
        return jsonify({"programs": programs, "page": page, "hasMore": len(programs) == 200})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/api/browse/program/<int:plan_id>')
def api_browse_program_detail(plan_id):
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        detail = client.get_program_detail(plan_id)
        return jsonify(detail)
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route('/edit/<string:code>')  # HERE: string instead of int
def edit(code):
    if not client.credentials.get("token"): return redirect(url_for('settings'))
    
    try:
        # Load workout details via code
        workout = client.get_workout_detail(code)
        library = client.get_library()
        categories = client.get_categories()
    except Exception as e:
        if _is_auth_error(e):
            client.logout()
            flash("Session expired. Please login again.", "error")
            return redirect(url_for('settings'))
        flash(f"Error loading data: {e}", "error")
        return redirect(url_for('index'))
    
    if not workout:
        flash("Could not load workout details.", "error")
        return redirect(url_for('index'))

    unit = client.credentials.get("unit", 0)
    custom_instruction = client.credentials.get("custom_instruction", "")
    return render_template(
        'create.html',
        library=library,
        existing_workout=workout,
        unit=unit,
        custom_instruction=custom_instruction,
        categories=categories,
        device_type=client.device_type,
        allow_monster_moves=client.allow_monster_moves,
    )


@app.route('/create', methods=['GET', 'POST'])
def create():
    if not client.credentials.get("token"): return redirect(url_for('settings'))
    
    if request.method == 'POST':
        data = request.json 
        name = data.get('name')
        exercises = data.get('exercises')
        template_id = data.get('id') 
        
        try:
            result = client.save_workout(name, exercises, template_id)
            if result.get('code') == 0:
                return jsonify({"status": "success"})
            else:
                return jsonify({"status": "error", "message": result.get('message')})
        except Exception as e:
            if _is_auth_error(e):
                return jsonify({"status": "error", "message": "Session expired. Please login again."}), 401
            return jsonify({"status": "error", "message": str(e)})

    try:
        library = client.get_library()
        categories = client.get_categories()
    except Exception as e:
        if _is_auth_error(e):
            client.logout()
            flash("Session expired. Please login again.", "error")
            return redirect(url_for('settings'))
        flash(f"Error loading workout builder data: {e}", "error")
        library = []
        categories = []

    unit = client.credentials.get("unit", 0)
    custom_instruction = client.credentials.get("custom_instruction", "")
    
    # HERE: We pass 'None' so the template knows: "No data to preload"
    # This has NO influence on the edit route, which sends its own data.
    return render_template(
        'create.html',
        library=library,
        existing_workout=None,
        unit=unit,
        custom_instruction=custom_instruction,
        categories=categories,
        device_type=client.device_type,
        allow_monster_moves=client.allow_monster_moves,
    )

@app.route('/delete/<int:id>')
def delete(id):
    client.delete_workout(id)
    flash("Workout deleted.", "info")
    return redirect(url_for('index'))

@app.route('/workout_history')
def workout_history():
    if not client.credentials.get("token"): return redirect(url_for('settings'))
    return render_template('workout_history.html')

@app.route('/api/workout_history', methods=['GET'])
def api_workout_history():
    start = request.args.get('start')
    end = request.args.get('end')
    if not start or not end:
        return jsonify({"error": "Missing dates"}), 400

    try:
        data = client.get_training_history(start, end)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/workout_history/detail/<path:record_id>')
def api_workout_history_detail(record_id):
    training_type = request.args.get('type', default=2, type=int)

    if training_type == 5:
        target_url = f"{client.base_url}/api/app/trainingInfo/cttTrainingInfoDetail/{record_id}"
    else:
        target_url = f"{client.base_url}/api/app/trainingInfo/courseTrainingInfoDetail/{record_id}"

    try:
        headers = client._get_headers()
        response = requests.get(target_url, headers=headers, timeout=10)

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({
                "error": f"Speediance API Error: {response.status_code}",
                "url": target_url,
                "type_requested": training_type
            }), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

class TextRedirector(object):
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, str):
        try:
            self.widget.configure(state="normal")
            self.widget.insert("end", str, (self.tag,))
            self.widget.see("end")
            self.widget.configure(state="disabled")
        except:
            pass
    
    def flush(self):
        pass

def open_browser():
    webbrowser.open_new("http://127.0.0.1:5001")

def run_flask_server():
    try:
        app.run(debug=False, port=5001, host='0.0.0.0', use_reloader=False)
    except Exception as e:
        print(f"Error starting server: {e}")

def start_gui():
    if tk is None:
        print("Tkinter is not available; starting Flask server without GUI.")
        run_flask_server()
        return
    root = tk.Tk()
    root.title("Unofficial Speediance Workout Manager Server")
    root.geometry("700x500")
    
    lbl = tk.Label(root, text="Unofficial Speediance Workout Manager is running.\nDo not close this window while using the app.", font=("Arial", 10), pady=10)
    lbl.pack()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=5)

    btn_open = tk.Button(btn_frame, text="Open in Browser", command=open_browser, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=10, pady=5)
    btn_open.pack(side=tk.LEFT, padx=10)

    def on_close():
        root.destroy()
        sys.exit(0)

    btn_close = tk.Button(btn_frame, text="Stop Server & Exit", command=on_close, bg="#f44336", fg="white", font=("Arial", 10, "bold"), padx=10, pady=5)
    btn_close.pack(side=tk.LEFT, padx=10)

    log_frame = tk.Frame(root)
    log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    tk.Label(log_frame, text="Server Logs:", anchor="w").pack(fill=tk.X)
    
    text_area = scrolledtext.ScrolledText(log_frame, state='disabled', font=("Consolas", 9))
    text_area.pack(fill=tk.BOTH, expand=True)
    
    sys.stdout = TextRedirector(text_area, "stdout")
    sys.stderr = TextRedirector(text_area, "stderr")

    root.protocol("WM_DELETE_WINDOW", on_close)

    t = Thread(target=run_flask_server, daemon=True)
    t.start()

    Timer(2.0, open_browser).start()

    root.mainloop()

if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        start_gui()
    else:
        app.run(debug=True, port=5001, host='0.0.0.0')
