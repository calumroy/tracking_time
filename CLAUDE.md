# Timesheet Tracking System Instructions

## Project Overview
This system helps track work hours across various projects by reading diary logs and formatting them into timesheets that can be uploaded to a time tracking system.

## Available Projects
The following active projects are available for time tracking:

### Centurion Truck Charging Depot (ID: 2094207)
Key tasks include:
- Hardware Installation at Site
- Project Management
- Cloud data integration
- Subcontrollers
- Component software testing
- Project data research
- Software design planning
- State Machine Design

### Batterang (ID: 2349452)
Key tasks include:
- Software Testing TI AM263 embedded platform
- Engineering - Battery & BMS Design
- Engineering - Documentation
- Customer and Internal Meetings

### Hybrid Haul Truck (ID: 2172690)
Key tasks include:
- Engineering - Technical and Project Management
- Engineering - Mechanical Concept Design
- Engineering - Research/Planning/Documentation
- Meetings - Internal

### UWA Dyno (ID: 2287394)
Key tasks include:
- Engineering - software
- Engineering - Planning/Management/Documentation
- Engineering - Mechanical Design

### SRG Sandvik Rig (ID: 2094220)
Key tasks include:
- Datalogging Software development
- CanBus decoding
- Site Visit

### Windmill (ID: 2323687)
Key tasks include:
- Gen 2 Design
- VESC Programming
- Design Of Windmill Lower Gearbox

## Timesheet Format
Timesheets should be formatted as follows:
```
# date DDMMYY
    timesheet
        Project Name
            Task Name
                HH.MM - HH.MM Brief description of work done
            Task Name
                HH.MM - HH.MM Brief description of work done
        Project Name
            Task Name
                HH.MM - HH.MM Brief description of work done
```

## Using the Parser
To parse and upload a timesheet file:
```
python timesheet_parser.py --username calum@switchbatteries.com --password "password" timesheet_file.txt
```

To get project tasks for a specific project:
```
python timesheet_parser.py --get-project-tasks --project-id PROJECT_ID --username calum@switchbatteries.com --password "password"
```

To list all available projects:
```
python timesheet_parser.py --get-projects --username calum@switchbatteries.com --password "password"
```

## Schedule Information
- Work hours: 9:00 AM - 5:30 PM
- Lunch break: 12:00 PM - 12:30 PM (30 minutes)