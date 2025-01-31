import sys
import re
import argparse
import requests
from datetime import datetime

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
BASE_URL = "https://app.trackingtime.co/api/v4"

# If your account/team requires specifying an account ID in the path:
# e.g. https://app.trackingtime.co/api/v4/<ACCOUNT_ID>/*
ACCOUNT_ID = None  # e.g. 12345

# The user ID for created tasks/time entries. Typically your own user or a coworker.
USER_ID = 123456

USER_AGENT = "TimesheetTaskCreator (calum@switchbatteries.com)"

# ---------------------------------------------------------------------------
# API CALLS
# ---------------------------------------------------------------------------

def get_account_info(username, password):
    """
    Calls GET /api/v4/users?filter=ALL to list all users in the account.
    Prints the raw JSON response.
    """
    if ACCOUNT_ID:
        url = f"{BASE_URL}/{ACCOUNT_ID}/users?filter=ALL"
    else:
        url = f"{BASE_URL}/users?filter=ALL"

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json"
    }

    print("[+] Retrieving account info (all users)...\n")
    r = requests.get(url, auth=(username, password), headers=headers)
    if r.status_code == 200:
        print(r.text)  # Raw JSON
    else:
        print(f"[-] HTTP {r.status_code} Error: {r.text}")


def get_all_projects_raw(username, password):
    """
    Calls GET /api/v4/projects?filter=ALL to list all projects in the account.
    Prints a short summary for each project: (ID, Name, Status, etc.)
    """
    if ACCOUNT_ID:
        url = f"{BASE_URL}/{ACCOUNT_ID}/projects?filter=ALL"
    else:
        url = f"{BASE_URL}/projects?filter=ALL"

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json"
    }

    print("[+] Retrieving all projects...\n")
    r = requests.get(url, auth=(username, password), headers=headers)
    if r.status_code == 200:
        data = r.json()
        print(data)
        if "data" in data and isinstance(data["data"], list):
            projects = data["data"]
            print(f"Found {len(projects)} projects:\n")

            for p in projects:
                pid = p.get("id", "N/A")
                pname = p.get("name", "(no name)")
                pstatus = p.get("status", "N/A")        # e.g. ACTIVE / ARCHIVED
                is_archived = p.get("is_archived", False)
                print(f"  ID: {pid}, Name: {pname}, Status: {pstatus}, Archived: {is_archived}")
        else:
            print("[-] Unexpected response format, 'data' not a list?")
    else:
        print(f"[-] HTTP {r.status_code} Error: {r.text}")


# ---------------------------------------------------------------------------
# HELPERS FOR TIMESHEET PARSING (if used)
# ---------------------------------------------------------------------------

def parse_date(date_str):
    """
    Parses a date of the form ddmmyy or ddmmyyyy into a datetime.date object.
    E.g. '290125' => 2025-01-29
    """
    if len(date_str) == 6:  # ddmmyy
        day = date_str[0:2]
        month = date_str[2:4]
        year = "20" + date_str[4:6]
    elif len(date_str) == 8:  # ddmmyyyy
        day = date_str[0:2]
        month = date_str[2:4]
        year = date_str[4:8]
    else:
        raise ValueError(f"Unable to parse date: {date_str}")
    return datetime(int(year), int(month), int(day)).date()

def parse_time_range(line):
    """
    Given something like '9.00 - 12.00 Software design PCS sub controller',
    returns (start_time_str, end_time_str, task_name)
    """
    pattern = r"^\s*(\d{1,2}\.\d{1,2})\s*-\s*(\d{1,2}\.\d{1,2})\s+(.*)$"
    match = re.match(pattern, line.strip())
    if not match:
        return None, None, None
    start_time_str = match.group(1)  # e.g. "9.00"
    end_time_str   = match.group(2)  # e.g. "12.00"
    remainder      = match.group(3)  # e.g. "Software design PCS sub controller"
    return start_time_str, end_time_str, remainder

