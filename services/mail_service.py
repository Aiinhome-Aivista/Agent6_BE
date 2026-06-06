"""
Mail Service — Intelligent Underwriting Assistant
Sends HTML email notifications for underwriting escalations via SMTP.
Reads configuration from .env:
    MAIL_HOST, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD,
    MAIL_FROM, MAIL_FROM_NAME, MAIL_USE_TLS
"""
import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)


def _get_smtp_config() -> dict:
    return {
        "host":      os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port":      int(os.getenv("SMTP_PORT", 587)),
        "username":  os.getenv("SMTP_USER", ""),
        "password":  os.getenv("SMTP_PASSWORD", ""),
        "from_addr": os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")),
        "from_name": os.getenv("SMTP_FROM", "Intelligent Underwriting Assistant"),
        "use_tls":   os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    }


def _build_initial_html(case_number: str, applicant_name: str,
                        policy_type: str, risk_level: str,
                        role_name: str, wait_minutes: int) -> str:
    """Returns a styled HTML body for initial review notification."""
    deadline_note = f"{wait_minutes} minute{'s' if wait_minutes != 1 else ''}"
    return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f9;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:30px 0;">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;
                    box-shadow:0 4px 20px rgba(0,0,0,0.08);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1a237e 0%,#283593 100%);
                     padding:32px 40px;text-align:center;">
            <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:.5px;">
              🛡️ Underwriting Review Required
            </h1>
            <p style="margin:8px 0 0;color:#c5cae9;font-size:13px;">
              Intelligent Underwriting Assistant
            </p>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="margin:0 0 20px;color:#37474f;font-size:15px;line-height:1.6;">
              Dear <strong>{role_name}</strong>,
            </p>
            <p style="margin:0 0 24px;color:#546e7a;font-size:14px;line-height:1.7;">
              A new underwriting case has been assigned for your review.
              Please take action within <strong style="color:#d32f2f;">{deadline_note}</strong>
              to avoid automatic escalation to the next authority level.
            </p>

            <!-- Case Card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#f8f9ff;border:1px solid #e3e7ff;
                          border-radius:8px;overflow:hidden;margin-bottom:28px;">
              <tr>
                <td style="background:#3949ab;padding:12px 20px;">
                  <span style="color:#fff;font-size:13px;font-weight:600;
                               letter-spacing:.3px;">CASE DETAILS</span>
                </td>
              </tr>
              <tr>
                <td style="padding:20px;">
                  <table width="100%" cellpadding="6" cellspacing="0">
                    <tr>
                      <td style="color:#78909c;font-size:13px;width:40%;">Case Number</td>
                      <td style="color:#263238;font-size:13px;font-weight:600;">{case_number}</td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">Applicant Name</td>
                      <td style="color:#263238;font-size:13px;font-weight:600;">{applicant_name}</td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">Policy Type</td>
                      <td style="color:#263238;font-size:13px;">{policy_type}</td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">AI Risk Level</td>
                      <td>
                        <span style="display:inline-block;padding:3px 12px;border-radius:20px;
                                     font-size:12px;font-weight:700;letter-spacing:.3px;
                                     background:{'#ffebee' if risk_level in ('HIGH','CRITICAL') else '#fff3e0' if risk_level=='MEDIUM' else '#e8f5e9'};
                                     color:{'#c62828' if risk_level in ('HIGH','CRITICAL') else '#e65100' if risk_level=='MEDIUM' else '#2e7d32'};">
                          {risk_level}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">Assigned To</td>
                      <td style="color:#263238;font-size:13px;">{role_name}</td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">SLA Deadline</td>
                      <td style="color:#d32f2f;font-size:13px;font-weight:600;">{deadline_note} from now</td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- CTA -->
            # <p style="text-align:center;margin:0 0 28px;">
            #   <a href="#" style="display:inline-block;padding:14px 36px;
            #                       background:linear-gradient(135deg,#1a237e,#3949ab);
            #                       color:#fff;text-decoration:none;border-radius:8px;
            #                       font-size:14px;font-weight:600;letter-spacing:.3px;">
            #     Review Case in IUA Portal →
            #   </a>
            # </p>

            <p style="color:#90a4ae;font-size:12px;line-height:1.6;margin:0;">
              ⚠️ This is an automated notification from the Intelligent Underwriting Assistant.
              If no action is taken within the SLA window, this case will automatically escalate
              to the next authority level.
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8f9ff;border-top:1px solid #e8eaf6;
                     padding:18px 40px;text-align:center;">
            <p style="margin:0;color:#b0bec5;font-size:11px;">
              © {datetime.utcnow().year} Intelligent Underwriting Assistant &nbsp;|&nbsp;
              Automated Escalation System
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def _build_escalation_html(case_number: str, applicant_name: str,
                           policy_type: str, risk_level: str,
                           from_role: str, to_role: str,
                           original_wait_minutes: int) -> str:
    """Returns a styled HTML body for escalation notification."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f9;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:30px 0;">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;
                    box-shadow:0 4px 20px rgba(0,0,0,0.08);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#b71c1c 0%,#c62828 100%);
                     padding:32px 40px;text-align:center;">
            <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:.5px;">
              🚨 Escalation Alert — Immediate Action Required
            </h1>
            <p style="margin:8px 0 0;color:#ffcdd2;font-size:13px;">
              Intelligent Underwriting Assistant · Automated Escalation
            </p>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="margin:0 0 20px;color:#37474f;font-size:15px;line-height:1.6;">
              Dear <strong>{to_role}</strong>,
            </p>
            <p style="margin:0 0 24px;color:#546e7a;font-size:14px;line-height:1.7;">
              The following case was <strong style="color:#d32f2f;">not actioned</strong>
              by <em>{from_role}</em> within the allotted
              <strong>{original_wait_minutes} minute{'s' if original_wait_minutes != 1 else ''}</strong>
              SLA window. It has been automatically escalated to you for immediate review.
            </p>

            <!-- Escalation Badge -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#fff8f8;border:2px solid #ef9a9a;
                          border-radius:8px;margin-bottom:24px;">
              <tr>
                <td style="padding:14px 20px;text-align:center;">
                  <span style="color:#c62828;font-size:13px;font-weight:700;">
                    ⏰ SLA BREACHED — ESCALATED FROM {from_role.upper()} → {to_role.upper()}
                  </span>
                </td>
              </tr>
            </table>

            <!-- Case Card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#f8f9ff;border:1px solid #e3e7ff;
                          border-radius:8px;overflow:hidden;margin-bottom:28px;">
              <tr>
                <td style="background:#c62828;padding:12px 20px;">
                  <span style="color:#fff;font-size:13px;font-weight:600;
                               letter-spacing:.3px;">ESCALATED CASE DETAILS</span>
                </td>
              </tr>
              <tr>
                <td style="padding:20px;">
                  <table width="100%" cellpadding="6" cellspacing="0">
                    <tr>
                      <td style="color:#78909c;font-size:13px;width:40%;">Case Number</td>
                      <td style="color:#263238;font-size:13px;font-weight:600;">{case_number}</td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">Applicant Name</td>
                      <td style="color:#263238;font-size:13px;font-weight:600;">{applicant_name}</td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">Policy Type</td>
                      <td style="color:#263238;font-size:13px;">{policy_type}</td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">AI Risk Level</td>
                      <td>
                        <span style="display:inline-block;padding:3px 12px;border-radius:20px;
                                     font-size:12px;font-weight:700;letter-spacing:.3px;
                                     background:{'#ffebee' if risk_level in ('HIGH','CRITICAL') else '#fff3e0' if risk_level=='MEDIUM' else '#e8f5e9'};
                                     color:{'#c62828' if risk_level in ('HIGH','CRITICAL') else '#e65100' if risk_level=='MEDIUM' else '#2e7d32'};">
                          {risk_level}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">Originally Assigned To</td>
                      <td style="color:#263238;font-size:13px;">{from_role}</td>
                    </tr>
                    <tr>
                      <td style="color:#78909c;font-size:13px;">Now Escalated To</td>
                      <td style="color:#c62828;font-size:13px;font-weight:700;">{to_role}</td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- CTA -->
            <!-- <p style="text-align:center;margin:0 0 28px;">
              <a href="#" style="display:inline-block;padding:14px 36px;
                                  background:linear-gradient(135deg,#b71c1c,#e53935);
                                  color:#fff;text-decoration:none;border-radius:8px;
                                  font-size:14px;font-weight:600;letter-spacing:.3px;">
                Review Escalated Case Now →
              </a>
            </p> -->

            <p style="color:#90a4ae;font-size:12px;line-height:1.6;margin:0;">
              ⚠️ This is an automated escalation from the Intelligent Underwriting Assistant.
              Please review and action this case immediately to prevent further escalation.
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#fff8f8;border-top:1px solid #ffcdd2;
                     padding:18px 40px;text-align:center;">
            <p style="margin:0;color:#b0bec5;font-size:11px;">
              © {datetime.utcnow().year} Intelligent Underwriting Assistant &nbsp;|&nbsp;
              Automated Escalation System
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def send_mail(to_email: str, subject: str, html_body: str) -> bool:
    """
    Send an HTML email via SMTP.
    Returns True on success, False on failure.
    Logs errors but does NOT raise — callers should check the return value.
    """
    cfg = _get_smtp_config()

    if not cfg["username"] or not cfg["password"]:
        logger.warning("[MailService] MAIL_USERNAME / MAIL_PASSWORD not configured. Skipping send.")
        # In dev/test, print the email subject so we know it would have been sent
        print(f"[MailService] (MOCK) Would send to={to_email} | subject={subject}")
        return False  # treat as non-fatal

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{cfg['from_name']} <{cfg['from_addr']}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if cfg["use_tls"]:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
            server.ehlo()
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15)
        server.login(cfg["username"], cfg["password"])
        server.sendmail(cfg["from_addr"], [to_email], msg.as_string())
        server.quit()
        logger.info(f"[MailService] Sent to={to_email} | subject={subject}")
        return True
    except Exception as exc:
        logger.error(f"[MailService] Failed to send to={to_email}: {exc}")
        return False


def send_initial_review_mail(to_email: str, case_number: str, applicant_name: str,
                              policy_type: str, risk_level: str,
                              role_name: str, wait_minutes: int) -> bool:
    """Send the first-notification email when a case enters 'under_review'."""
    subject = f"[IUA] Action Required: Case {case_number} — {applicant_name} ({risk_level} Risk)"
    html = _build_initial_html(case_number, applicant_name, policy_type,
                               risk_level, role_name, wait_minutes)
    return send_mail(to_email, subject, html)


def send_escalation_mail(to_email: str, case_number: str, applicant_name: str,
                         policy_type: str, risk_level: str,
                         from_role: str, to_role: str,
                         original_wait_minutes: int) -> bool:
    """Send escalation email to next authority level after SLA breach."""
    subject = (f"[IUA] 🚨 ESCALATED: Case {case_number} — {applicant_name} "
               f"(No action by {from_role})")
    html = _build_escalation_html(case_number, applicant_name, policy_type,
                                  risk_level, from_role, to_role, original_wait_minutes)
    return send_mail(to_email, subject, html)


def send_bulk_emails(users: list[dict], subject: str, body: str):
    """
    Sends emails to a list of users.
    :param users: List of dictionaries with 'email' and 'name' keys.
    :param subject: Email subject.
    :param body: Email body (HTML).
    """
    cfg = _get_smtp_config()

    try:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
        if cfg["use_tls"]:
            server.starttls()
        server.login(cfg["username"], cfg["password"])

        for user in users:
            msg = MIMEMultipart()
            msg["From"] = cfg["from_addr"]
            msg["To"] = user["email"]
            msg["Subject"] = subject

            msg.attach(MIMEText(body, "html"))

            server.sendmail(cfg["from_addr"], user["email"], msg.as_string())
            logger.info(f"Email sent to {user['name']} <{user['email']}>")

        server.quit()
    except Exception as e:
        logger.error(f"Failed to send emails: {e}")
