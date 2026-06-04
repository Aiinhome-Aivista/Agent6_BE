"""
Mail Config Controller — Intelligent Underwriting Assistant
REST API to manage the mail_config table (per-role SLA wait times)
and to inspect case mail / escalation logs.

Endpoints:
  GET    /mail-config/              → list all config rows
  PUT    /mail-config/{role_id}     → update wait_minutes / is_active for a role
  GET    /mail-config/logs          → list case_mail_log (all or filtered by case_id)
  POST   /mail-config/test-mail     → send a test email to verify SMTP settings
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from database.connection import fetch_all, fetch_one, execute
from utils.auth_deps import get_current_user
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mail-config", tags=["Mail & Escalation Config"])


# ── Pydantic Schemas ─────────────────────────────────────────────────────────

class MailConfigUpdate(BaseModel):
    wait_minutes: int = Field(..., ge=1, le=10080,
                              description="SLA window in minutes (1 min – 7 days)")
    is_active: bool = True


class TestMailRequest(BaseModel):
    to_email: EmailStr


# ── Helper ───────────────────────────────────────────────────────────────────

def _admin_only(current_user: dict):
    if current_user["role_id"] != 1:
        raise HTTPException(status_code=403,
                            detail="Only Admins can manage mail configuration.")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", summary="List all mail config entries")
async def list_mail_config(current_user: dict = Depends(get_current_user)):
    """
    Returns all mail_config rows showing per-role SLA wait times
    and the escalation chain.  Accessible by Admins and Managers.
    """
    if current_user["role_id"] not in [1, 2]:
        raise HTTPException(status_code=403,
                            detail="Admins and Managers only.")
    rows = fetch_all(
        """SELECT mc.id, mc.role_id, mc.role_name, mc.level,
                  mc.wait_minutes, mc.is_active,
                  er.name AS escalates_to_role_name,
                  mc.escalate_to_role_id,
                  mc.created_at, mc.updated_at
           FROM mail_config mc
           LEFT JOIN roles er ON er.id = mc.escalate_to_role_id
           ORDER BY mc.level ASC"""
    )
    return rows


@router.put("/{role_id}", summary="Update SLA wait time for a role")
async def update_mail_config(
    role_id: int,
    body: MailConfigUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Admin-only.  Update the SLA wait_minutes and active status for a given role.
    Example: set Underwriter (role_id=4) wait to 45 minutes.
    """
    _admin_only(current_user)

    existing = fetch_one("SELECT id FROM mail_config WHERE role_id = %s", (role_id,))
    if not existing:
        raise HTTPException(status_code=404,
                            detail=f"No mail_config entry for role_id={role_id}.")

    execute(
        """UPDATE mail_config
           SET wait_minutes = %s, is_active = %s, updated_at = %s
           WHERE role_id = %s""",
        (body.wait_minutes, int(body.is_active), datetime.utcnow(), role_id)
    )

    updated = fetch_one(
        """SELECT mc.*, er.name AS escalates_to_role_name
           FROM mail_config mc
           LEFT JOIN roles er ON er.id = mc.escalate_to_role_id
           WHERE mc.role_id = %s""",
        (role_id,)
    )
    return {"message": "Mail config updated successfully.", "config": updated}


