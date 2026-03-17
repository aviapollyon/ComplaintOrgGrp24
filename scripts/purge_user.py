import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import and_, or_

from app import create_app, db
from app.models.admin_notification import AdminNotification
from app.models.announcement import Announcement
from app.models.attachment import Attachment
from app.models.audit_log import AuditLog
from app.models.comment_vote import CommentVote
from app.models.escalation import EscalationRequest
from app.models.pending_registration import PendingRegistration
from app.models.reassignment_request import ReassignmentRequest
from app.models.reopen_request import ReopenRequest
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_flag import FlaggedTicket
from app.models.ticket_update import TicketUpdate
from app.models.ticket_vote import TicketVote
from app.models.user import User
from app.models.user_notification import UserNotification
from app.models.user_preference import UserPreference


DEFAULT_EMAIL = '22218367@dut4life.ac.za'


def _ids_for(query, column):
    return [row[0] for row in query.with_entities(column).all()]


def _count_or_delete(query, label, summary, dry_run):
    if dry_run:
        summary[label] = query.count()
    else:
        summary[label] = query.delete(synchronize_session=False)


def purge_user(email: str, dry_run: bool = True) -> int:
    user = User.query.filter_by(Email=email).first()
    pending = PendingRegistration.query.filter_by(Email=email).first()

    if not user and not pending:
        print(f'No user or pending registration found for: {email}')
        return 0

    summary = {}

    if user:
        uid = user.UserId
        ticket_ids = _ids_for(Ticket.query.filter(Ticket.StudentId == uid), Ticket.TicketId)

        update_ids_ticket = _ids_for(
            TicketUpdate.query.filter(TicketUpdate.TicketId.in_(ticket_ids)),
            TicketUpdate.UpdateId,
        ) if ticket_ids else []
        update_ids_user = _ids_for(
            TicketUpdate.query.filter(TicketUpdate.UserId == uid),
            TicketUpdate.UpdateId,
        )
        update_ids = list(set(update_ids_ticket + update_ids_user))

        comment_ids_ticket = _ids_for(
            TicketComment.query.filter(TicketComment.TicketId.in_(ticket_ids)),
            TicketComment.CommentId,
        ) if ticket_ids else []
        comment_ids_user = _ids_for(
            TicketComment.query.filter(TicketComment.UserId == uid),
            TicketComment.CommentId,
        )
        comment_ids = list(set(comment_ids_ticket + comment_ids_user))

        q_parent = TicketUpdate.query.filter(TicketUpdate.ParentUpdateId.in_(update_ids)) if update_ids else TicketUpdate.query.filter(False)
        if dry_run:
            summary['ticket_updates.parent_update_cleared'] = q_parent.count()
        else:
            summary['ticket_updates.parent_update_cleared'] = q_parent.update(
                {TicketUpdate.ParentUpdateId: None},
                synchronize_session=False,
            )

        _count_or_delete(
            CommentVote.query.filter(
                or_(CommentVote.UserId == uid, CommentVote.CommentId.in_(comment_ids))
            ),
            'comment_votes.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            TicketVote.query.filter(
                or_(TicketVote.UserId == uid, TicketVote.TicketId.in_(ticket_ids))
            ),
            'ticket_votes.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            Attachment.query.filter(
                or_(Attachment.UpdateId.in_(update_ids), Attachment.TicketId.in_(ticket_ids))
            ),
            'attachments.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            UserNotification.query.filter(
                or_(UserNotification.UserId == uid, UserNotification.TicketId.in_(ticket_ids))
            ),
            'user_notifications.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            AdminNotification.query.filter(AdminNotification.TicketId.in_(ticket_ids)),
            'admin_notifications.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            EscalationRequest.query.filter(
                or_(EscalationRequest.RequestedById == uid, EscalationRequest.TicketId.in_(ticket_ids))
            ),
            'escalation_requests.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            ReassignmentRequest.query.filter(
                or_(
                    ReassignmentRequest.RequestedById == uid,
                    ReassignmentRequest.TargetStaffId == uid,
                    ReassignmentRequest.TicketId.in_(ticket_ids),
                )
            ),
            'reassignment_requests.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            ReopenRequest.query.filter(
                or_(ReopenRequest.StudentId == uid, ReopenRequest.TicketId.in_(ticket_ids))
            ),
            'reopen_requests.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            FlaggedTicket.query.filter(FlaggedTicket.TicketId.in_(ticket_ids)),
            'flagged_tickets.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            TicketComment.query.filter(TicketComment.CommentId.in_(comment_ids)),
            'ticket_comments.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            TicketUpdate.query.filter(TicketUpdate.UpdateId.in_(update_ids)),
            'ticket_updates.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            UserPreference.query.filter(UserPreference.UserId == uid),
            'user_preferences.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            AuditLog.query.filter(
                or_(
                    AuditLog.ActorId == uid,
                    and_(AuditLog.TargetType == 'User', AuditLog.TargetId == uid),
                )
            ),
            'audit_logs.deleted',
            summary,
            dry_run,
        )

        _count_or_delete(
            Announcement.query.filter(Announcement.CreatedBy == uid),
            'announcements.deleted',
            summary,
            dry_run,
        )

        q_unassign = Ticket.query.filter(Ticket.StaffId == uid, Ticket.StudentId != uid)
        if dry_run:
            summary['tickets.staff_unassigned'] = q_unassign.count()
        else:
            summary['tickets.staff_unassigned'] = q_unassign.update(
                {Ticket.StaffId: None},
                synchronize_session=False,
            )

        _count_or_delete(
            Ticket.query.filter(Ticket.TicketId.in_(ticket_ids)),
            'tickets.deleted',
            summary,
            dry_run,
        )

        if dry_run:
            summary['users.deleted'] = 1
        else:
            db.session.delete(user)
            summary['users.deleted'] = 1

    if pending:
        if dry_run:
            summary['pending_registrations.deleted'] = 1
        else:
            db.session.delete(pending)
            summary['pending_registrations.deleted'] = 1

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    print('Summary:')
    for key in sorted(summary.keys()):
        print(f'  {key}: {summary[key]}')

    if dry_run:
        print('\nDry run complete. Re-run with --yes to execute deletions.')
    else:
        print('\nDeletion complete.')

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Purge a user by email and remove related references.'
    )
    parser.add_argument('--email', default=DEFAULT_EMAIL, help='User email to purge')
    parser.add_argument(
        '--config',
        default='default',
        choices=['default', 'development', 'production'],
        help='Flask config profile',
    )
    parser.add_argument(
        '--yes',
        action='store_true',
        help='Execute deletion. Without this flag, script performs dry-run only.',
    )
    args = parser.parse_args()

    app = create_app(args.config)
    with app.app_context():
        return purge_user(email=args.email, dry_run=not args.yes)


if __name__ == '__main__':
    raise SystemExit(main())
