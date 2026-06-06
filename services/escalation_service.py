"""
Escalation Service — Intelligent Underwriting Assistant
Core business logic for:
  1. Triggering initial review emails when a case becomes 'under_review'.
  2. Checking SLA windows and firing escalation emails to higher authority.
"""
import logging
from datetime import datetime, timedelta
from database.connection import fetch_all, fetch_one, execute

logger = logging.getLogger(__name__)


# ── Role Hierarchy (ascending authority, matches mail_config.level) ──────────
# role_id:  4=Underwriter  3=Senior_Underwriter  2=Manager  1=Admin
LEVEL_ROLES = {4: 1, 3: 2, 2: 3, 1: 4}   # role_id → level


def _get_mail_config(role_id: int) -> dict | None:
    """Fetch mail_config row for a given role_id."""
    return fetch_one(
        "SELECT * FROM mail_config WHERE role_id = %s AND is_active = 1",
        (role_id,)
    )


def _get_users_for_role(role_id: int) -> list[dict]:
    """Return all active users with the specified role_id (for email dispatch)."""
    return fetch_all(
        "SELECT id, username, email FROM users WHERE role_id = %s AND is_active = 1",
        (role_id,)
    )


def _get_active_log(case_id: int, role_id: int) -> dict | None:
    """
    Fetch the most-recent case_mail_log row for (case_id, role_id)
    that has NOT yet been escalated and NOT yet had action taken.
    """
    return fetch_one(
        """SELECT * FROM case_mail_log
           WHERE case_id = %s AND role_id = %s
             AND is_escalated = 0 AND action_taken = 0
           ORDER BY sent_at DESC LIMIT 1""",
        (case_id, role_id)
    )


# ── Public API ────────────────────────────────────────────────────────────────

def trigger_initial_notification(case_id: int) -> bool:
    """
    Called right after a case transitions to 'under_review'.
    Looks up the Level-1 (Underwriter, role_id=4) mail_config, then
    emails all active Underwriters and inserts a case_mail_log row.

    Returns True if at least one email was dispatched / logged.
    """
    from services.mail_service import send_initial_review_mail

    # Fetch case details
    case = fetch_one(
        """SELECT uc.case_number, uc.applicant_name, uc.policy_type,
                  COALESCE(ra.risk_level, 'UNKNOWN') AS risk_level
           FROM underwriting_cases uc
           LEFT JOIN risk_assessments ra ON ra.case_id = uc.id
           WHERE uc.id = %s
           ORDER BY ra.created_at DESC LIMIT 1""",
        (case_id,)
    )
    if not case:
        logger.warning(f"[Escalation] case_id={case_id} not found.")
        return False

    # Level-1 = Underwriter (role_id = 4)
    cfg = _get_mail_config(role_id=4)
    if not cfg:
        logger.warning("[Escalation] No active mail_config for role_id=4 (Underwriter).")
        return False

    underwriters = _get_users_for_role(role_id=4)
    if not underwriters:
        logger.warning("[Escalation] No active Underwriters found to notify.")
        return False

    wait_minutes  = cfg["wait_minutes"]
    due_at        = datetime.utcnow() + timedelta(minutes=wait_minutes)
    dispatched    = 0

    for uw in underwriters:
        sent = send_initial_review_mail(
            to_email      = uw["email"],
            case_number   = case["case_number"],
            applicant_name= case["applicant_name"],
            policy_type   = case["policy_type"],
            risk_level    = case["risk_level"],
            role_name     = "Underwriter",
            wait_minutes  = wait_minutes,
        )
        # Log regardless (mock sends are also tracked)
        execute(
            """INSERT INTO case_mail_log
               (case_id, role_id, recipient_email, mail_type, sent_at, escalation_due_at)
               VALUES (%s, %s, %s, 'initial', %s, %s)""",
            (case_id, 4, uw["email"], datetime.utcnow(), due_at)
        )
        if sent:
            dispatched += 1
        logger.info(
            f"[Escalation] Initial mail → {uw['email']} | case={case['case_number']} | "
            f"due={due_at.isoformat()}"
        )

    return dispatched > 0 or len(underwriters) > 0  # logged even if SMTP not configured


