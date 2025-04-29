import sys
import re
import argparse
import requests
from datetime import datetime, date

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
BASE_URL = "https://app.trackingtime.co/api/v4"

# If your account/team requires specifying an account ID in the path:
# e.g. https://app.trackingtime.co/api/v4/<ACCOUNT_ID>/*
ACCOUNT_ID = 451010  # e.g. 12345

# The user ID for created tasks/time entries. Typically your own user or a coworker.
DEFAULT_USER_ID = 625297

USER_AGENT = "TimesheetTaskCreator (calum@switchbatteries.com)"

# Cache created tasks during one run so we don't create duplicates
# { (project_id, task_name) : task_id }
task_cache = {}

# ---------------------------------------------------------------------------
# API CALLS (USERS / PROJECTS)
# ---------------------------------------------------------------------------

def get_account_info(username, password):
    """GET /users?filter=ALL — list all users"""
    path = f"{ACCOUNT_ID}/users" if ACCOUNT_ID else "users"
    url = f"{BASE_URL}/{path}?filter=ALL"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    print("[+] Retrieving account info (all users)...\n")
    r = requests.get(url, auth=(username, password), headers=headers)
    if r.status_code == 200:
        print(r.text)
    else:
        print(f"[-] HTTP {r.status_code} Error: {r.text}")


def get_all_projects_raw(username, password):
    """GET /projects/ids?filter=ALL — list projects (raw)"""
    path = f"{ACCOUNT_ID}/projects/ids" if ACCOUNT_ID else "projects"
    url = f"{BASE_URL}/{path}?filter=ALL"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}

    print("[+] Retrieving all projects...\n")
    print(headers)
    r = requests.get(url, auth=(username, password), headers=headers)
    if r.status_code != 200:
        print(f"[-] HTTP {r.status_code} Error: {r.text}")
        return

    data = r.json()
    print(data)
    if "data" in data and isinstance(data["data"], list):
        projects = data["data"]
        print(f"Found {len(projects)} projects:\n")
        for p in projects:
            pid = p.get("id", "N/A")
            pname = p.get("name", "(no name)")
            pstatus = p.get("status", "N/A")
            is_archived = p.get("is_archived", False)
            print(f"  ID: {pid}, Name: {pname}, Status: {pstatus}, Archived: {is_archived}")
    else:
        print("[-] Unexpected response format, 'data' not a list?")

# ---------------------------------------------------------------------------
# TIMESHEET PARSER HELPERS
# ---------------------------------------------------------------------------

def parse_date(date_str):
    """Parse ddmmyy or ddmmyyyy → datetime.date"""
    if len(date_str) == 6:  # ddmmyy
        day, month, yy = date_str[:2], date_str[2:4], date_str[4:]
        year = "20" + yy
    elif len(date_str) == 8:  # ddmmyyyy
        day, month, year = date_str[:2], date_str[2:4], date_str[4:]
    else:
        raise ValueError(f"Unable to parse date: {date_str}")
    return datetime(int(year), int(month), int(day)).date()

def parse_time_range(line):
    """Return (start_str, end_str, description) from a timesheet line"""
    m = re.match(r"^\s*(\d{1,2}\.\d{1,2})\s*-\s*(\d{1,2}\.\d{1,2})\s+(.*)$", line.strip())
    return (m.group(1), m.group(2), m.group(3)) if m else (None, None, None)

def float_time_to_hm(time_str):
    val = float(time_str)
    return int(val), int(round((val - int(val)) * 60))

def build_iso_datetime(date_obj, h, m):
    return datetime(date_obj.year, date_obj.month, date_obj.day, h, m).strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------------------------------
# TRACKINGTIME HELPERS (PROJECTS / TASKS / EVENTS)
# ---------------------------------------------------------------------------------------

def get_all_projects(username, password):
    """Return {project_name_lower: project_id} dict plus print summary."""
    path = f"{ACCOUNT_ID}/projects" if ACCOUNT_ID else "projects"
    url = f"{BASE_URL}/{path}?filter=ALL"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}

    resp = requests.get(url, auth=(username, password), headers=headers)
    if resp.status_code != 200:
        print(f"Error fetching projects: HTTP {resp.status_code} => {resp.text}")
        return {}

    projects_list = resp.json().get("data", [])
    print(f"[+] Found {len(projects_list)} existing projects:")
    for p in projects_list:
        print(f"    ID: {p.get('id')}, Name: {p.get('name')}")
    return {p.get("name", "").lower(): p.get("id") for p in projects_list if p.get("name")}

