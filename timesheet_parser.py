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
DEFAULT_ACCOUNT_ID = 451010  # e.g. 12345

# The user ID for created tasks/time entries. Typically your own user or a coworker.
DEFAULT_USER_ID = 625297

USER_AGENT = "TimesheetTaskCreator (calum@switchbatteries.com)"

# Cache created tasks during one run so we don't create duplicates
# { (project_id, task_name) : task_id }
task_cache = {}

# ---------------------------------------------------------------------------
# API CALLS (USERS / PROJECTS)
# ---------------------------------------------------------------------------

def get_account_info(username, password, account_id=None):
    """GET /users?filter=ALL — list all users"""
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/users" if account_id else "users"
    url = f"{BASE_URL}/{path}?filter=ALL"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    print("[+] Retrieving account info (all users)...\n")
    r = requests.get(url, auth=(username, password), headers=headers)
    if r.status_code == 200:
        print(r.text)
    else:
        print(f"[-] HTTP {r.status_code} Error: {r.text}")


def get_all_projects_raw(username, password, account_id=None):
    """GET /projects?filter=ALL — list projects (raw)"""
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/projects" if account_id else "projects"
    url = f"{BASE_URL}/{path}?filter=ALL"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}

    print("[+] Retrieving all projects...\n")
    print(headers)
    r = requests.get(url, auth=(username, password), headers=headers)
    if r.status_code != 200:
        print(f"[-] HTTP {r.status_code} Error: {r.text}")
        return

    data = r.json()
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

def get_all_projects(username, password, account_id=None):
    """Return {project_name_lower: project_id} dict plus print summary."""
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/projects" if account_id else "projects"
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
    return {p.get("name", "").lower().strip(): p.get("id") for p in projects_list if p.get("name")}

def post_create_task(task_name, project_id, username, password, user_id, account_id=None, project_name=None):
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/tasks/add" if account_id else "tasks/add"
    url = f"{BASE_URL}/{path}"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    payload = {"name": task_name, "project_id": str(project_id), "user_id": str(user_id)}

    r = requests.post(url, json=payload, auth=(username, password), headers=headers)
    if r.status_code != 200:
        print(f"    HTTP {r.status_code} error creating task '{task_name}': {r.text}")
        return None

    j = r.json()
    if j.get("response", {}).get("status") != 200:
        print(f"    Error creating task '{task_name}': {j.get('response', {}).get('message')}")
        return None

    task_id = j.get("data", {}).get("id")
    if project_name:
        print(f"    Created task '{task_name}' (ID: {task_id}) in project {project_id} ('{project_name}')")
    else:
        print(f"    Created task '{task_name}' (ID: {task_id}) in project {project_id}")
    return task_id

