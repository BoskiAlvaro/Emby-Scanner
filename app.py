import yaml
import requests
import sys
import os
import sqlite3
import threading
import time
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, redirect, url_for

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.yaml')
DB_FILE = os.path.join(CONFIG_DIR, 'scheduler.db')
LOG_FILE = os.path.join(CONFIG_DIR, 'execution.log')


# --- DATABASE ---

def init_db():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Base tables
    c.execute('''
              CREATE TABLE IF NOT EXISTS schedules
              (
                  id
                  INTEGER
                  PRIMARY
                  KEY
                  AUTOINCREMENT,
                  library_id
                  TEXT,
                  frequency
                  TEXT,
                  custom_time
                  TEXT,
                  last_run
                  DATETIME
              )
              ''')
    c.execute('''
              CREATE TABLE IF NOT EXISTS custom_names
              (
                  item_id
                  TEXT
                  PRIMARY
                  KEY,
                  name
                  TEXT
              )
              ''')

    # Migration: Add created_at if missing
    try:
        c.execute("ALTER TABLE schedules ADD COLUMN created_at DATETIME")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# --- LOGGING SYSTEM ---

def log_execution(item_name, item_path, source, success, error_msg=None):
    entry = {
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "name": item_name,
        "path": item_path,
        "source": source,
        "status": "Success" if success else "Failed",
        "error": str(error_msg) if error_msg else ""
    }
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Logging error: {e}")


def get_item_details(library_id, config):
    try:
        base = get_base_url_from_dict(config['server'])
        api_key = config['server']['api_key']
        url = f"{base}/emby/Items?Ids={library_id}&Fields=Path&api_key={api_key}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if 'Items' in data and len(data['Items']) > 0:
                item = data['Items'][0]
                return item.get('Name', 'Unknown'), item.get('Path', 'N/A')
    except Exception:
        pass
    return "ID: " + str(library_id), "N/A"


# --- HELPER LOGIC ---

def calculate_next_run_date(last_run_str, freq, custom_time_str, created_at_str):
    if not freq or freq == 'manual':
        return None

    now = datetime.now()

    # 1. Weekly (MON 14:00)
    if freq == 'weekly' and custom_time_str:
        try:
            target_day_str, target_time = custom_time_str.split(' ')
            h, m = map(int, target_time.split(':'))
            weekday_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
            target_weekday = weekday_map.get(target_day_str, 0)

            days_ahead = target_weekday - now.weekday()

            target_dt_today = now.replace(hour=h, minute=m, second=0, microsecond=0)

            if days_ahead < 0 or (days_ahead == 0 and now >= target_dt_today):
                days_ahead += 7

            return now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=days_ahead)
        except:
            return None

    # 2. Daily Custom
    if freq == 'daily_custom' and custom_time_str:
        try:
            h, m = map(int, custom_time_str.split(':'))
            target_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if now < target_today:
                return target_today
            else:
                return target_today + timedelta(days=1)
        except ValueError:
            return None

    # 3. Intervals
    base_time = None
    if last_run_str:
        try:
            base_time = datetime.strptime(last_run_str, '%Y-%m-%d %H:%M:%S')
        except:
            pass
    elif created_at_str:
        try:
            base_time = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
        except:
            pass

    if not base_time:
        return None

    minutes_map = {
        '15min': 15, '30min': 30, '45min': 45,
        '1h': 60, '2h': 120, '3h': 180, '6h': 360, '12h': 720, '24h': 1440
    }
    minutes = minutes_map.get(freq)

    if minutes:
        return base_time + timedelta(minutes=minutes)

    return None


def format_next_run(dt_obj):
    if dt_obj is None:
        return "Pending..."
    if dt_obj < datetime.now():
        return "Pending (Overdue)..."
    return dt_obj.strftime('%Y-%m-%d %H:%M:%S')


# --- CONFIGURATION ---

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def save_config(new_config):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump(new_config, f, default_flow_style=False)
        return True
    except Exception:
        return False


def get_base_url_from_dict(server_dict):
    return f"http://{server_dict['ip']}:{server_dict['port']}"


# --- SCHEDULER & REFRESH ---

def perform_refresh(library_id, config, source="System"):
    name, path = get_item_details(library_id, config)

    conn = get_db_connection()
    custom = conn.execute("SELECT name FROM custom_names WHERE item_id = ?", (library_id,)).fetchone()
    conn.close()

    if custom:
        name = f"{custom['name']} ({name})"

    try:
        base = get_base_url_from_dict(config['server'])
        url = f"{base}/emby/Items/{library_id}/Refresh"
        params = {
            'Recursive': 'true',
            'MetadataRefreshMode': 'Default',
            'ImageRefreshMode': 'Default',
            'ReplaceAllMetadata': 'false',
            'ReplaceAllImages': 'false',
            'api_key': config['server']['api_key']
        }

        resp = requests.post(url, params=params, timeout=10)
        resp.raise_for_status()

        log_execution(name, path, source, True)
        return True
    except Exception as e:
        print(f"Refresh error: {e}")
        log_execution(name, path, source, False, str(e))
        return False


