"""
Knowledge Base Scheduler
Runs every 6 hours via APScheduler.
Finds rule_books rows where graph_processed = 0 (uploaded but not yet LLM-processed)
and processes them through the KB pipeline.
"""
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from database.connection import fetch_all, execute

scheduler = BackgroundScheduler(timezone="UTC")


def _run_pending_kb_docs():
    """
    Synchronous wrapper — fetches all unprocessed KB docs and runs the pipeline.
    Called by APScheduler every 6 hours.
    """
    print(f"[KB Scheduler] Running at {datetime.utcnow().isoformat()} UTC")

    try:
        pending = fetch_all(
            "SELECT id, file_name, file_path FROM rule_books WHERE graph_processed = 0 ORDER BY created_at ASC"
        )
    except Exception as e:
        print(f"[KB Scheduler] DB fetch error: {e}")
        return

    if not pending:
        print("[KB Scheduler] No pending documents found.")
        return

    print(f"[KB Scheduler] Found {len(pending)} unprocessed document(s). Processing...")

    from services.kb_pipeline import kb_pipeline

    async def _process_all():
        for row in pending:
            kb_id     = row["id"]
            file_name = row["file_name"]
            file_path = row["file_path"]

            print(f"[KB Scheduler] Processing kb_id={kb_id} -> {file_name}")
            try:
                import os
                if not os.path.exists(file_path):
                    print(f"[KB Scheduler] File not found on disk: {file_path}. Marking as error.")
                    execute(
                        "UPDATE rule_books SET graph_processed = 2, processing_error = %s WHERE id = %s",
                        ("File not found on disk", kb_id)
                    )
                    continue

                result = await kb_pipeline.process(kb_id, file_path, file_name)

                relevance     = result.get("relevance", {})
                is_blocked    = result.get("blocked", True)
                risk_analysis = result.get("risk_analysis") or {}

                category = relevance.get("category", "General")

                if is_blocked:
                    execute(
                        """UPDATE rule_books SET
                           graph_processed       = 2,
                           relevance_score       = %s,
                           relevance_label       = %s,
                           relevance_reason      = %s,
                           raw_summary           = %s,
                           extraction_confidence = %s,
                           processed_at          = %s,
                           category              = %s
                           WHERE id = %s""",
                        (
                            relevance.get("score", 0),
                            relevance.get("label", "Blocked"),
                            relevance.get("reason", ""),
                            result.get("raw_summary"),
                            result.get("extraction_confidence"),
                            datetime.utcnow(),
                            category,
                            kb_id
                        )
                    )
                    print(f"[KB Scheduler] BLOCKED kb_id={kb_id} — relevance={relevance.get('score')} — category={category}")
                else:
                    execute(
                        """UPDATE rule_books SET
                           relevance_score       = %s,
                           relevance_label       = %s,
                           relevance_reason      = %s,
                           graph_processed       = 1,
                           nodes_count           = %s,
                           edges_count           = %s,
                           chunks_count          = %s,
                           risk_level            = %s,
                           fraud_score           = %s,
                           raw_summary           = %s,
                           extraction_confidence = %s,
                           processed_at          = %s,
                           category              = %s
                           WHERE id = %s""",
                        (
                            relevance.get("score", 0),
                            relevance.get("label", ""),
                            relevance.get("reason", ""),
                            result.get("nodes_stored", 0),
                            result.get("edges_stored", 0),
                            result.get("chunks_indexed", 0),
                            risk_analysis.get("risk_level"),
                            risk_analysis.get("fraud_score"),
                            result.get("raw_summary"),
                            result.get("extraction_confidence"),
                            datetime.utcnow(),
                            category,
                            kb_id
                        )
                    )
                    print(f"[KB Scheduler] Done kb_id={kb_id} — nodes={result.get('nodes_stored')}, edges={result.get('edges_stored')} — category={category}")

            except Exception as e:
                print(f"[KB Scheduler] Error processing kb_id={kb_id}: {e}")
                try:
                    execute(
                        "UPDATE rule_books SET graph_processed = 2, processing_error = %s WHERE id = %s",
                        (str(e)[:500], kb_id)
                    )
                except Exception:
                    pass

    asyncio.run(_process_all())
    print("[KB Scheduler] Batch complete.")


def start_kb_scheduler(interval_hours: int = 6):
    """
    Start the background scheduler.
    Call this from main.py on application startup.
    interval_hours: how often to run (default 6hrs, min 1hr for testing)
    """
    scheduler.add_job(
        _run_pending_kb_docs,
        trigger=IntervalTrigger(hours=interval_hours),
        id="kb_graph_refresh",
        name="Knowledge Base Graph Refresh",
        replace_existing=True,
        max_instances=1          # Prevent overlapping runs
    )
    scheduler.start()
    print(f"[KB Scheduler] Started — runs every {interval_hours} hour(s).")


def stop_kb_scheduler():
    """Gracefully stop the scheduler on app shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[KB Scheduler] Stopped.")