def float_time_to_hm(time_str):
    """
    Converts '9.00' -> (9, 0), '9.30' -> (9, 30), '13.5' -> (13, 30), etc.
    """
    val = float(time_str)
    hours = int(val)
    minutes = int(round((val - hours) * 60))
    return hours, minutes

def build_iso_datetime(date_obj, hours, minutes):
    """
    Return 'YYYY-MM-DD HH:MM:SS'
    """
    dt = datetime(date_obj.year, date_obj.month, date_obj.day, hours, minutes, 0)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------------------------------
# TRACKINGTIME API CALLS
# ---------------------------------------------------------------------------------------

def get_all_projects(username, password):
    """
    Lists all projects in the account (filter=ALL) and returns a dict
    mapping { project_name_lowercase: project_id }
    """
    # Construct endpoint
    if ACCOUNT_ID:
        url = f"{BASE_URL}/{ACCOUNT_ID}/projects?filter=ALL"
    else:
        url = f"{BASE_URL}/projects?filter=ALL"

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }

    resp = requests.get(url, auth=(username, password), headers=headers)
    if resp.status_code == 200:
        j = resp.json()
        # j should look like {"response": {...}, "data": [ {...}, {...}, ... ]}
        projects_list = j.get("data", [])
        mapping = {}
        for p in projects_list:
            # each "p" is a project object with "id", "name", etc.
            pid = p.get("id")
            pname = p.get("name", "")
            if pname:
                mapping[pname.lower()] = pid
        print(mapping)
        return mapping
    else:
        print(f"Error fetching projects: HTTP {resp.status_code} => {resp.text}")
        return {}

def post_create_task(task_name, project_id, username, password):
    """
    Creates a new task with the given name in the specified project.
    Endpoint: /api/v4/tasks/add

    Returns the new task's ID, or None if error.
    """
    if ACCOUNT_ID:
        url = f"{BASE_URL}/{ACCOUNT_ID}/tasks/add"
    else:
        url = f"{BASE_URL}/tasks/add"

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json"
    }

    payload = {
        "name": task_name,
        "project_id": project_id,
        "user_id": USER_ID
    }

    resp = requests.post(url, json=payload, auth=(username, password), headers=headers)
    if resp.status_code == 200:
        j = resp.json()
        status = j.get("response", {}).get("status")
        if status == 200:
            data = j.get("data", {})
            task_id = data.get("id")
            print(f"    Created task '{task_name}' (ID: {task_id}) in project {project_id}")
            return task_id
        else:
            msg = j.get("response", {}).get("message", "Unknown error")
            print(f"    Error creating task '{task_name}': {msg}")
            return None
    else:
        print(f"    HTTP {resp.status_code} error creating task '{task_name}': {resp.text}")
        return None

def post_create_event(start_dt, end_dt, task_id, username, password, notes=None):
    """
    Creates a time entry (event) for the given task_id, referencing user_id, start/end times.
    Endpoint: /api/v4/events/add
    """
    start_obj = datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S")
    end_obj   = datetime.strptime(end_dt,   "%Y-%m-%d %H:%M:%S")
    duration_seconds = int((end_obj - start_obj).total_seconds())

    if ACCOUNT_ID:
        url = f"{BASE_URL}/{ACCOUNT_ID}/events/add"
    else:
        url = f"{BASE_URL}/events/add"

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json"
    }

    payload = {
        "task_id": task_id,
        "user_id": USER_ID,
        "start": start_dt,
        "end": end_dt,
        "duration": duration_seconds
    }
    if notes:
        payload["notes"] = notes

    resp = requests.post(url, json=payload, auth=(username, password), headers=headers)
    if resp.status_code == 200:
        j = resp.json()
        status = j.get("response", {}).get("status")
        if status == 200:
            print(f"      ✓ Created event from {start_dt} to {end_dt}")
        else:
            msg = j.get("response", {}).get("message", "Unknown error")
            print(f"      ✗ Error creating event: {msg}")
    else:
        print(f"      ✗ HTTP {resp.status_code} error: {resp.text}")

