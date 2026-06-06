import json
from database.connection import execute

def log_action(user_id: int, action: str, details: dict = None, target_type: str = None, target_id: int = None, ip_address: str = None, old_values: dict = None, new_values: dict = None):
    """
    Writes an event to the audit_logs table for compliance tracking.
    """
    sql = "INSERT INTO audit_logs (user_id, action, target_type, target_id, ip_address, old_values, new_values, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    try:
        execute(sql, (
            user_id, action, target_type, target_id, ip_address,
            json.dumps(old_values) if old_values else None,
            json.dumps(new_values) if new_values else None,
            json.dumps(details) if details else None
        ))
    except Exception as e:
        print(f"Failed to write audit log: {e}")
