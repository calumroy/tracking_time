import sys
import re
import argparse
import requests
from datetime import datetime

# ---------------------------------------------------------------------------
# CONFIGURATION (you can also pass account/team IDs, user IDs, etc., below)
# ---------------------------------------------------------------------------
BASE_URL = "https://app.trackingtime.co/api/v4"
USER_ID = 123456  # The user for whom we're creating these entries
# If your account requires specifying an account ID/team ID in the path, set:
ACCOUNT_ID = None  # e.g. 12345
USER_AGENT = "TimesheetParser (myemail@example.com)"

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

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
    Given something like:
        '9.00 - 12.00 Software design PCS sub controller'
    extract:
        start_time_str => '9.00'
        end_time_str   => '12.00'
        remainder      => 'Software design PCS sub controller'
    Returns (start_time, end_time, description) or (None, None, None) if not matched.
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
    Converts a string like '9.00' => (9, 0), '9.30' => (9, 30),
    '13.5' => (13, 30), etc.
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
        # Optional: "task_id": ...
        # Optional: "project_id": ...
        # Optional: "timezone": "GMT-03:00"
    }

    # If you need to specify an account/team ID:
    # e.g. https://app.trackingtime.co/api/v4/{ACCOUNT_ID}/events/add
    if ACCOUNT_ID:
        url = f"{BASE_URL}/{ACCOUNT_ID}/events/add"
    else:
        url = f"{BASE_URL}/events/add"

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }

    # Make request
    print(f"Creating entry from {start_dt} to {end_dt}, notes={notes!r}")
    r = requests.post(url, json=payload, auth=(username, password), headers=headers)

    if r.status_code == 200:
        resp_json = r.json()
        status = resp_json.get("response", {}).get("status", None)
        if status == 200:
            print("  ✓ Created successfully")
        else:
            err_msg = resp_json.get("response", {}).get("message", "Unknown error")
            print(f"  ✗ Error in response: {err_msg}")
    else:
        print(f"  ✗ HTTP Error {r.status_code}: {r.text}")


def process_timesheet_file(filepath, username, password):
    """
    Reads the input file line by line, looking for:

        # date ...
            timesheet
                <project>
                    <startTime> - <endTime> <description>
                <project>
                    ...

    and creates one time entry per line of tasks.
    """
    current_date = None
    in_timesheet_block = False
    current_project = None

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")  # keep indentation for analysis
            stripped = line.strip()

            if not stripped:
                continue  # skip blank lines

            # 1) Detect date line, e.g. "# date 310125"
            if stripped.startswith("# date"):
                # e.g. "# date 290125"
                parts = stripped.split()
                if len(parts) == 3:
                    date_str = parts[2]
                    current_date = parse_date(date_str)
                else:
                    current_date = None
                in_timesheet_block = False
                current_project = None
                continue

            # 2) Detect "timesheet" line
            if stripped.lower() == "timesheet":
                in_timesheet_block = True
                current_project = None
                continue

            # 3) If we're in the timesheet block, we either see:
            #    - A project name line
            #    - A task line under that project
            if in_timesheet_block and current_date:
                # Determine indent level to see if it’s project vs. task line
                indent = len(line) - len(line.lstrip(" "))

                # If indent is around 8 (or so), assume it's a project name
                if indent >= 8 and indent < 12:
                    current_project = stripped
                    continue

                # If indent is around 12 or more, assume it's a times line
                if indent >= 12:
                    # parse "9.00 - 12.00 Something"
                    start_time_str, end_time_str, description = parse_time_range(stripped)
                    if start_time_str is None:
                        # Not a recognized times line, skip
                        continue

                    # Build start/end datetimes
                    sh, sm = float_time_to_hm(start_time_str)
                    eh, em = float_time_to_hm(end_time_str)

                    start_dt = build_iso_datetime(current_date, sh, sm)
                    end_dt   = build_iso_datetime(current_date, eh, em)

                    # Combine project + user text into the notes
                    notes = f"[Project: {current_project}] {description}"

                    # Create the time entry in TrackingTime
                    create_time_entry(start_dt, end_dt, notes, username, password)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Parse a timesheet file and create time entries in TrackingTime.")
    parser.add_argument("timesheet_file", help="Path to the timesheet file")
    parser.add_argument("--username", required=True, help="TrackingTime username (email)")
    parser.add_argument("--password", required=True, help="TrackingTime password")
    args = parser.parse_args()

    process_timesheet_file(args.timesheet_file, args.username, args.password)


if __name__ == "__main__":
    main()
