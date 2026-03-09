"""
seed_test_data.py
Run once after flask db upgrade to populate the database with realistic test data.

Usage:
    python seed_test_data.py

Login credentials are printed to the console on completion.
"""

from app import create_app, db
from app.models.department        import Department
from app.models.user              import User, RoleEnum
from app.models.ticket            import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update     import TicketUpdate, UpdateStatusEnum
from app.models.announcement      import Announcement
from app.models.user_notification import UserNotification
from app.services.notifications   import (
    notify_ticket_assigned,
    notify_status_update,
    notify_staff_reply,
    notify_ticket_resolved,
    notify_ticket_rejected,
    notify_progress_update,
)
from datetime import datetime, timedelta
import random

app = create_app('development')


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def days_ago(n, hours=0, minutes=0):
    return datetime.utcnow() - timedelta(days=n, hours=hours, minutes=minutes)


def make_user(full_name, email, password, role, dept):
    u = User(
        FullName     = full_name,
        Email        = email,
        Role         = role,
        DepartmentId = dept.DepartmentId if dept else None,
        IsActive     = True,
        CreatedAt    = days_ago(random.randint(30, 120)),
    )
    u.set_password(password)
    db.session.add(u)
    return u


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

with app.app_context():

    # ── 1. Departments ────────────────────────────────────────────────────────
    dept_map = {
        'Academic Affairs'       : None,
        'Finance & Accounts'     : None,
        'Facilities Management'  : None,
        'Information Technology' : None,
        'Student Housing'        : None,
        'Student Administration' : None,
    }

    for name in dept_map:
        existing = Department.query.filter_by(Name=name).first()
        if not existing:
            d = Department(Name=name)
            db.session.add(d)
            db.session.flush()
            dept_map[name] = d
        else:
            dept_map[name] = existing

    db.session.flush()

    academic   = dept_map['Academic Affairs']
    finance    = dept_map['Finance & Accounts']
    facilities = dept_map['Facilities Management']
    it_dept    = dept_map['Information Technology']
    housing    = dept_map['Student Housing']
    admin_dept = dept_map['Student Administration']

    # ── 2. Admin account ─────────────────────────────────────────────────────
    admin_user = User.query.filter_by(Email='admin@dut.ac.za').first()
    if not admin_user:
        admin_user = make_user(
            'System Admin', 'admin@dut.ac.za', 'Admin@1234',
            RoleEnum.Admin, None
        )
        db.session.flush()

    # ── 3. Staff accounts ─────────────────────────────────────────────────────
    staff_data = [
        ('Sipho Nkosi',       'sipho.nkosi@dut.ac.za',       'Staff@1234', academic),
        ('Priya Pillay',      'priya.pillay@dut.ac.za',      'Staff@1234', academic),
        ('James Mokoena',     'james.mokoena@dut.ac.za',     'Staff@1234', finance),
        ('Fatima Dlamini',    'fatima.dlamini@dut.ac.za',    'Staff@1234', finance),
        ('Rajan Govender',    'rajan.govender@dut.ac.za',    'Staff@1234', facilities),
        ('Nomsa Zulu',        'nomsa.zulu@dut.ac.za',        'Staff@1234', it_dept),
        ('Thabo Sithole',     'thabo.sithole@dut.ac.za',     'Staff@1234', it_dept),
        ('Linda Maharaj',     'linda.maharaj@dut.ac.za',     'Staff@1234', housing),
        ('Mandla Khumalo',    'mandla.khumalo@dut.ac.za',    'Staff@1234', admin_dept),
    ]

    staff_users = {}
    for full_name, email, pw, dept in staff_data:
        u = User.query.filter_by(Email=email).first()
        if not u:
            u = make_user(full_name, email, pw, RoleEnum.Staff, dept)
            db.session.flush()
        staff_users[email] = u

    # ── 4. Student accounts ───────────────────────────────────────────────────
    student_data = [
        ('Ayanda Mthembu',    'ayanda.mthembu@student.dut.ac.za',    'Student@1234'),
        ('Keegan Peters',     'keegan.peters@student.dut.ac.za',     'Student@1234'),
        ('Zanele Ntuli',      'zanele.ntuli@student.dut.ac.za',      'Student@1234'),
        ('Rishi Naidoo',      'rishi.naidoo@student.dut.ac.za',      'Student@1234'),
        ('Chloe van Wyk',     'chloe.vanwyk@student.dut.ac.za',      'Student@1234'),
        ('Lethiwe Cele',      'lethiwe.cele@student.dut.ac.za',      'Student@1234'),
        ('Mohammed Cassim',   'mohammed.cassim@student.dut.ac.za',   'Student@1234'),
        ('Tayla Botha',       'tayla.botha@student.dut.ac.za',       'Student@1234'),
    ]

    student_users = {}
    for full_name, email, pw in student_data:
        u = User.query.filter_by(Email=email).first()
        if not u:
            u = make_user(full_name, email, pw, RoleEnum.Student, None)
            db.session.flush()
        student_users[email] = u

    # References
    ayanda   = student_users['ayanda.mthembu@student.dut.ac.za']
    keegan   = student_users['keegan.peters@student.dut.ac.za']
    zanele   = student_users['zanele.ntuli@student.dut.ac.za']
    rishi    = student_users['rishi.naidoo@student.dut.ac.za']
    chloe    = student_users['chloe.vanwyk@student.dut.ac.za']
    lethiwe  = student_users['lethiwe.cele@student.dut.ac.za']
    mohammed = student_users['mohammed.cassim@student.dut.ac.za']
    tayla    = student_users['tayla.botha@student.dut.ac.za']

    sipho    = staff_users['sipho.nkosi@dut.ac.za']
    priya    = staff_users['priya.pillay@dut.ac.za']
    james    = staff_users['james.mokoena@dut.ac.za']
    fatima   = staff_users['fatima.dlamini@dut.ac.za']
    rajan    = staff_users['rajan.govender@dut.ac.za']
    nomsa    = staff_users['nomsa.zulu@dut.ac.za']
    thabo    = staff_users['thabo.sithole@dut.ac.za']
    linda    = staff_users['linda.maharaj@dut.ac.za']
    mandla   = staff_users['mandla.khumalo@dut.ac.za']

    # ── 5. Tickets ────────────────────────────────────────────────────────────

    def make_ticket(student, staff, dept, title, description,
                    category, priority, status,
                    created_days_ago, resolved_days_ago=None,
                    feedback_rating=None, feedback_comment=None):
        created_at  = days_ago(created_days_ago, random.randint(0, 8))
        resolved_at = None
        if resolved_days_ago is not None:
            resolved_at = days_ago(resolved_days_ago, random.randint(0, 4))

        t = Ticket(
            StudentId       = student.UserId,
            StaffId         = staff.UserId if staff else None,
            DepartmentId    = dept.DepartmentId,
            Title           = title,
            Description     = description,
            Category        = category,
            Priority        = priority,
            Status          = status,
            CreatedAt       = created_at,
            UpdatedAt       = resolved_at or created_at,
            ResolvedAt      = resolved_at,
            FeedbackRating  = feedback_rating,
            FeedbackComment = feedback_comment,
        )
        db.session.add(t)
        db.session.flush()
        return t

    def add_update(ticket, author, comment, status_change=None,
                   is_reply_thread=False, parent_id=None, when_days_ago=None):
        created = days_ago(when_days_ago or 0, random.randint(0, 3))
        u = TicketUpdate(
            TicketId       = ticket.TicketId,
            UserId         = author.UserId,
            Comment        = comment,
            StatusChange   = status_change,
            IsReplyThread  = is_reply_thread,
            ParentUpdateId = parent_id,
            CreatedAt      = created,
        )
        db.session.add(u)
        db.session.flush()
        return u

    # ── Ticket 1 — RESOLVED with feedback ────────────────────────────────────
    t1 = make_ticket(
        student            = ayanda,
        staff              = sipho,
        dept               = academic,
        title              = 'Missing module result for BUS301',
        description        = ('My result for BUS301 does not appear on the student portal '
                              'even though I wrote the exam three weeks ago. '
                              'I need this resolved before the supplementary exam deadline.'),
        category           = 'Academic',
        priority           = PriorityEnum.High,
        status             = StatusEnum.Resolved,
        created_days_ago   = 18,
        resolved_days_ago  = 5,
        feedback_rating    = 5,
        feedback_comment   = 'Sipho was very helpful and resolved this quickly.',
    )
    add_update(t1, sipho,  'Ticket received. I will contact the examinations office.',
               UpdateStatusEnum.InProgress, when_days_ago=17)
    add_update(t1, sipho,  '[RESOLVED] Result has been captured. Please check your portal.',
               UpdateStatusEnum.Resolved, when_days_ago=5)
    notify_ticket_assigned(t1)
    notify_ticket_resolved(t1, sipho)

    # ── Ticket 2 — RESOLVED with feedback ────────────────────────────────────
    t2 = make_ticket(
        student            = keegan,
        staff              = james,
        dept               = finance,
        title              = 'NSFAS allowance not received for March',
        description        = ('I have not received my NSFAS monthly allowance for March 2026. '
                              'I have already verified my banking details are correct on the NSFAS portal.'),
        category           = 'Financial',
        priority           = PriorityEnum.High,
        status             = StatusEnum.Resolved,
        created_days_ago   = 22,
        resolved_days_ago  = 10,
        feedback_rating    = 4,
        feedback_comment   = 'Took a bit long but was resolved.',
    )
    add_update(t2, james,  'Investigating with NSFAS directly.',
               UpdateStatusEnum.InProgress, when_days_ago=21)
    u2_reply = add_update(t2, james,
               'Can you please confirm your student number and ID number so I can follow up?',
               UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=19)
    add_update(t2, keegan, 'My student number is 21301456 and ID is 0204125****.',
               parent_id=u2_reply.UpdateId, when_days_ago=18)
    add_update(t2, james,  '[RESOLVED] NSFAS confirmed payment was processed. '
               'Funds should reflect within 2 business days.',
               UpdateStatusEnum.Resolved, when_days_ago=10)
    notify_ticket_assigned(t2)
    notify_staff_reply(t2, james)
    notify_ticket_resolved(t2, james)

    # ── Ticket 3 — IN PROGRESS ────────────────────────────────────────────────
    t3 = make_ticket(
        student          = zanele,
        staff            = priya,
        dept             = academic,
        title            = 'Incorrect timetable allocation for Semester 2',
        description      = ('My semester 2 timetable has me registered for a module I already '
                            'passed last year (MTH201). I need it removed and replaced with MTH301.'),
        category         = 'Academic',
        priority         = PriorityEnum.High,
        status           = StatusEnum.InProgress,
        created_days_ago = 7,
    )
    add_update(t3, priya, 'I have raised this with the timetable office. Expect feedback by end of week.',
               UpdateStatusEnum.InProgress, when_days_ago=6)
    notify_ticket_assigned(t3)
    notify_progress_update(t3, priya)

    # ── Ticket 4 — PENDING INFO ───────────────────────────────────────────────
    t4 = make_ticket(
        student          = rishi,
        staff            = fatima,
        dept             = finance,
        title            = 'Double charge on tuition fee account',
        description      = ('My fee statement shows two charges of R14 500 for the same semester. '
                            'I only registered once and this appears to be a system error.'),
        category         = 'Financial',
        priority         = PriorityEnum.High,
        status           = StatusEnum.PendingInfo,
        created_days_ago = 5,
    )
    add_update(t4, fatima, 'I can see the double entry. Investigating.',
               UpdateStatusEnum.InProgress, when_days_ago=4)
    u4_reply = add_update(t4, fatima,
               'Please upload your fee statement PDF so I can escalate to the finance system team.',
               UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=3)
    notify_ticket_assigned(t4)
    notify_staff_reply(t4, fatima)

    # ── Ticket 5 — ASSIGNED ───────────────────────────────────────────────────
    t5 = make_ticket(
        student          = chloe,
        staff            = rajan,
        dept             = facilities,
        title            = 'Broken air conditioning in E-Block lecture hall',
        description      = ('The air conditioning unit in E-Block room 204 has not been working '
                            'for two weeks. With summer temperatures the room is unbearable for '
                            'lectures scheduled between 10:00 and 14:00.'),
        category         = 'Facilities',
        priority         = PriorityEnum.Medium,
        status           = StatusEnum.Assigned,
        created_days_ago = 3,
    )
    notify_ticket_assigned(t5)

    # ── Ticket 6 — IN PROGRESS ────────────────────────────────────────────────
    t6 = make_ticket(
        student          = lethiwe,
        staff            = nomsa,
        dept             = it_dept,
        title            = 'Cannot access student email account',
        description      = ('My DUT student email account has been locked. '
                            'I receive a "Your account has been disabled" message when trying to log in. '
                            'I need access urgently to receive exam correspondence.'),
        category         = 'IT Support',
        priority         = PriorityEnum.Medium,
        status           = StatusEnum.InProgress,
        created_days_ago = 4,
    )
    add_update(t6, nomsa, 'Account identified. Resetting through the Active Directory portal now.',
               UpdateStatusEnum.InProgress, when_days_ago=3)
    notify_ticket_assigned(t6)
    notify_progress_update(t6, nomsa)

    # ── Ticket 7 — RESOLVED with low rating ──────────────────────────────────
    t7 = make_ticket(
        student            = mohammed,
        staff              = thabo,
        dept               = it_dept,
        title              = 'Campus Wi-Fi drops every 10 minutes in library',
        description        = ('The Wi-Fi in the main library (Level 2 and Level 3) disconnects '
                              'every 10–15 minutes. This has been ongoing for 3 weeks and makes '
                              'online research impossible.'),
        category           = 'IT Support',
        priority           = PriorityEnum.Medium,
        status             = StatusEnum.Resolved,
        created_days_ago   = 25,
        resolved_days_ago  = 8,
        feedback_rating    = 3,
        feedback_comment   = 'Problem was resolved but took much longer than expected.',
    )
    add_update(t7, thabo, 'Logged with network infrastructure team.',
               UpdateStatusEnum.InProgress, when_days_ago=24)
    u7_reply = add_update(t7, thabo,
               'Can you confirm which access points you see when the drop occurs? '
               'Please check the network name (e.g. DUT-Student-2G or 5G).',
               UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=22)
    add_update(t7, mohammed, 'It shows DUT-Student-5G on level 2 and DUT-Student-2G on level 3.',
               parent_id=u7_reply.UpdateId, when_days_ago=21)
    add_update(t7, thabo, '[RESOLVED] Access point firmware updated. Connection should be stable.',
               UpdateStatusEnum.Resolved, when_days_ago=8)
    notify_ticket_assigned(t7)
    notify_staff_reply(t7, thabo)
    notify_ticket_resolved(t7, thabo)

    # ── Ticket 8 — PENDING INFO ───────────────────────────────────────────────
    t8 = make_ticket(
        student          = tayla,
        staff            = linda,
        dept             = housing,
        title            = 'Room transfer request — noise complaint',
        description      = ('I have been unable to sleep due to excessive noise from the room '
                            'next door in Residence Block C. I have spoken to the occupants twice '
                            'with no improvement. I am requesting a transfer to Block A or B.'),
        category         = 'Accommodation',
        priority         = PriorityEnum.Medium,
        status           = StatusEnum.PendingInfo,
        created_days_ago = 6,
    )
    add_update(t8, linda, 'Transfer request noted. Checking availability.',
               UpdateStatusEnum.InProgress, when_days_ago=5)
    u8_reply = add_update(t8, linda,
               'Please confirm your current room number and student number '
               'so I can pull up your residence record.',
               UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=4)
    notify_ticket_assigned(t8)
    notify_staff_reply(t8, linda)

    # ── Ticket 9 — SUBMITTED (unassigned — triggers admin notification) ───────
    t9 = make_ticket(
        student          = ayanda,
        staff            = None,
        dept             = admin_dept,
        title            = 'Wrong qualification on academic record',
        description      = ('My academic transcript shows "Diploma in Business Studies" '
                            'but I am registered for "Bachelor of Commerce". '
                            'This needs to be corrected urgently as I need the transcript for a bursary application.'),
        category         = 'Administration',
        priority         = PriorityEnum.Low,
        status           = StatusEnum.Submitted,
        created_days_ago = 1,
    )
    # Simulate unassigned admin notification
    from app.models.admin_notification import AdminNotification
    db.session.add(AdminNotification(
        Type     = 'unassigned_ticket',
        Message  = (f'Ticket #{t9.TicketId} "{t9.Title}" has no staff '
                    f'in its department and was left unassigned.'),
        TicketId = t9.TicketId,
        IsRead   = False,
        CreatedAt = days_ago(1),
    ))

    # ── Ticket 10 — REJECTED ─────────────────────────────────────────────────
    t10 = make_ticket(
        student          = keegan,
        staff            = mandla,
        dept             = admin_dept,
        title            = 'Request for extra library printing credits',
        description      = ('I have used all my monthly printing credits and need additional '
                            'credits to print my final year project draft before submission.'),
        category         = 'Administration',
        priority         = PriorityEnum.Low,
        status           = StatusEnum.Rejected,
        created_days_ago = 12,
    )
    add_update(t10, mandla,
               'Printing credit top-ups fall outside the scope of the grievance portal. '
               'Please contact the library directly at library@dut.ac.za.',
               UpdateStatusEnum.Rejected, when_days_ago=11)
    notify_ticket_assigned(t10)
    notify_ticket_rejected(t10, mandla)

    # ── Ticket 11 — RESOLVED with thread showing full conversation ────────────
    t11 = make_ticket(
        student            = zanele,
        staff              = james,
        dept               = finance,
        title              = 'Bursary payment not reflected after confirmation letter',
        description        = ('I received a confirmation letter from my bursary provider '
                              'three weeks ago stating that payment was made to DUT. '
                              'However my fee account still shows the full amount outstanding.'),
        category           = 'Financial',
        priority           = PriorityEnum.High,
        status             = StatusEnum.Resolved,
        created_days_ago   = 30,
        resolved_days_ago  = 15,
        feedback_rating    = 5,
        feedback_comment   = 'James followed up multiple times and kept me informed throughout.',
    )
    add_update(t11, james, 'Bursary payment confirmed received from finance system.',
               UpdateStatusEnum.InProgress, when_days_ago=29)
    u11_reply = add_update(t11, james,
               'Please forward the confirmation letter from your bursary provider '
               'to bursaries@dut.ac.za and copy me in.',
               UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=28)
    add_update(t11, zanele,
               'Email sent. The reference number on the letter is BUR-2026-00412.',
               parent_id=u11_reply.UpdateId, when_days_ago=27)
    add_update(t11, james,
               'Payment has been allocated to your account. Please allow 24 hours for the portal to update.',
               parent_id=u11_reply.UpdateId, when_days_ago=16)
    add_update(t11, james, '[RESOLVED] Payment reflected on student account.',
               UpdateStatusEnum.Resolved, when_days_ago=15)
    notify_ticket_assigned(t11)
    notify_staff_reply(t11, james)
    notify_ticket_resolved(t11, james)

    # ── Ticket 12 — IN PROGRESS ───────────────────────────────────────────────
    t12 = make_ticket(
        student          = rishi,
        staff            = sipho,
        dept             = academic,
        title            = 'Lecturer absence not communicated for 2 weeks',
        description      = ('Our BUS401 lecturer has not attended any lectures for two weeks '
                            'and no replacement or online materials have been provided. '
                            'We have a test scheduled in 10 days.'),
        category         = 'Academic',
        priority         = PriorityEnum.High,
        status           = StatusEnum.InProgress,
        created_days_ago = 9,
    )
    add_update(t12, sipho,
               'Raised with the head of department. A replacement lecturer will be confirmed by tomorrow.',
               UpdateStatusEnum.InProgress, when_days_ago=8)
    notify_ticket_assigned(t12)
    notify_progress_update(t12, sipho)

    # ── Ticket 13 — ASSIGNED ─────────────────────────────────────────────────
    t13 = make_ticket(
        student          = chloe,
        staff            = nomsa,
        dept             = it_dept,
        title            = 'Blackboard not loading course materials',
        description      = ('Since the Blackboard update last Monday I cannot access any '
                            'course materials for my registered modules. '
                            'The page loads but shows "No content available" for all modules.'),
        category         = 'IT Support',
        priority         = PriorityEnum.Medium,
        status           = StatusEnum.Assigned,
        created_days_ago = 2,
    )
    notify_ticket_assigned(t13)

    # ── Ticket 14 — RESOLVED ─────────────────────────────────────────────────
    t14 = make_ticket(
        student            = lethiwe,
        staff              = linda,
        dept               = housing,
        title              = 'Hot water outage in Block D for 5 days',
        description        = ('There has been no hot water in Block D since Monday. '
                              'Maintenance was called but no one arrived. '
                              'We need this fixed as a matter of urgency.'),
        category           = 'Accommodation',
        priority           = PriorityEnum.Medium,
        status             = StatusEnum.Resolved,
        created_days_ago   = 14,
        resolved_days_ago  = 7,
        feedback_rating    = 4,
        feedback_comment   = 'Linda escalated quickly to maintenance.',
    )
    add_update(t14, linda,
               'Maintenance team notified. Fault logged as priority repair.',
               UpdateStatusEnum.InProgress, when_days_ago=13)
    add_update(t14, linda,
               '[RESOLVED] Plumber confirmed repair completed. Hot water restored.',
               UpdateStatusEnum.Resolved, when_days_ago=7)
    notify_ticket_assigned(t14)
    notify_ticket_resolved(t14, linda)

    # ── Ticket 15 — SUBMITTED ────────────────────────────────────────────────
    t15 = make_ticket(
        student          = mohammed,
        staff            = thabo,
        dept             = it_dept,
        title            = 'Computer lab PCs freezing during practical sessions',
        description      = ('All PCs in Lab G-07 freeze within 20 minutes of being used. '
                            'This is affecting our CAD practical sessions. '
                            'The issue started after the Windows update two weeks ago.'),
        category         = 'IT Support',
        priority         = PriorityEnum.Medium,
        status           = StatusEnum.Assigned,
        created_days_ago = 1,
    )
    notify_ticket_assigned(t15)

    # ── 6. Announcements ──────────────────────────────────────────────────────
    announcements_data = [
        (
            'System Maintenance — Saturday 14 March',
            'The student portal will be unavailable from 22:00 on Saturday 14 March to '
            '06:00 on Sunday 15 March for scheduled maintenance. Please plan accordingly.',
            'All',
        ),
        (
            'Semester 2 Registration Now Open',
            'Semester 2 registration is open from 1 April to 15 April 2026. '
            'Log in to the student portal to register your modules. '
            'Late registrations will incur a penalty fee.',
            'Student',
        ),
        (
            'Staff Training — Grievance Portal Update',
            'A 30-minute walkthrough of the new features on the grievance portal will be '
            'held on Wednesday 11 March at 10:00 via MS Teams. Link sent to your DUT email.',
            'Staff',
        ),
        (
            'Examination Timetables Published',
            'Semester 1 examination timetables are now available on the student portal. '
            'Please check your timetable and report any clashes immediately via the grievance portal.',
            'Student',
        ),
    ]

    for title, message, audience in announcements_data:
        existing = Announcement.query.filter_by(Title=title).first()
        if not existing:
            db.session.add(Announcement(
                Title          = title,
                Message        = message,
                TargetAudience = audience,
                CreatedBy      = admin_user.UserId,
                IsActive       = True,
                CreatedAt      = days_ago(random.randint(1, 10)),
            ))

    # ── 7. Commit everything ──────────────────────────────────────────────────
    db.session.commit()
    print('\n' + '═' * 65)
    print('  ✅  TEST DATA SEEDED SUCCESSFULLY')
    print('═' * 65)

    print('\n── ADMIN ──────────────────────────────────────────────────────')
    print(f'  {"Email":<42} {"Password"}')
    print(f'  {"admin@dut.ac.za":<42} Admin@1234')

    print('\n── STAFF ──────────────────────────────────────────────────────')
    print(f'  {"Email":<42} {"Password":<12} {"Department"}')
    for name, email, pw, dept in staff_data:
        print(f'  {email:<42} {pw:<12} {dept.Name}')

    print('\n── STUDENTS ────────────────────────────────────────────────────')
    print(f'  {"Email":<48} {"Password"}')
    for name, email, pw in student_data:
        print(f'  {email:<48} {pw}')

    print('\n── TICKETS CREATED ─────────────────────────────────────────────')
    tickets_summary = [
        (t1,  'Ayanda → Sipho',    'Resolved ⭐⭐⭐⭐⭐'),
        (t2,  'Keegan → James',    'Resolved ⭐⭐⭐⭐'),
        (t3,  'Zanele → Priya',    'In Progress'),
        (t4,  'Rishi  → Fatima',   'Pending Info'),
        (t5,  'Chloe  → Rajan',    'Assigned'),
        (t6,  'Lethiwe → Nomsa',   'In Progress'),
        (t7,  'Mohammed → Thabo',  'Resolved ⭐⭐⭐'),
        (t8,  'Tayla  → Linda',    'Pending Info'),
        (t9,  'Ayanda → Unassigned','Submitted (admin notif)'),
        (t10, 'Keegan → Mandla',   'Rejected'),
        (t11, 'Zanele → James',    'Resolved ⭐⭐⭐⭐⭐'),
        (t12, 'Rishi  → Sipho',    'In Progress'),
        (t13, 'Chloe  → Nomsa',    'Assigned'),
        (t14, 'Lethiwe → Linda',   'Resolved ⭐⭐⭐⭐'),
        (t15, 'Mohammed → Thabo',  'Assigned'),
    ]
    for t, parties, status in tickets_summary:
        print(f'  #{t.TicketId:<4} {parties:<26} {status}')

    print('\n── ANNOUNCEMENTS ───────────────────────────────────────────────')
    for title, _, audience in announcements_data:
        print(f'  [{audience:<7}] {title}')

    print('\n' + '═' * 65 + '\n')