def post_create_task(task_name, project_id, username, password, user_id):
    path = f"{ACCOUNT_ID}/tasks/add" if ACCOUNT_ID else "tasks/add"
    url = f"{BASE_URL}/{path}"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    payload = {"name": task_name, "project_id": project_id, "user_id": user_id}

    r = requests.post(url, json=payload, auth=(username, password), headers=headers)
    if r.status_code != 200:
        print(f"    HTTP {r.status_code} error creating task '{task_name}': {r.text}")
        return None

    j = r.json()
    if j.get("response", {}).get("status") != 200:
        print(f"    Error creating task '{task_name}': {j.get('response', {}).get('message')}")
        return None

    task_id = j.get("data", {}).get("id")
    print(f"    Created task '{task_name}' (ID: {task_id}) in project {project_id}")
    return task_id

def post_create_event(start_dt, end_dt, task_id, username, password, user_id, notes=None):
    path = f"{ACCOUNT_ID}/events/add" if ACCOUNT_ID else "events/add"
    url = f"{BASE_URL}/{path}"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}

    dur = int((datetime.strptime(end_dt, "%Y-%m-%d %H:%M:%S") - datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S")).total_seconds())
    payload = {"task_id": task_id, "user_id": user_id, "start": start_dt, "end": end_dt, "duration": dur}
    if notes:
        payload["notes"] = notes

    r = requests.post(url, json=payload, auth=(username, password), headers=headers)
    if r.status_code != 200:
        print(f"      ✗ HTTP {r.status_code} error: {r.text}")
        return
    if r.json().get("response", {}).get("status") == 200:
        print(f"      ✓ Created event from {start_dt} to {end_dt}")
    else:
        print(f"      ✗ Error creating event: {r.json().get('response', {}).get('message')}")

# ---------------------------------------------------------------------------------------
# FETCH TIME ENTRIES (NEW FEATURE)
# ---------------------------------------------------------------------------------------

def get_user_time_entries(username, password, from_date=None, to_date=None, page_size=20000, user_id=None):
    """Fetch all entries for user_id between from_date and to_date (inclusive)."""
    path = f"{ACCOUNT_ID}/events/min" if ACCOUNT_ID else "events/min"
    url = f"{BASE_URL}/{path}"

    # If dates not given, default to a very wide window (Jan 1 2000 → today)
    if not from_date:
        from_date = "2000-01-01"
    if not to_date:
        to_date = date.today().strftime("%Y-%m-%d")

    params = {
        "filter": "USER",
        "id": user_id,
        "from": from_date,
        "to": to_date,
        "order": "asc",
        "page_size": page_size,
    }

    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    print(f"[+] Fetching time entries for user {user_id} from {from_date} to {to_date} ...")

    all_entries, page = [], 0
    while True:
        params["page"] = page
        r = requests.get(url, params=params, auth=(username, password), headers=headers)
        if r.status_code != 200:
            print(f"[-] HTTP {r.status_code} error retrieving entries: {r.text}")
            break
        page_data = r.json().get("data", [])
        if not page_data:
            break
        all_entries.extend(page_data)
        if len(page_data) < page_size:
            break
        page += 1

    print(f"[+] Retrieved {len(all_entries)} entries:\n")
    for ev in all_entries:
        eid, start, end, dur = ev.get("id"), ev.get("s"), ev.get("e"), ev.get("d", 0)
        project, task = ev.get("p"), ev.get("t")
        hh, mm = divmod(dur // 60, 60)
        print(f"  [{eid}] {start} -> {end} | {hh:02d}:{mm:02d} | {project} / {task}")

# ---------------------------------------------------------------------------------------
# FETCH TIME ENTRIES COUNT 
# ---------------------------------------------------------------------------------------

def get_time_entries_count(username, password, from_date, to_date, filter_type="USER", filter_id=None):
    """Get count of time entries for a user or company in a date range."""
    path = f"{ACCOUNT_ID}/events/count" if ACCOUNT_ID else "events/count"
    url = f"{BASE_URL}/{path}"
    
    # Validate parameters
    if not from_date or not to_date:
        print("[-] Error: from_date and to_date are required for counting entries")
        return
        
    params = {
        "filter": filter_type,
        "from": from_date,
        "to": to_date,
    }
    
    # Add ID if provided (required for USER filter)
    if filter_id:
        params["id"] = filter_id
    
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    print(f"[+] Counting time entries for {filter_type.lower()} " + 
          (f"ID {filter_id} " if filter_id else "") + 
          f"from {from_date} to {to_date} ...")
    print("url:", url)
    print("Headers:", headers)
    print("Parameters:", params)
    r = requests.get(url, params=params, auth=(username, password), headers=headers)
    if r.status_code != 200:
        print(f"[-] HTTP {r.status_code} error retrieving entry count: {r.text}")
        return
        
    data = r.json()
    if data.get("response", {}).get("status") == 200:
        count = data.get("data", {}).get("count", 0)
        print(f"[+] Found {count} time entries for the specified period")
    else:
        print(f"[-] API error: {data.get('response', {}).get('message')}")

# ---------------------------------------------------------------------------------------
# FETCH TEAMS/ACCOUNTS
# ---------------------------------------------------------------------------------------

def get_teams(username, password):
    """Get all teams/accounts the user has access to."""
    url = f"{BASE_URL}/teams"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    
    print("[+] Retrieving teams/accounts...\n")
    r = requests.get(url, auth=(username, password), headers=headers)
    if r.status_code != 200:
        print(f"[-] HTTP {r.status_code} error retrieving teams: {r.text}")
        return
    
    data = r.json()
    if data.get("response", {}).get("status") == 200 and "data" in data:
        teams = data["data"]
        print(f"[+] Found {len(teams)} teams/accounts:")
        for team in teams:
            account_id = team.get("account_id", "N/A")
            company = team.get("company", "(No name)")
            role = team.get("role", "N/A")
            is_default = team.get("is_default", False)
            status = team.get("status", "N/A")
            print(f"    ID: {account_id}, Name: {company}, Role: {role}, " +
                  f"Status: {status}" + (" [DEFAULT]" if is_default else ""))
    else:
        print(f"[-] API error: {data.get('response', {}).get('message')}")

# ---------------------------------------------------------------------------------------
# TIMESHEET FILE PROCESSOR
# ---------------------------------------------------------------------------------------

def process_timesheet_file(filepath, username, password, user_id):
    print("[+] Fetching existing projects...")
    project_map = get_all_projects(username, password)

    current_date, in_block, current_project = None, False, None
    with open(filepath, "r", encoding="utf-8") as f:
        for raw in f:
            line, stripped = raw.rstrip("\n"), raw.strip()
            if not stripped:
                continue

            if stripped.startswith("# date"):
                current_date = parse_date(stripped.split()[2]) if len(stripped.split()) == 3 else None
                in_block, current_project = False, None
                continue
            if stripped.lower() == "timesheet":
                in_block, current_project = True, None
                continue

            if in_block and current_date:
                indent = len(line) - len(line.lstrip(" "))
                if 8 <= indent < 12:
                    current_project = stripped
                    continue
                if indent >= 12:
                    st, et, desc = parse_time_range(stripped)
                    if not st:
                        continue
                    sh, sm = float_time_to_hm(st)
                    eh, em = float_time_to_hm(et)
                    start_dt = build_iso_datetime(current_date, sh, sm)
                    end_dt = build_iso_datetime(current_date, eh, em)

                    proj_id = project_map.get(current_project.lower()) if current_project else None
                    if not proj_id:
                        print(f"Project '{current_project}' not found. Skipping task '{desc}'")
                        continue
                    key = (proj_id, desc)
                    task_id = task_cache.get(key) or post_create_task(desc, proj_id, username, password, user_id)
                    if not task_id:
                        continue
                    task_cache[key] = task_id
                    post_create_event(start_dt, end_dt, task_id, username, password, user_id,
                                      notes=f"Auto entry for project '{current_project}'")

# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="TrackingTime helper: parse timesheets or query the API.")
    p.add_argument("timesheet_file", nargs="?", help="Timesheet file path")
    p.add_argument("--username", required=True, help="TrackingTime username (email)")
    p.add_argument("--password", required=True, help="TrackingTime password")
    p.add_argument("--user-id", type=int, help="User ID for tasks/time entries (default: %(default)s)",
                   default=DEFAULT_USER_ID)

    p.add_argument("--get-info", action="store_true", help="List all users (raw JSON)")
    p.add_argument("--get-projects", action="store_true", help="List all projects")
    p.add_argument("--get-teams", action="store_true", help="List all teams/accounts")
    p.add_argument("--get-time-tracking", action="store_true", help="List all time entries for USER_ID")
    p.add_argument("--get-time-count", action="store_true", help="Get count of time entries in a date range")
    p.add_argument("--count-filter", choices=["USER", "COMPANY"], default="USER", 
                  help="Filter type for time count: user or company-wide (default: %(default)s)")
    p.add_argument("--from-date", metavar="YYYY-MM-DD", help="Start date for time queries")
    p.add_argument("--to-date", metavar="YYYY-MM-DD", help="End date for time queries (inclusive)")

    args = p.parse_args()

    if args.get_info:
        get_account_info(args.username, args.password)
        return
    if args.get_projects:
        get_all_projects_raw(args.username, args.password)
        return
    if args.get_teams:
        get_teams(args.username, args.password)
        return
    if args.get_time_tracking:
        get_user_time_entries(args.username, args.password, args.from_date, args.to_date, user_id=args.user_id)
        return
    if args.get_time_count:
        filter_id = args.user_id if args.count_filter == "USER" else DEFAULT_USER_ID
        get_time_entries_count(args.username, args.password, args.from_date, args.to_date, 
                             args.count_filter, filter_id)
        return
    if args.timesheet_file:
        process_timesheet_file(args.timesheet_file, args.username, args.password, args.user_id)
        return

    print("No action specified.")
    p.print_help()

if __name__ == "__main__":
    main()