def check_schedules():
    config = load_config()
    if not config or 'server' not in config:
        return

    conn = get_db_connection()
    tasks = conn.execute('SELECT * FROM schedules').fetchall()
    now = datetime.now()

    for task in tasks:
        tid, lid, freq, ctime, last_str = task['id'], task['library_id'], task['frequency'], task['custom_time'], task[
            'last_run']

        created_str = task['created_at'] if 'created_at' in task.keys() else None

        should_run = False
        last = datetime.strptime(last_str, '%Y-%m-%d %H:%M:%S') if last_str else None
        created = datetime.strptime(created_str, '%Y-%m-%d %H:%M:%S') if created_str else None

        if freq == 'manual':
            continue

        if freq == 'weekly':
            if ctime:
                try:
                    # ctime format: "MON 14:00"
                    target_day, target_time = ctime.split(' ')
                    h, m = map(int, target_time.split(':'))
                    weekday_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}

                    if now.weekday() == weekday_map.get(target_day):
                        target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                        if now >= target_dt and (not last or last < target_dt):
                            should_run = True
                except:
                    pass

        elif freq == 'daily_custom':
            if ctime:
                try:
                    h, m = map(int, ctime.split(':'))
                    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if now >= target and (not last or last < target):
                        should_run = True
                except:
                    pass
        else:
            mins = {
                '15min': 15, '30min': 30, '45min': 45,
                '1h': 60, '2h': 120, '3h': 180, '6h': 360, '12h': 720, '24h': 1440
            }.get(freq)

            if mins:
                base_time = last if last else created
                if not base_time:
                    should_run = True
                elif now >= base_time + timedelta(minutes=mins):
                    should_run = True

        if should_run:
            source_label = f"Scheduler ({ctime if freq in ['daily_custom', 'weekly'] else freq})"
            if perform_refresh(lid, config, source=source_label):
                conn.execute('UPDATE schedules SET last_run = ? WHERE id = ?', (now.strftime('%Y-%m-%d %H:%M:%S'), tid))
                conn.commit()
    conn.close()


def scheduler_loop():
    while True:
        try:
            check_schedules()
        except Exception:
            pass
        time.sleep(60)


init_db()
t = threading.Thread(target=scheduler_loop, daemon=True)
t.start()


# --- ROUTES ---

