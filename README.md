# tracking_time
python command line tools to read notes and fill in the tracking time website 

Give it a text file with this format

```
        # date 290125
            timesheet
                ProjectOne
                    9.00 - 12.00 Some description
                    12.30 - 17.00 Another task
                ProjectTwo
                    9.00 - 11.00 ...
```

## Example usage

```
python timesheet_parser.py <timesheet_file.txt> --username "john@doe.com" --password "MyPassWord"
```

--username and --password are your TrackingTime credentials.
(Alternatively, adapt the script to use environment variables or tokens.)