def post_create_event(start_dt, end_dt, task_id, username, password, user_id, notes=None, account_id=None):
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/events/add" if account_id else "events/add"
    url = f"{BASE_URL}/{path}"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}

    dur = int((datetime.strptime(end_dt, "%Y-%m-%d %H:%M:%S") - datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S")).total_seconds())
    payload = {"task_id": str(task_id), "user_id": str(user_id), "start": start_dt, "end": end_dt, "duration": dur}
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

def get_user_time_entries(username, password, from_date=None, to_date=None, page_size=20000, user_id=None, account_id=None):
    """Fetch all entries for user_id between from_date and to_date (inclusive)."""
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/events/min" if account_id else "events/min"
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

def get_time_entries_count(username, password, from_date, to_date, filter_type="USER", filter_id=None, account_id=None):
    """Get count of time entries for a user or company in a date range."""
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/events/count" if account_id else "events/count"
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

def process_timesheet_file(filepath, username, password, user_id, account_id=None):
    print("[+] Fetching existing projects...")
    project_map = get_all_projects(username, password, account_id)
    
    # Dictionary to cache project tasks
    project_tasks_cache = {}

    current_date = None
    in_block = False
    current_project = None
    current_task = None
    
    with open(filepath, "r", encoding="utf-8") as f:
        for raw in f:
            line, stripped = raw.rstrip("\n"), raw.strip()
            if not stripped:
                continue

            if stripped.startswith("# date"):
                current_date = parse_date(stripped.split()[2]) if len(stripped.split()) == 3 else None
                in_block, current_project, current_task = False, None, None
                continue
                
            if stripped.lower() == "timesheet":
                in_block = True
                current_project, current_task = None, None
                continue

            if in_block and current_date:
                indent = len(line) - len(line.lstrip(" "))
                
                # Project line (indentation level 1)
                if 8 <= indent < 12:
                    current_project = stripped
                    current_task = None
                    
                    # Fetch tasks for this project if not already cached
                    proj_id = project_map.get(current_project.lower())
                    if proj_id and proj_id not in project_tasks_cache:
                        print(f"[+] Fetching tasks for project '{current_project}' (ID: {proj_id})...")
                        tasks = get_project_tasks(username, password, proj_id, account_id=account_id)
                        project_tasks_cache[proj_id] = tasks
                    continue
                    
                # Task line (indentation level 2)
                elif 12 <= indent < 16:
                    current_task = stripped
                    continue
                
                # Time entry line (indentation level 3)
                elif indent >= 16 and current_project and current_task:
                    st, et, desc = parse_time_range(stripped)
                    if not st:
                        continue
                        
                    sh, sm = float_time_to_hm(st)
                    eh, em = float_time_to_hm(et)
                    start_dt = build_iso_datetime(current_date, sh, sm)
                    end_dt = build_iso_datetime(current_date, eh, em)

                    proj_id = project_map.get(current_project.lower()) if current_project else None
                    if not proj_id:
                        print(f"Project '{current_project}' not found. Skipping entry for task '{current_task}': '{desc}'")
                        continue
                    
                    # Try to find a matching task in the project's tasks
                    task_id = None
                    if proj_id in project_tasks_cache:
                        # Look for exact or similar match
                        for task in project_tasks_cache[proj_id]:
                            task_name = task.get("name", "")
                            # Check if task name contains our current task or vice versa
                            if (current_task.lower() in task_name.lower() or 
                                task_name.lower() in current_task.lower() or
                                desc.lower() in task_name.lower()):
                                task_id = task.get("id")
                                print(f"[+] Matched task '{current_task}' with existing task '{task_name}' (ID: {task_id})")
                                break
                    
                    if not task_id:
                        print(f"[-] No matching task found for '{current_task}' in project '{current_project}'. Skipping.")
                        continue
                    
                    # Create the time entry with the description as notes
                    notes = f"{desc} (Auto entry for task '{current_task}' in project '{current_project}')"
                    post_create_event(start_dt, end_dt, task_id, username, password, user_id, notes=notes, account_id=account_id)

# ---------------------------------------------------------------------------------------
# FETCH PROJECT TIME ENTRIES 
# ---------------------------------------------------------------------------------------

def get_project_time_entries(username, password, project_id, from_date=None, to_date=None, page_size=20000, account_id=None, user_id=None):
    """Fetch all time entries for a specific project between from_date and to_date (inclusive)."""
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/events/min" if account_id else "events/min"
    url = f"{BASE_URL}/{path}"

    # If dates not given, default to a very wide window (Jan 1 2000 → today)
    if not from_date:
        from_date = "2000-01-01"
    if not to_date:
        to_date = date.today().strftime("%Y-%m-%d")

    params = {
        "filter": "PROJECT",
        "id": project_id,
        "from": from_date,
        "to": to_date,
        "order": "asc",
        "page_size": page_size,
    }

    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    print(f"[+] Fetching time entries for project {project_id} from {from_date} to {to_date} ...")

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

    # Filter by user_id if specified
    if user_id:
        user_entries = [ev for ev in all_entries if str(ev.get("uid")) == str(user_id)]
        print(f"[+] Retrieved {len(user_entries)} entries for project {project_id} and user {user_id} (out of {len(all_entries)} total entries):\n")
        entries_to_display = user_entries
    else:
        print(f"[+] Retrieved {len(all_entries)} entries for project {project_id}:\n")
        entries_to_display = all_entries
    
    for ev in entries_to_display:
        eid, start, end, dur = ev.get("id"), ev.get("s"), ev.get("e"), ev.get("d", 0)
        user, task = ev.get("u"), ev.get("t")
        hh, mm = divmod(dur // 60, 60)
        print(f"  [{eid}] {start} -> {end} | {hh:02d}:{mm:02d} | User: {user} | Task: {task}")
    
    return entries_to_display

# ---------------------------------------------------------------------------------------
# FETCH PROJECT TASKS
# ---------------------------------------------------------------------------------------

def get_project_tasks(username, password, project_id, include_archived=False, page_size=500, account_id=None):
    """Fetch all tasks for a specific project using pagination."""
    account_id = account_id or DEFAULT_ACCOUNT_ID
    path = f"{account_id}/tasks/paginated" if account_id else "tasks/paginated"
    url = f"{BASE_URL}/{path}"
    
    # Define filter based on include_archived parameter
    task_filter = "ALL" if include_archived else "ACTIVE"
    
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    print(f"[+] Fetching tasks and filtering for project {project_id}...")
    
    project_tasks = []
    page = 0
    total_tasks_processed = 0
    
    while True:
        params = {
            "filter": task_filter,
            "page": page,
            "page_size": page_size
        }
        
        r = requests.get(url, params=params, auth=(username, password), headers=headers)
        if r.status_code != 200:
            print(f"[-] HTTP {r.status_code} error retrieving tasks: {r.text}")
            break
            
        data = r.json()
        tasks = data.get("data", [])
        
        if not tasks:
            break
            
        # Filter tasks for the requested project_id
        matching_tasks = [task for task in tasks if str(task.get("project_id")) == str(project_id)]
        project_tasks.extend(matching_tasks)
        
        total_tasks_processed += len(tasks)
        print(f"  Processed page {page}: Found {len(matching_tasks)} matching tasks from {len(tasks)} total")
        
        # If we received fewer tasks than page_size, we've reached the end
        if len(tasks) < page_size:
            break
            
        page += 1
    
    print(f"[+] Retrieved {len(project_tasks)} tasks for project {project_id} (processed {total_tasks_processed} total tasks):\n")
    
    for task in project_tasks:
        task_id = task.get("id")
        name = task.get("name")
        status = "Archived" if task.get("is_archived") else "Active"
        estimated_time = task.get("loc_estimated_time", "00:00")
        worked_hours = task.get("loc_worked_hours", "00:00") 
        created_at = task.get("created_at")
        print(f"  [{task_id}] {name} | Status: {status} | Est: {estimated_time} | Worked: {worked_hours} | Created: {created_at}")
    
    return project_tasks

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
    p.add_argument("--account-id", type=int, help="Account ID for API operations (default: %(default)s)",
                   default=DEFAULT_ACCOUNT_ID)

    p.add_argument("--get-info", action="store_true", help="List all users (raw JSON)")
    p.add_argument("--get-projects", action="store_true", help="List all projects")
    p.add_argument("--get-teams", action="store_true", help="List all teams/accounts")
    p.add_argument("--get-time-tracking", action="store_true", help="List all time entries for USER_ID")
    p.add_argument("--get-time-count", action="store_true", help="Get count of time entries in a date range")
    p.add_argument("--get-project-events", action="store_true", help="List all time entries for a specific project")
    p.add_argument("--get-project-tasks", action="store_true", help="List all tasks for a specific project")
    p.add_argument("--project-id", type=int, help="Project ID for project-specific queries")
    p.add_argument("--include-archived", action="store_true", help="Include archived tasks when listing project tasks")
    p.add_argument("--count-filter", choices=["USER", "COMPANY"], default="USER", 
                  help="Filter type for time count: user or company-wide (default: %(default)s)")
    p.add_argument("--from-date", metavar="YYYY-MM-DD", help="Start date for time queries")
    p.add_argument("--to-date", metavar="YYYY-MM-DD", help="End date for time queries (inclusive)")

    args = p.parse_args()

    if args.get_info:
        get_account_info(args.username, args.password, args.account_id)
        return
    if args.get_projects:
        get_all_projects_raw(args.username, args.password, args.account_id)
        return
    if args.get_teams:
        get_teams(args.username, args.password)
        return
    if args.get_time_tracking:
        get_user_time_entries(args.username, args.password, args.from_date, args.to_date, 
                            user_id=args.user_id, account_id=args.account_id)
        return
    if args.get_project_events:
        if not args.project_id:
            print("[-] Error: --project-id is required when using --get-project-events")
            return
        get_project_time_entries(args.username, args.password, args.project_id, args.from_date, args.to_date,
                              account_id=args.account_id, user_id=args.user_id)
        return
    if args.get_project_tasks:
        if not args.project_id:
            print("[-] Error: --project-id is required when using --get-project-tasks")
            return
        get_project_tasks(args.username, args.password, args.project_id, args.include_archived,
                        account_id=args.account_id)
        return
    if args.get_time_count:
        filter_id = args.user_id if args.count_filter == "USER" else None
        get_time_entries_count(args.username, args.password, args.from_date, args.to_date, 
                             args.count_filter, filter_id, args.account_id)
        return
    if args.timesheet_file:
        process_timesheet_file(args.timesheet_file, args.username, args.password, args.user_id, args.account_id)
        return

    print("No action specified.")
    p.print_help()

if __name__ == "__main__":
    main()
