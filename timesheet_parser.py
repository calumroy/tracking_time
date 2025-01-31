import sys
import re
import argparse
import requests
from datetime import datetime

# ---------------------------------------------------------------------------
# CONFIGURATION (Customize as needed)
# ---------------------------------------------------------------------------
BASE_URL = "https://app.trackingtime.co/api/v4"

# If your account/team requires specifying an account ID in the URL path
# e.g. https://app.trackingtime.co/api/v4/<ACCOUNT_ID>/*, set it here:
ACCOUNT_ID = None  # e.g. 12345

# The user ID that we assign timesheet entries to (your ID or a coworker's ID)
USER_ID = 625297  

USER_AGENT = "TimesheetParser (myemail@example.com)"

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def list_users(username, password):
    """
    Lists all users in the current account via GET /api/v4/users.
    Only admins / project managers can do this.
    """
    # If you need an account ID in the path, adjust here
    # For example: f"{BASE_URL}/{ACCOUNT_ID}/users"
    if ACCOUNT_ID:
        url = f"{BASE_URL}/{ACCOUNT_ID}/users?filter=ALL"
    else:
        url = f"{BASE_URL}/users?filter=ALL"  # or filter=ACTIVE, etc.

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }

    print("[+] Fetching list of users...")
    resp = requests.get(url, auth=(username, password), headers=headers)

    if resp.status_code == 200:
        data = resp.json()
        # Should look like: {"response": {...}, "data": [ {..user1..}, {..user2..}, ... ]}
        if "data" in data and isinstance(data["data"], list):
            users_list = data["data"]
            print(f"\nFound {len(users_list)} users:\n")
            for user in users_list:
                uid = user.get("id", "N/A")
                name = user.get("name", "")
                surname = user.get("surname", "")
                email = user.get("email", "")
                role = user.get("role", "")
                print(f"  ID: {uid:<6} | {name} {surname} | {email} | Role: {role}")
            print("\nDone.")
        else:
            print("[-] Could not parse user list. Check response format.")
    else:
        print(f"[-] HTTP Error {resp.status_code}: {resp.text}")

def parse_date(date_str):
    """
    Parses a date of the form ddmmyy or ddmmyyyy into a datetime.date object.
    For example '290125' => 2025-01-29
    """
    # You can adjust if your input is ddmmyyyy, etc.
    # Here, we assume '290125' => dd mm yy => 29 01 25 => 2025-01-29
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
    Parse lines like:
        9.00 - 12.00 Software design PCS sub controller
    Return (start_time_str, end_time_str, description) or (None, None, None)
    """
    pattern = r"^\s*(\d{1,2}\.\d{1,2})\s*-\s*(\d{1,2}\.\d{1,2})\s+(.*)$"
    match = re.match(pattern, line.strip())
    if not match:
        return None, None, None
    start_time_str = match.group(1) 
    end_time_str   = match.group(2)
    remainder      = match.group(3)
    return start_time_str, end_time_str, remainder


def float_time_to_hm(time_str):
    """
    Converts '9.00' => (9, 0), '9.30' => (9, 30), '13.5' => (13, 30), etc.
    """
    val = float(time_str)
    hours = int(val)
    minutes = int(round((val - hours) * 60))
    return hours, minutes


def build_iso_datetime(date_obj, hours, minutes):
    """
    Builds a string 'YYYY-mm-dd HH:MM:SS' from date + hour + minute.
    """
    dt = datetime(date_obj.year, date_obj.month, date_obj.day, hours, minutes, 0)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_time_entry(
    start_dt,
    end_dt,
    notes,
    username,
    password
):
    """
    POST to /api/v4/events/add to create a single time entry.
    """
    # Calculate duration in seconds
    start_obj = datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S")
    end_obj   = datetime.strptime(end_dt,   "%Y-%m-%d %H:%M:%S")
    duration_seconds = int((end_obj - start_obj).total_seconds())

    # Prepare the JSON payload
    payload = {
        "duration": duration_seconds,
        "user_id": USER_ID,
        "start": start_dt,
        "end": end_dt,
        "notes": notes,
        # Optional:
        # "task_id": 12345,
        # "project_id": 12345,
        # "timezone": "GMT+00:00"
    }

    if ACCOUNT_ID:
        url = f"{BASE_URL}/{ACCOUNT_ID}/events/add"
    else:
        url = f"{BASE_URL}/events/add"

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }

    print(f"Creating entry from {start_dt} to {end_dt}, notes={notes!r}")
    r = requests.post(url, json=payload, auth=(username, password), headers=headers)
    if r.status_code == 200:
        resp_json = r.json()
        status = resp_json.get("response", {}).get("status")
        if status == 200:
            print("  ✓ Created successfully")
        else:
            msg = resp_json.get("response", {}).get("message", "Unknown error")
            print(f"  ✗ Error in response: {msg}")
    else:
        print(f"  ✗ HTTP Error {r.status_code}: {r.text}")


def process_timesheet_file(filepath, username, password):
    """
    Read file lines in the format:
        # date 290125
            timesheet
                ProjectOne
                    9.00 - 12.00 Some description
                    12.30 - 17.00 Another task
                ProjectTwo
                    9.00 - 11.00 ...
    Create time entries for each line.
    """
    current_date = None
    in_timesheet_block = False
    current_project = None

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")  # keep indentation
            stripped = line.strip()

            if not stripped:
                continue  # skip blanks

            # Detect date line
            if stripped.startswith("# date"):
                parts = stripped.split()
                if len(parts) == 3:
                    date_str = parts[2]
                    current_date = parse_date(date_str)
                else:
                    current_date = None
                in_timesheet_block = False
                current_project = None
                continue

            # Detect "timesheet" line
            if stripped.lower() == "timesheet":
                in_timesheet_block = True
                current_project = None
                continue

            # If we're in the timesheet block, interpret lines as project headings or tasks
            if in_timesheet_block and current_date:
                indent = len(line) - len(line.lstrip(" "))

                # If indentation is moderate, treat this as a project name
                if indent >= 8 and indent < 12:
                    current_project = stripped
                    continue

                # If deeper indentation, treat this as a time/task line
                if indent >= 12:
                    start_time_str, end_time_str, description = parse_time_range(stripped)
                    if start_time_str is None:
                        # Not a recognized time range line
                        continue
                    sh, sm = float_time_to_hm(start_time_str)
                    eh, em = float_time_to_hm(end_time_str)
                    start_dt = build_iso_datetime(current_date, sh, sm)
                    end_dt   = build_iso_datetime(current_date, eh, em)
                    notes = f"[Project: {current_project}] {description}"
                    create_time_entry(start_dt, end_dt, notes, username, password)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Parse a timesheet file (in the specified format) and create time entries in TrackingTime."
    )
    parser.add_argument(
        "timesheet_file",
        nargs="?",
        help="Path to the timesheet file (optional if --list-users is used)."
    )
    parser.add_argument("--username", required=True, help="TrackingTime username (email).")
    parser.add_argument("--password", required=True, help="TrackingTime password.")
    parser.add_argument(
        "--list-users",
        action="store_true",
        help="List all users in the account (only for admins/project managers)."
    )

    args = parser.parse_args()

    # If user requested to list users, do that and exit
    if args.list_users:
        list_users(args.username, args.password)
        return

    # Otherwise, if a timesheet file is provided, process it
    if args.timesheet_file:
        process_timesheet_file(args.timesheet_file, args.username, args.password)
    else:
        # If no timesheet_file and not listing users, show usage
        print("No timesheet file specified. Use --list-users or provide a timesheet file.")
        parser.print_help()


if __name__ == "__main__":
    main()