# ---------------------------------------------------------------------------------------
# MAIN TIMESHEET PARSING
# ---------------------------------------------------------------------------------------

def process_timesheet_file(filepath, username, password):
    """
    Reads a file in the format:

    # date 290125
        timesheet
            Centurion
                9.00 - 12.00 Software design
            LandCruiser
                12.30 - 17.00 Another Task

    Only adds new tasks to *existing* projects in TT that match the project name (case-insensitive).
    If project doesn't exist, we skip it (or you could error).
    """
    # 1. Fetch all existing projects from your account
    print("[+] Fetching existing projects...")
    project_map = get_all_projects(username, password)
    # project_map = { "centurion": 123, "landcruiser": 456, ... }

    # 2. We'll parse the file, find tasks, and attach them to existing projects only
    current_date = None
    in_timesheet_block = False
    current_project_name = None

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if not stripped:
                continue

            # Check for date line
            if stripped.startswith("# date"):
                # e.g. "# date 290125"
                parts = stripped.split()
                if len(parts) == 3:
                    date_str = parts[2]
                    current_date = parse_date(date_str)
                else:
                    current_date = None
                in_timesheet_block = False
                current_project_name = None
                continue

            # Check for "timesheet"
            if stripped.lower() == "timesheet":
                in_timesheet_block = True
                current_project_name = None
                continue

            # If in timesheet block, parse project lines or tasks
            if in_timesheet_block and current_date:
                indent = len(line) - len(line.lstrip(" "))

                # Project line
                if 8 <= indent < 12:
                    current_project_name = stripped
                    continue

                # Task line
                if indent >= 12:
                    start_time_str, end_time_str, task_desc = parse_time_range(stripped)
                    if start_time_str is None:
                        continue

                    # Convert times
                    sh, sm = float_time_to_hm(start_time_str)
                    eh, em = float_time_to_hm(end_time_str)

                    start_dt = build_iso_datetime(current_date, sh, sm)
                    end_dt   = build_iso_datetime(current_date, eh, em)

                    # Find the matching project
                    if not current_project_name:
                        print(f"No project found for line: {stripped}")
                        continue

                    proj_id = project_map.get(current_project_name.lower())
                    if not proj_id:
                        print(f"Project '{current_project_name}' not found in TT. Skipping this task: {task_desc}")
                        continue

                    # Create or reuse the task
                    task_key = (proj_id, task_desc)
                    if task_key not in task_cache:
                        # create it
                        task_id = post_create_task(task_desc, proj_id, username, password)
                        if not task_id:
                            continue  # skip if creation failed
                        task_cache[task_key] = task_id
                    else:
                        task_id = task_cache[task_key]

                    # Create time entry
                    note_str = f"Auto time entry for existing project '{current_project_name}'"
                    post_create_event(start_dt, end_dt, task_id, username, password, notes=note_str)

def main():
    parser = argparse.ArgumentParser(
        description="A script that can list users, list projects, or parse a timesheet file."
    )
    parser.add_argument(
        "timesheet_file",
        nargs="?",
        help="Path to the timesheet file (omit if using --get-info or --get-projects)."
    )
    parser.add_argument("--username", required=True, help="TrackingTime username (email).")
    parser.add_argument("--password", required=True, help="TrackingTime password.")

    parser.add_argument(
        "--get-info",
        action="store_true",
        help="List all users in the account (raw JSON)."
    )
    parser.add_argument(
        "--get-projects",
        action="store_true",
        help="List all projects in the account."
    )

    args = parser.parse_args()

    # If user requested to list users:
    if args.get_info:
        get_account_info(args.username, args.password)
        return

    # If user requested to list projects:
    if args.get_projects:
        get_all_projects_raw(args.username, args.password)
        return

    # Otherwise, parse timesheet (if file provided)
    if args.timesheet_file:
        process_timesheet_file(args.timesheet_file, args.username, args.password)
    else:
        print("No action specified (no file, and not listing users or projects).")
        parser.print_help()


if __name__ == "__main__":
    main()
