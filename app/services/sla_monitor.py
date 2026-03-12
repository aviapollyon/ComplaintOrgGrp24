import logging
import threading
import time

from app import db
from app.models.ticket import Ticket, StatusEnum
from app.services.notifications import notify_sla_breach

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_thread = None


def _scan_sla_breaches():
    tickets = Ticket.query.filter(~Ticket.Status.in_([StatusEnum.Resolved, StatusEnum.Rejected])).all()
    for ticket in tickets:
        if ticket.is_response_sla_overdue:
            notify_sla_breach(ticket, 'first_response')
        if ticket.is_resolution_sla_overdue:
            notify_sla_breach(ticket, 'resolution')
    db.session.commit()


def _runner(app, interval_seconds):
    logger.info('SLA monitor started (interval=%ss).', interval_seconds)
    with app.app_context():
        while not _stop_event.is_set():
            try:
                _scan_sla_breaches()
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                logger.error('SLA monitor scan failed: %s', exc, exc_info=True)
            finally:
                db.session.remove()

            # Wait with interrupt support
            if _stop_event.wait(timeout=interval_seconds):
                break

    logger.info('SLA monitor stopped.')


def start_sla_monitor(app):
    global _thread

    if not app.config.get('SLA_MONITOR_ENABLED', True):
        logger.info('SLA monitor is disabled by configuration.')
        return

    if _thread and _thread.is_alive():
        return

    interval_seconds = max(30, int(app.config.get('SLA_MONITOR_INTERVAL_SECONDS', 300)))
    _stop_event.clear()
    _thread = threading.Thread(
        target=_runner,
        args=(app, interval_seconds),
        daemon=True,
        name='sla-monitor-thread',
    )
    _thread.start()


def stop_sla_monitor():
    _stop_event.set()