@router.get("/logs", summary="View case mail & escalation logs")
async def get_mail_logs(
    case_id: int | None = Query(None, description="Filter by specific case ID"),
    limit: int          = Query(100, ge=1, le=500),
    current_user: dict  = Depends(get_current_user)
):
    """
    Returns case_mail_log entries.  Admins/Managers see all; others see only
    logs where they are the recipient (by their own email).
    """
    role_id = current_user["role_id"]

    if role_id in [1, 2]:
        # Full access
        if case_id:
            rows = fetch_all(
                """SELECT cml.*, uc.case_number, uc.applicant_name,
                          r.name AS role_name
                   FROM case_mail_log cml
                   JOIN underwriting_cases uc ON uc.id = cml.case_id
                   JOIN roles r ON r.id = cml.role_id
                   WHERE cml.case_id = %s
                   ORDER BY cml.sent_at DESC LIMIT %s""",
                (case_id, limit)
            )
        else:
            rows = fetch_all(
                """SELECT cml.*, uc.case_number, uc.applicant_name,
                          r.name AS role_name
                   FROM case_mail_log cml
                   JOIN underwriting_cases uc ON uc.id = cml.case_id
                   JOIN roles r ON r.id = cml.role_id
                   ORDER BY cml.sent_at DESC LIMIT %s""",
                (limit,)
            )
    else:
        # Underwriters / Senior UW: see only their own emails
        user_record = fetch_one("SELECT email FROM users WHERE id = %s",
                                (current_user["user_id"],))
        if not user_record:
            raise HTTPException(status_code=404, detail="User not found.")
        my_email = user_record["email"]

        base_sql = """SELECT cml.*, uc.case_number, uc.applicant_name,
                             r.name AS role_name
                      FROM case_mail_log cml
                      JOIN underwriting_cases uc ON uc.id = cml.case_id
                      JOIN roles r ON r.id = cml.role_id
                      WHERE cml.recipient_email = %s"""
        if case_id:
            rows = fetch_all(base_sql + " AND cml.case_id = %s ORDER BY cml.sent_at DESC LIMIT %s",
                             (my_email, case_id, limit))
        else:
            rows = fetch_all(base_sql + " ORDER BY cml.sent_at DESC LIMIT %s",
                             (my_email, limit))

    return rows


@router.get("/logs/summary", summary="Escalation summary dashboard data")
async def get_escalation_summary(current_user: dict = Depends(get_current_user)):
    """
    Returns aggregated escalation KPIs for the dashboard:
    - Total mails sent (initial + escalation)
    - Total escalations fired
    - Open (pending action) cases count
    - Average escalation time
    Admin / Manager only.
    """
    if current_user["role_id"] not in [1, 2]:
        raise HTTPException(status_code=403, detail="Admins and Managers only.")

    summary = fetch_one(
        """SELECT
             COUNT(*)                                        AS total_mails_sent,
             SUM(mail_type = 'escalation')                  AS total_escalations,
             SUM(is_escalated = 0 AND action_taken = 0)     AS open_notifications,
             SUM(action_taken = 1)                          AS actioned_notifications
           FROM case_mail_log"""
    )

    # Breakdown by level
    by_role = fetch_all(
        """SELECT r.name AS role_name, mc.level,
                  COUNT(cml.id)                    AS total_sent,
                  SUM(cml.is_escalated = 1)        AS escalated_out,
                  SUM(cml.action_taken = 1)        AS actioned
           FROM case_mail_log cml
           JOIN roles r ON r.id = cml.role_id
           LEFT JOIN mail_config mc ON mc.role_id = cml.role_id
           GROUP BY cml.role_id, r.name, mc.level
           ORDER BY mc.level ASC"""
    )

    return {"summary": summary, "by_role": by_role}


@router.post("/test-mail", summary="Send a test email to verify SMTP")
async def send_test_mail(
    body: TestMailRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Admin-only.  Sends a test HTML email to verify that SMTP settings
    in .env are correct (MAIL_HOST, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD).
    """
    _admin_only(current_user)

    from services.mail_service import send_mail
    html = """
    <div style="font-family:sans-serif;padding:30px;background:#f4f6f9;">
      <div style="max-width:500px;margin:auto;background:#fff;border-radius:10px;
                  padding:30px;box-shadow:0 4px 12px rgba(0,0,0,.08);">
        <h2 style="color:#1a237e;margin-top:0;">✅ SMTP Test Successful</h2>
        <p style="color:#546e7a;">
          Your Intelligent Underwriting Assistant mail service is configured correctly.<br>
          Escalation emails will be delivered to underwriters as expected.
        </p>
        <hr style="border:none;border-top:1px solid #e8eaf6;margin:20px 0;">
        <p style="color:#90a4ae;font-size:12px;margin:0;">
          © Intelligent Underwriting Assistant — Automated Mail System
        </p>
      </div>
    </div>
    """
    sent = send_mail(
        to_email=body.to_email,
        subject="[IUA] SMTP Test — Mail Service Verification",
        html_body=html
    )
    if sent:
        return {"message": f"Test email sent successfully to {body.to_email}."}
    else:
        return {
            "message": "SMTP not configured (MAIL_USERNAME/MAIL_PASSWORD missing). "
                       "Check .env and restart the server.",
            "hint": "Add MAIL_HOST, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM to .env"
        }