def check_and_escalate() -> int:
    """
    Scheduled job: check all overdue case_mail_log rows and escalate.
    Called every minute by the escalation scheduler.
    Returns count of escalations fired in this run.
    """
    from services.mail_service import send_escalation_mail, send_initial_review_mail

    now = datetime.utcnow()

    # Find all log entries whose SLA window has expired and haven't been escalated
    overdue = fetch_all(
        """SELECT cml.*, uc.case_number, uc.applicant_name, uc.policy_type, cs.status_name AS status,
                  COALESCE(ra.risk_level, 'UNKNOWN') AS risk_level
           FROM case_mail_log cml
           JOIN underwriting_cases uc ON uc.id = cml.case_id
           LEFT JOIN case_statuses cs ON uc.status_id = cs.id
           LEFT JOIN risk_assessments ra ON ra.case_id = cml.case_id
           WHERE cml.is_escalated = 0
             AND cml.action_taken = 0
             AND cml.escalation_due_at <= %s
             AND cs.status_name NOT IN ('Approved', 'Rejected')
           ORDER BY cml.escalation_due_at ASC""",
        (now,)
    )

    if not overdue:
        return 0

    escalated_count = 0

    for row in overdue:
        log_id       = row["id"]
        case_id      = row["case_id"]
        current_role = row["role_id"]
        case_number  = row["case_number"]
        applicant    = row["applicant_name"]
        policy_type  = row["policy_type"]
        risk_level   = row["risk_level"]

        # Get current role's config to find who to escalate to
        current_cfg = _get_mail_config(role_id=current_role)
        if not current_cfg:
            logger.warning(f"[Escalation] No config for role_id={current_role}. Skipping log_id={log_id}.")
            # Mark as escalated to stop re-processing
            execute("UPDATE case_mail_log SET is_escalated=1, escalated_at=%s WHERE id=%s",
                    (now, log_id))
            continue

        from_role_name       = current_cfg["role_name"]
        original_wait        = current_cfg["wait_minutes"]
        escalate_to_role_id  = current_cfg["escalate_to_role_id"]

        # Mark the current log as escalated
        execute(
            "UPDATE case_mail_log SET is_escalated=1, escalated_at=%s WHERE id=%s",
            (now, log_id)
        )
        
        # Update the case status to 'Referred' so the UI reflects the escalation globally
        execute(
            "UPDATE underwriting_cases SET status_id = (SELECT id FROM case_statuses WHERE status_name = 'Referred') WHERE id = %s",
            (case_id,)
        )

        if not escalate_to_role_id:
            # This is the top level (Admin). Log the breach but no further escalation.
            logger.warning(
                f"[Escalation] TOP-LEVEL SLA BREACH — case={case_number} | "
                f"role={from_role_name} | log_id={log_id}. No further escalation."
            )
            continue

        # Fetch next-level config
        next_cfg = _get_mail_config(role_id=escalate_to_role_id)
        if not next_cfg:
            logger.warning(f"[Escalation] No config for escalate_to_role_id={escalate_to_role_id}.")
            continue

        next_role_name  = next_cfg["role_name"]
        next_wait       = next_cfg["wait_minutes"]
        next_due_at     = now + timedelta(minutes=next_wait)
        next_users      = _get_users_for_role(role_id=escalate_to_role_id)

        if not next_users:
            logger.warning(f"[Escalation] No active users for role_id={escalate_to_role_id}.")
            continue

        for user in next_users:
            sent = send_escalation_mail(
                to_email             = user["email"],
                case_number          = case_number,
                applicant_name       = applicant,
                policy_type          = policy_type,
                risk_level           = risk_level,
                from_role            = from_role_name,
                to_role              = next_role_name,
                original_wait_minutes= original_wait,
            )
            # Insert new log row for the escalated level
            execute(
                """INSERT INTO case_mail_log
                   (case_id, role_id, recipient_email, mail_type, sent_at, escalation_due_at)
                   VALUES (%s, %s, %s, 'escalation', %s, %s)""",
                (case_id, escalate_to_role_id, user["email"], now, next_due_at)
            )
            logger.info(
                f"[Escalation] Escalated case={case_number} "
                f"from={from_role_name} → to={next_role_name} | "
                f"email={user['email']} | due={next_due_at.isoformat()}"
            )

        escalated_count += 1

    return escalated_count


def mark_action_taken(case_id: int) -> int:
    """
    Call this when an underwriter takes any decision on a case (approve/reject/escalate).
    Marks ALL open case_mail_log rows for the case as actioned, stopping further escalations.
    Returns the number of rows updated.
    """
    now = datetime.utcnow()
    from database.connection import db_cursor
    with db_cursor(commit=True) as (_, cur):
        cur.execute(
            """UPDATE case_mail_log
               SET action_taken = 1, action_taken_at = %s
               WHERE case_id = %s AND action_taken = 0 AND is_escalated = 0""",
            (now, case_id)
        )
        return cur.rowcount