@app.route('/')
def index():
    if not os.path.exists(CONFIG_FILE):
        return redirect(url_for('setup_page'))

    config = load_config()
    if not config or 'server' not in config:
        return redirect(url_for('setup_page'))

    api_key = config['server'].get('api_key')
    base = get_base_url_from_dict(config['server'])
    hidden_ids = [str(x) for x in config.get('hidden_ids', [])]

    conn = get_db_connection()
    db_schedules = conn.execute('SELECT * FROM schedules').fetchall()
    db_names = conn.execute('SELECT * FROM custom_names').fetchall()
    conn.close()

    temp_status = {}
    active_schedule_ids = set()
    for row in db_schedules:
        lid = row['library_id']
        if row['frequency'] != 'manual':
            active_schedule_ids.add(lid)

        if lid not in temp_status:
            temp_status[lid] = {'lasts': [], 'nexts': []}

        if row['last_run']:
            temp_status[lid]['lasts'].append(row['last_run'])

        created_at_str = row['created_at'] if 'created_at' in row.keys() else None
        nxt = calculate_next_run_date(row['last_run'], row['frequency'], row['custom_time'], created_at_str)

        if nxt:
            temp_status[lid]['nexts'].append(nxt)
        elif not row['last_run'] and row['frequency'] != 'manual':
            temp_status[lid]['nexts'].append(datetime.min)

    items_status = {}
    for lid, v in temp_status.items():
        last = sorted(v['lasts'], reverse=True)[0] if v['lasts'] else None
        valid_nexts = [x for x in v['nexts'] if x > datetime.min]
        nxt_str = format_next_run(min(valid_nexts)) if valid_nexts else None
        items_status[lid] = {'last_run': last, 'next_run': nxt_str}

    custom_names = {r['item_id']: r['name'] for r in db_names}

    try:
        resp = requests.get(f"{base}/Library/SelectableMediaFolders", params={'api_key': api_key}, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        for lib in data:
            if lib['Id'] in custom_names:
                lib['Name'] = custom_names[lib['Id']]
            if 'SubFolders' in lib:
                for sub in lib['SubFolders']:
                    if sub['Id'] in custom_names:
                        sub['Name'] = custom_names[sub['Id']]

    except Exception as e:
        return render_template('setup.html', error=str(e), initial_data=config['server'])

    return render_template('index.html', libraries=data, hidden_ids=hidden_ids, items_status=items_status,
                           active_schedule_ids=active_schedule_ids)


# --- API ---

@app.route('/trigger-refresh/<item_id>', methods=['POST'])
def trigger_refresh(item_id):
    config = load_config()
    if not config:
        return jsonify({"success": False, "message": "No config"}), 500

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db_connection()

    row = conn.execute("SELECT id FROM schedules WHERE library_id=? AND frequency='manual'", (item_id,)).fetchone()
    if row:
        conn.execute("UPDATE schedules SET last_run=? WHERE id=?", (now, row['id']))
    else:
        conn.execute("INSERT INTO schedules (library_id, frequency, last_run, created_at) VALUES (?, 'manual', ?, ?)",
                     (item_id, now, now))

    conn.commit()
    conn.close()

    perform_refresh(item_id, config, source="Manual")
    return jsonify({"success": True, "message": "Refresh started."})


@app.route('/api/logs', methods=['GET'])
def get_logs():
    if not os.path.exists(LOG_FILE):
        return jsonify({"logs": [], "total": 0, "pages": 0})

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    logs = []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            lines.reverse()
            total_items = len(lines)
            total_pages = (total_items + limit - 1) // limit
            sliced_lines = lines[(page - 1) * limit: page * limit]

            for line in sliced_lines:
                try:
                    logs.append(json.loads(line))
                except:
                    pass

            return jsonify({
                "logs": logs,
                "total": total_items,
                "page": page,
                "pages": total_pages
            })
    except Exception as e:
        return jsonify({"error": str(e), "logs": []})


@app.route('/api/config', methods=['GET'])
def get_config():
    cfg = load_config()
    return jsonify(cfg.get('server', {}) if cfg else {})


@app.route('/api/config', methods=['POST'])
def update_config():
    current = load_config() or {}
    success = save_config({
        "server": request.json,
        "hidden_ids": current.get('hidden_ids', [])
    })
    if success:
        log_execution("System", "-", "Settings (Config)", True, "Configuration updated")
    return jsonify({"success": success})


@app.route('/api/schedule/<lib_id>', methods=['GET'])
def get_schedules(lib_id):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM schedules WHERE library_id=? AND frequency != 'manual'", (lib_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/schedule/add', methods=['POST'])
def add_schedule():
    data = request.json
    lib_id = data.get('library_id')
    freq = data.get('frequency')
    custom_time = data.get('custom_time')

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    conn.execute('INSERT INTO schedules (library_id, frequency, custom_time, created_at) VALUES (?,?,?,?)',
                 (lib_id, freq, custom_time, now_str))
    conn.commit()
    conn.close()

    config = load_config()
    name, path = get_item_details(lib_id, config)
    desc = f"Frequency: {freq}"
    if freq == 'daily_custom' or freq == 'weekly':
        desc += f" at {custom_time}"

    log_execution(name, path, "Settings (Add Schedule)", True, desc)
    return jsonify({"success": True})


@app.route('/api/schedule/delete', methods=['POST'])
def delete_schedule():
    sched_id = request.json.get('id')
    conn = get_db_connection()
    row = conn.execute("SELECT library_id, frequency FROM schedules WHERE id=?", (sched_id,)).fetchone()
    if row:
        config = load_config()
        name, path = get_item_details(row['library_id'], config)
        conn.execute('DELETE FROM schedules WHERE id=?', (sched_id,))
        conn.commit()
        log_execution(name, path, "Settings (Delete Schedule)", True, f"Removed frequency: {row['frequency']}")
    conn.close()
    return jsonify({"success": True})


@app.route('/api/rename/<item_id>', methods=['POST'])
def rename_item(item_id):
    name = request.json.get('name')
    conn = get_db_connection()
    config = load_config()
    old_name, path = get_item_details(item_id, config)
    msg = ""

    if name and name.strip():
        if conn.execute('SELECT 1 FROM custom_names WHERE item_id=?', (item_id,)).fetchone():
            conn.execute('UPDATE custom_names SET name=? WHERE item_id=?', (name, item_id))
        else:
            conn.execute('INSERT INTO custom_names VALUES (?,?)', (item_id, name))
        msg = f"Renamed to: {name}"
    else:
        conn.execute('DELETE FROM custom_names WHERE item_id=?', (item_id,))
        msg = "Restored default name"

    conn.commit()
    conn.close()
    log_execution(old_name, path, "Settings (Rename)", True, msg)
    return jsonify({"success": True})


@app.route('/test-connection', methods=['POST'])
def test_connection():
    try:
        url = f"http://{request.json['ip']}:{request.json['port']}/emby/System/Info"
        r = requests.get(url, params={'api_key': request.json['api_key']}, timeout=5)
        return jsonify({"success": True, "server_name": r.json().get('ServerName'), "version": r.json().get('Version')})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/setup')
def setup_page():
    return render_template('setup.html', initial_data=(load_config() or {}).get('server', {}))


@app.route('/save-initial-config', methods=['POST'])
def save_initial_config():
    success = save_config({"server": request.json, "hidden_ids": []})
    return jsonify({"success": success})


@app.route('/save-settings', methods=['POST'])
def save_settings():
    c = load_config()
    c['hidden_ids'] = request.json.get('hidden_ids', [])
    return jsonify({"success": save_config(c)})


if __name__ == '__main__':
    port = int(os.environ.get('APP_PORT', 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    print(f"Starting server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)
