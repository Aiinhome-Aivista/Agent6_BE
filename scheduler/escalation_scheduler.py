"""
Escalation Scheduler — Intelligent Underwriting Assistant
Runs every minute via APScheduler.
Delegates all business logic to services/escalation_service.py.
"""
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Separate scheduler instance so it doesn't interfere with kb_scheduler
_esc_scheduler = BackgroundScheduler(timezone="UTC")


def _escalation_tick():
    """
    Called every minute.  Checks for overdue case_mail_log rows and fires
    escalation emails to the next authority level.
    """
    try:
        from services.escalation_service import check_and_escalate
        fired = check_and_escalate()
        if fired:
            logger.info(
                f"[EscalationScheduler] {datetime.utcnow().isoformat()} UTC — "
                f"{fired} escalation(s) triggered."
            )
    except Exception as exc:
        logger.error(f"[EscalationScheduler] Tick error: {exc}", exc_info=True)


def start_escalation_scheduler(interval_minutes: int = 1):
    """
    Start the escalation background scheduler.
    Call from main.py on application startup.
    interval_minutes: how often to run (default 1 min).
    """
    _esc_scheduler.add_job(
        _escalation_tick,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="escalation_check",
        name="Underwriting Escalation Check",
        replace_existing=True,
        max_instances=1,          # Prevent overlapping runs
    )
    _esc_scheduler.start()
    print(f"[EscalationScheduler] Started — checks every {interval_minutes} minute(s).")


def stop_escalation_scheduler():
    """Gracefully stop on app shutdown."""
    if _esc_scheduler.running:
        _esc_scheduler.shutdown(wait=False)
        print("[EscalationScheduler] Stopped.")
