INSERT into
    commands (
        command_dt,
        command,
        pid,
        return_val,
        pwd,
        session
    )
values
    (datetime('now', 'localtime'), ?, ?, ?, ?, ?)
