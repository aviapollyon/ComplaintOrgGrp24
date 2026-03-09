"""
seed_test_data.py
Run once after flask db upgrade.

Usage:
    python seed_test_data.py

Covers all 14 categories:
    Academic, Financial, Examination, Bursary & Funding, Registration,
    Facilities, IT Support, Accommodation, Health & Wellness,
    Library, Transport, Administration, Student Conduct, Other

Deliberately triggers keyword flags on:
    - IT Support / "wifi"        (3+ tickets)
    - Academic   / "result"      (3+ tickets)
    - Financial  / "nsfas"       (3+ tickets)
    - Facilities / "broken"      (3+ tickets)
"""

from app import create_app, db
from app.models.department         import Department
from app.models.user               import User, RoleEnum
from app.models.ticket             import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update      import TicketUpdate, UpdateStatusEnum
from app.models.announcement       import Announcement
from app.models.admin_notification import AdminNotification
from app.utils.helpers             import check_and_raise_flags
from app.services.notifications    import (
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


# ── helpers ─────────────────────��─────────────────────────────────────────────

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
    u = TicketUpdate(
        TicketId       = ticket.TicketId,
        UserId         = author.UserId,
        Comment        = comment,
        StatusChange   = status_change,
        IsReplyThread  = is_reply_thread,
        ParentUpdateId = parent_id,
        CreatedAt      = days_ago(when_days_ago or 0, random.randint(0, 3)),
    )
    db.session.add(u)
    db.session.flush()
    return u


# ─────────────────────────────────────────────────────────────────────────────
with app.app_context():

    # ── 1. Departments ────��───────────────────────────────────────────────────
    dept_names = [
        'Academic Affairs',
        'Finance & Accounts',
        'Facilities Management',
        'Information Technology',
        'Student Housing',
        'Student Administration',
    ]
    dept_map = {}
    for name in dept_names:
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

    # ── 2. Admin ──────────────────────────────────────────────────────────────
    admin_user = User.query.filter_by(Email='admin@dut.ac.za').first()
    if not admin_user:
        admin_user = make_user(
            'System Admin', 'admin@dut.ac.za', 'Admin@1234',
            RoleEnum.Admin, None
        )
        db.session.flush()

    # ── 3. Staff ──────────────────────────────────────────────────────────────
    staff_data = [
        ('Sipho Nkosi',    'sipho.nkosi@dut.ac.za',    'Staff@1234', academic),
        ('Priya Pillay',   'priya.pillay@dut.ac.za',   'Staff@1234', academic),
        ('James Mokoena',  'james.mokoena@dut.ac.za',  'Staff@1234', finance),
        ('Fatima Dlamini', 'fatima.dlamini@dut.ac.za', 'Staff@1234', finance),
        ('Rajan Govender', 'rajan.govender@dut.ac.za', 'Staff@1234', facilities),
        ('Nomsa Zulu',     'nomsa.zulu@dut.ac.za',     'Staff@1234', it_dept),
        ('Thabo Sithole',  'thabo.sithole@dut.ac.za',  'Staff@1234', it_dept),
        ('Linda Maharaj',  'linda.maharaj@dut.ac.za',  'Staff@1234', housing),
        ('Mandla Khumalo', 'mandla.khumalo@dut.ac.za', 'Staff@1234', admin_dept),
    ]
    staff_users = {}
    for full_name, email, pw, dept in staff_data:
        u = User.query.filter_by(Email=email).first()
        if not u:
            u = make_user(full_name, email, pw, RoleEnum.Staff, dept)
            db.session.flush()
        staff_users[email] = u

    sipho  = staff_users['sipho.nkosi@dut.ac.za']
    priya  = staff_users['priya.pillay@dut.ac.za']
    james  = staff_users['james.mokoena@dut.ac.za']
    fatima = staff_users['fatima.dlamini@dut.ac.za']
    rajan  = staff_users['rajan.govender@dut.ac.za']
    nomsa  = staff_users['nomsa.zulu@dut.ac.za']
    thabo  = staff_users['thabo.sithole@dut.ac.za']
    linda  = staff_users['linda.maharaj@dut.ac.za']
    mandla = staff_users['mandla.khumalo@dut.ac.za']

    # ── 4. Students ───────────────────────────────────────────────────────────
    student_data = [
        ('Ayanda Mthembu',  'ayanda.mthembu@student.dut.ac.za',  'Student@1234'),
        ('Keegan Peters',   'keegan.peters@student.dut.ac.za',   'Student@1234'),
        ('Zanele Ntuli',    'zanele.ntuli@student.dut.ac.za',    'Student@1234'),
        ('Rishi Naidoo',    'rishi.naidoo@student.dut.ac.za',    'Student@1234'),
        ('Chloe van Wyk',   'chloe.vanwyk@student.dut.ac.za',   'Student@1234'),
        ('Lethiwe Cele',    'lethiwe.cele@student.dut.ac.za',    'Student@1234'),
        ('Mohammed Cassim', 'mohammed.cassim@student.dut.ac.za', 'Student@1234'),
        ('Tayla Botha',     'tayla.botha@student.dut.ac.za',     'Student@1234'),
    ]
    student_users = {}
    for full_name, email, pw in student_data:
        u = User.query.filter_by(Email=email).first()
        if not u:
            u = make_user(full_name, email, pw, RoleEnum.Student, None)
            db.session.flush()
        student_users[email] = u

    ayanda   = student_users['ayanda.mthembu@student.dut.ac.za']
    keegan   = student_users['keegan.peters@student.dut.ac.za']
    zanele   = student_users['zanele.ntuli@student.dut.ac.za']
    rishi    = student_users['rishi.naidoo@student.dut.ac.za']
    chloe    = student_users['chloe.vanwyk@student.dut.ac.za']
    lethiwe  = student_users['lethiwe.cele@student.dut.ac.za']
    mohammed = student_users['mohammed.cassim@student.dut.ac.za']
    tayla    = student_users['tayla.botha@student.dut.ac.za']

    # =========================================================================
    # 5. TICKETS  (25 total — all 14 categories, flag triggers included)
    # =========================================================================

    # ── ACADEMIC (3 tickets — flags "result") ────────────────────────────────

    t1 = make_ticket(
        ayanda, sipho, academic,
        'Missing module result for BUS301',
        'My result for BUS301 does not appear on the student portal even though I wrote '
        'the exam three weeks ago. I need this resolved before the supplementary exam deadline.',
        'Academic', PriorityEnum.High, StatusEnum.Resolved,
        created_days_ago=18, resolved_days_ago=5,
        feedback_rating=5, feedback_comment='Sipho resolved this very quickly.',
    )
    add_update(t1, sipho, 'Contacting the examinations office about this result.',
               UpdateStatusEnum.InProgress, when_days_ago=17)
    add_update(t1, sipho, '[RESOLVED] Result has been captured. Please check your portal.',
               UpdateStatusEnum.Resolved, when_days_ago=5)
    notify_ticket_assigned(t1)
    notify_ticket_resolved(t1, sipho)

    t2 = make_ticket(
        zanele, priya, academic,
        'Incorrect timetable allocation — MTH201 result not carried over',
        'My semester 2 timetable still shows MTH201 even though my result from last year '
        'should have cleared the prerequisite. The system has not updated.',
        'Academic', PriorityEnum.High, StatusEnum.InProgress,
        created_days_ago=7,
    )
    add_update(t2, priya, 'Raised with the timetable office. The result record is being verified.',
               UpdateStatusEnum.InProgress, when_days_ago=6)
    notify_ticket_assigned(t2)
    notify_progress_update(t2, priya)

    t3 = make_ticket(
        rishi, sipho, academic,
        'Lecturer absent for two weeks — no result or feedback provided',
        'Our BUS401 lecturer has not attended any lectures for two weeks and no results '
        'from the last assessment have been returned. We have a test in 10 days.',
        'Academic', PriorityEnum.High, StatusEnum.InProgress,
        created_days_ago=9,
    )
    add_update(t3, sipho,
               'Raised with the head of department. A replacement lecturer will be confirmed.',
               UpdateStatusEnum.InProgress, when_days_ago=8)
    notify_ticket_assigned(t3)
    notify_progress_update(t3, sipho)
    # ► "result" appears in all 3 Academic tickets → flag triggered

    # ── FINANCIAL (3 tickets — flags "nsfas") ────────────────────────────────

    t4 = make_ticket(
        keegan, james, finance,
        'NSFAS allowance not received for March',
        'I have not received my NSFAS monthly allowance for March 2026. '
        'My banking details on the NSFAS portal are verified and correct.',
        'Financial', PriorityEnum.High, StatusEnum.Resolved,
        created_days_ago=22, resolved_days_ago=10,
        feedback_rating=4, feedback_comment='Took some time but was resolved.',
    )
    add_update(t4, james, 'Investigating with NSFAS directly.',
               UpdateStatusEnum.InProgress, when_days_ago=21)
    u4r = add_update(t4, james,
                     'Please confirm your student number and ID so I can follow up with NSFAS.',
                     UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=19)
    add_update(t4, keegan, 'Student number: 21301456, ID: 0204125****.',
               parent_id=u4r.UpdateId, when_days_ago=18)
    add_update(t4, james, '[RESOLVED] NSFAS confirmed payment processed. Funds reflect in 2 days.',
               UpdateStatusEnum.Resolved, when_days_ago=10)
    notify_ticket_assigned(t4)
    notify_staff_reply(t4, james)
    notify_ticket_resolved(t4, james)

    t5 = make_ticket(
        rishi, fatima, finance,
        'Double charge on tuition fee account',
        'My fee statement shows two charges of R14 500 for the same semester. '
        'I only registered once — this appears to be a system error.',
        'Financial', PriorityEnum.High, StatusEnum.PendingInfo,
        created_days_ago=5,
    )
    add_update(t5, fatima, 'I can see the double entry. Investigating now.',
               UpdateStatusEnum.InProgress, when_days_ago=4)
    u5r = add_update(t5, fatima,
                     'Please upload your fee statement PDF so I can escalate to the finance team.',
                     UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=3)
    notify_ticket_assigned(t5)
    notify_staff_reply(t5, fatima)

    t6 = make_ticket(
        zanele, james, finance,
        'NSFAS bursary payment not reflected after confirmation letter',
        'I received a confirmation letter from my bursary provider three weeks ago '
        'stating that NSFAS payment was made to DUT. My fee account still shows the '
        'full amount outstanding.',
        'Financial', PriorityEnum.High, StatusEnum.Resolved,
        created_days_ago=30, resolved_days_ago=15,
        feedback_rating=5, feedback_comment='James followed up multiple times.',
    )
    add_update(t6, james, 'NSFAS payment confirmed received from finance system.',
               UpdateStatusEnum.InProgress, when_days_ago=29)
    u6r = add_update(t6, james,
                     'Please forward the bursary confirmation letter to bursaries@dut.ac.za.',
                     UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=28)
    add_update(t6, zanele, 'Email sent. Reference: BUR-2026-00412.',
               parent_id=u6r.UpdateId, when_days_ago=27)
    add_update(t6, james, 'Payment allocated. Portal will update within 24 hours.',
               parent_id=u6r.UpdateId, when_days_ago=16)
    add_update(t6, james, '[RESOLVED] NSFAS payment reflected on student account.',
               UpdateStatusEnum.Resolved, when_days_ago=15)
    notify_ticket_assigned(t6)
    notify_staff_reply(t6, james)
    notify_ticket_resolved(t6, james)
    # ► "nsfas" in t4, t5, t6 → flag triggered

    # ── EXAMINATION ───────────────────────────────────────────────────────────

    t7 = make_ticket(
        chloe, priya, academic,
        'Exam timetable clash — two exams scheduled at the same time',
        'My semester 1 exam timetable has a clash: ACC201 and MKT301 are both scheduled '
        'for 14 May at 08:00. I need one deferred or moved to avoid the clash.',
        'Examination', PriorityEnum.High, StatusEnum.InProgress,
        created_days_ago=4,
    )
    add_update(t7, priya,
               'Timetable clash confirmed. Submitted a deferral request to the exams office.',
               UpdateStatusEnum.InProgress, when_days_ago=3)
    notify_ticket_assigned(t7)
    notify_progress_update(t7, priya)

    # ── BURSARY & FUNDING ─────────────────────────────────────────────────────

    t8 = make_ticket(
        lethiwe, james, finance,
        'Bursary allocation not reflecting on student account',
        'My external bursary provider (Sasol Bursary Programme) confirmed that the '
        'bursary allocation was sent to DUT on 1 March. It does not reflect on my account.',
        'Bursary & Funding', PriorityEnum.High, StatusEnum.Assigned,
        created_days_ago=3,
    )
    notify_ticket_assigned(t8)

    # ── REGISTRATION ──────────────────────────────────────────────────────────

    t9 = make_ticket(
        mohammed, mandla, admin_dept,
        'Registration blocked due to outstanding library fine',
        'I am unable to complete my semester 2 registration. The system shows '
        '"Outstanding obligations" but the only item is a library fine I paid last week. '
        'I have a receipt but the block has not been lifted.',
        'Registration', PriorityEnum.High, StatusEnum.InProgress,
        created_days_ago=6,
    )
    add_update(t9, mandla,
               'Confirmed library fine was paid. Requesting IT to clear the registration block.',
               UpdateStatusEnum.InProgress, when_days_ago=5)
    notify_ticket_assigned(t9)
    notify_progress_update(t9, mandla)

    # ── FACILITIES (3 tickets — flags "broken") ───────────────────────────────

    t10 = make_ticket(
        chloe, rajan, facilities,
        'Broken air conditioning in E-Block lecture hall',
        'The air conditioning unit in E-Block room 204 has been broken for two weeks. '
        'With summer temperatures the room is unbearable for lectures at 10:00–14:00.',
        'Facilities', PriorityEnum.Medium, StatusEnum.Assigned,
        created_days_ago=3,
    )
    notify_ticket_assigned(t10)

    t11 = make_ticket(
        tayla, rajan, facilities,
        'Broken projector in A-Block seminar room A105',
        'The projector in A105 is broken and has been out of order for over a week. '
        'Three lecture groups use this room and presenters are unable to display slides.',
        'Facilities', PriorityEnum.Medium, StatusEnum.InProgress,
        created_days_ago=8,
    )
    add_update(t11, rajan, 'Logged with AV maintenance team. Replacement unit being sourced.',
               UpdateStatusEnum.InProgress, when_days_ago=7)
    notify_ticket_assigned(t11)
    notify_progress_update(t11, rajan)

    t12 = make_ticket(
        ayanda, rajan, facilities,
        'Broken hand dryers and no paper towels in B-Block bathrooms',
        'All hand dryers in the B-Block ground floor bathrooms are broken. '
        'There are also no paper towels. This has been the case for over five days.',
        'Facilities', PriorityEnum.Medium, StatusEnum.Resolved,
        created_days_ago=14, resolved_days_ago=7,
        feedback_rating=4, feedback_comment='Fixed quickly once logged.',
    )
    add_update(t12, rajan,
               'Maintenance team dispatched. Paper towels restocked and dryers repaired.',
               UpdateStatusEnum.InProgress, when_days_ago=13)
    add_update(t12, rajan, '[RESOLVED] All dryers operational and bathrooms restocked.',
               UpdateStatusEnum.Resolved, when_days_ago=7)
    notify_ticket_assigned(t12)
    notify_ticket_resolved(t12, rajan)
    # ► "broken" in t10, t11, t12 → flag triggered

    # ── IT SUPPORT (3 tickets — flags "wifi") ────────────────────────────────

    t13 = make_ticket(
        lethiwe, nomsa, it_dept,
        'Cannot access student email account',
        'My DUT student email account has been locked. I receive "Your account has been '
        'disabled" when trying to log in. I need access urgently for exam correspondence.',
        'IT Support', PriorityEnum.Medium, StatusEnum.InProgress,
        created_days_ago=4,
    )
    add_update(t13, nomsa,
               'Account identified. Resetting through Active Directory now.',
               UpdateStatusEnum.InProgress, when_days_ago=3)
    notify_ticket_assigned(t13)
    notify_progress_update(t13, nomsa)

    t14 = make_ticket(
        mohammed, thabo, it_dept,
        'Campus wifi drops every 10 minutes in the library',
        'The wifi in the main library (Level 2 and Level 3) disconnects every 10–15 minutes. '
        'This has been ongoing for 3 weeks and makes online research impossible.',
        'IT Support', PriorityEnum.Medium, StatusEnum.Resolved,
        created_days_ago=25, resolved_days_ago=8,
        feedback_rating=3, feedback_comment='Took longer than expected but resolved.',
    )
    add_update(t14, thabo, 'Logged with network infrastructure team.',
               UpdateStatusEnum.InProgress, when_days_ago=24)
    u14r = add_update(t14, thabo,
                      'Confirm which access point shows when the wifi drops (2G or 5G)?',
                      UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=22)
    add_update(t14, mohammed, 'DUT-Student-5G on level 2, DUT-Student-2G on level 3.',
               parent_id=u14r.UpdateId, when_days_ago=21)
    add_update(t14, thabo, '[RESOLVED] Access point firmware updated. Connection stable.',
               UpdateStatusEnum.Resolved, when_days_ago=8)
    notify_ticket_assigned(t14)
    notify_staff_reply(t14, thabo)
    notify_ticket_resolved(t14, thabo)

    t15 = make_ticket(
        keegan, nomsa, it_dept,
        'Wifi not available in postgraduate labs — wifi password changed without notice',
        'The wifi password in the postgraduate computer labs was changed last Monday. '
        'No notice was sent to students. We cannot connect to the internet for research.',
        'IT Support', PriorityEnum.Medium, StatusEnum.Resolved,
        created_days_ago=12, resolved_days_ago=9,
        feedback_rating=5, feedback_comment='Nomsa sent the new credentials immediately.',
    )
    add_update(t15, nomsa,
               '[RESOLVED] New wifi credentials emailed to all postgrad lab users.',
               UpdateStatusEnum.Resolved, when_days_ago=9)
    notify_ticket_assigned(t15)
    notify_ticket_resolved(t15, nomsa)
    # ► "wifi" in t14, t15 + t16 below → flag triggered

    t16 = make_ticket(
        chloe, thabo, it_dept,
        'Blackboard not loading course materials — wifi login loop',
        'Since the Blackboard update last Monday I cannot access course materials. '
        'The page loads but shows "No content available". The wifi login also redirects '
        'me in a loop and I cannot authenticate properly.',
        'IT Support', PriorityEnum.Medium, StatusEnum.Assigned,
        created_days_ago=2,
    )
    notify_ticket_assigned(t16)
    # ► "wifi" now appears in t14, t15, t16 → 3 tickets → flag raised

    # ── ACCOMMODATION ─────────────────────────────────────────────────────────

    t17 = make_ticket(
        tayla, linda, housing,
        'Room transfer request — noise complaint Block C',
        'I have been unable to sleep due to excessive noise from the room next door in '
        'Block C. I have spoken to the occupants twice with no improvement.',
        'Accommodation', PriorityEnum.Medium, StatusEnum.PendingInfo,
        created_days_ago=6,
    )
    add_update(t17, linda, 'Transfer request noted. Checking room availability.',
               UpdateStatusEnum.InProgress, when_days_ago=5)
    u17r = add_update(t17, linda,
                      'Please confirm your current room number and student number.',
                      UpdateStatusEnum.PendingInfo, is_reply_thread=True, when_days_ago=4)
    notify_ticket_assigned(t17)
    notify_staff_reply(t17, linda)

    t18 = make_ticket(
        lethiwe, linda, housing,
        'Hot water outage in Block D for 5 days',
        'There has been no hot water in Block D since Monday. Maintenance was called '
        'but no one arrived. We need this fixed as a matter of urgency.',
        'Accommodation', PriorityEnum.Medium, StatusEnum.Resolved,
        created_days_ago=14, resolved_days_ago=7,
        feedback_rating=4, feedback_comment='Linda escalated quickly to maintenance.',
    )
    add_update(t18, linda, 'Maintenance team notified. Fault logged as priority repair.',
               UpdateStatusEnum.InProgress, when_days_ago=13)
    add_update(t18, linda, '[RESOLVED] Plumber confirmed repair completed. Hot water restored.',
               UpdateStatusEnum.Resolved, when_days_ago=7)
    notify_ticket_assigned(t18)
    notify_ticket_resolved(t18, linda)

    # ── HEALTH & WELLNESS ─────────────────────────────────────────────────────

    t19 = make_ticket(
        ayanda, mandla, admin_dept,
        'Request for counselling referral — exam stress and anxiety',
        'I have been experiencing severe exam anxiety and stress that is affecting my '
        'ability to study. I would like to be referred to the campus counselling service '
        'and understand what support is available to me.',
        'Health & Wellness', PriorityEnum.Medium, StatusEnum.Resolved,
        created_days_ago=10, resolved_days_ago=6,
        feedback_rating=5, feedback_comment='Mandla was very supportive and acted quickly.',
    )
    add_update(t19, mandla,
               '[RESOLVED] Referral sent to Student Wellness. You will receive an appointment '
               'within 2 working days.',
               UpdateStatusEnum.Resolved, when_days_ago=6)
    notify_ticket_assigned(t19)
    notify_ticket_resolved(t19, mandla)

    # ── LIBRARY ───────────────────────────────────────────────────────────────

    t20 = make_ticket(
        keegan, mandla, admin_dept,
        'Request for extra library printing credits',
        'I have used all my monthly printing credits and need additional credits to print '
        'my final year project draft before submission.',
        'Library', PriorityEnum.Low, StatusEnum.Rejected,
        created_days_ago=12,
    )
    add_update(t20, mandla,
               'Printing credit top-ups are outside the scope of this portal. '
               'Please contact the library directly at library@dut.ac.za.',
               UpdateStatusEnum.Rejected, when_days_ago=11)
    notify_ticket_assigned(t20)
    notify_ticket_rejected(t20, mandla)

    # ── TRANSPORT ─────────────────────────────────────────────────────────────

    t21 = make_ticket(
        rishi, rajan, facilities,
        'Campus shuttle bus not arriving at scheduled times',
        'The campus shuttle bus that runs between the Steve Biko and ML Sultan campuses '
        'has been arriving 30–45 minutes late every day this week. Students are missing '
        'the first lecture of the day as a result.',
        'Transport', PriorityEnum.Low, StatusEnum.InProgress,
        created_days_ago=5,
    )
    add_update(t21, rajan,
               'Reported to the transport coordinator. Updated schedule being circulated.',
               UpdateStatusEnum.InProgress, when_days_ago=4)
    notify_ticket_assigned(t21)
    notify_progress_update(t21, rajan)

    # ── ADMINISTRATION ────────────────────────────────────────────────────────

    t22 = make_ticket(
        ayanda, mandla, admin_dept,
        'Wrong qualification on academic record — transcript error',
        'My academic transcript shows "Diploma in Business Studies" but I am registered '
        'for "Bachelor of Commerce". This needs correction urgently for a bursary application.',
        'Administration', PriorityEnum.Low, StatusEnum.Submitted,
        created_days_ago=1,
    )
    # Unassigned admin notification
    db.session.add(AdminNotification(
        Type      = 'unassigned_ticket',
        Message   = (f'Ticket #{t22.TicketId} "{t22.Title}" was submitted '
                     f'but has no staff assigned.'),
        TicketId  = t22.TicketId,
        IsRead    = False,
        CreatedAt = days_ago(1),
    ))

    # ── STUDENT CONDUCT ───────────────────────────────────────────────────────

    t23 = make_ticket(
        tayla, mandla, admin_dept,
        'Harassment complaint against a classmate',
        'A classmate has been making repeated offensive comments directed at me during '
        'group project sessions. I have asked them to stop but the behaviour continues. '
        'I would like to formally report this misconduct.',
        'Student Conduct', PriorityEnum.Low, StatusEnum.InProgress,
        created_days_ago=7,
    )
    add_update(t23, mandla,
               'Complaint registered. Both parties will be contacted separately for statements.',
               UpdateStatusEnum.InProgress, when_days_ago=6)
    notify_ticket_assigned(t23)
    notify_progress_update(t23, mandla)

    # ── OTHER ─────────────────────────────────────────────────────────────────

    t24 = make_ticket(
        mohammed, thabo, it_dept,
        'Computer lab PCs freezing during CAD practical sessions',
        'All PCs in Lab G-07 freeze within 20 minutes of being used. '
        'This is affecting our CAD practical sessions. The issue started after '
        'the Windows update two weeks ago.',
        'Other', PriorityEnum.Low, StatusEnum.Assigned,
        created_days_ago=1,
    )
    notify_ticket_assigned(t24)

    # ── Extra Academic ticket to push "result" flag over threshold ────────────
    t25 = make_ticket(
        lethiwe, priya, academic,
        'Supplementary exam result not published after 6 weeks',
        'I wrote my supplementary exam for ACC102 six weeks ago. The result has still '
        'not been published on the portal. The supplementary result is required for '
        'my progression to the next academic year.',
        'Academic', PriorityEnum.High, StatusEnum.Assigned,
        created_days_ago=2,
    )
    notify_ticket_assigned(t25)
    # ► "result" now in t1, t2, t3, t25 — four Academic tickets → flag triggered

    # ── 6. Run keyword flag checks ────────────────────────────────────────────
    # Process in submission order so counts accumulate correctly
    for t in [t1, t2, t3, t4, t5, t6, t7, t8, t9,
              t10, t11, t12, t13, t14, t15, t16, t17, t18,
              t19, t20, t21, t22, t23, t24, t25]:
        check_and_raise_flags(t)

    # ── 7. Announcements ──────────────────────────────────────────────────────
    announcements_data = [
        (
            'System Maintenance — Saturday 14 March',
            'The student portal will be unavailable from 22:00 Saturday 14 March to '
            '06:00 Sunday 15 March for scheduled maintenance.',
            'All',
        ),
        (
            'Semester 2 Registration Now Open',
            'Semester 2 registration is open from 1 April to 15 April 2026. '
            'Log in to the student portal to register your modules.',
            'Student',
        ),
        (
            'Staff Training — Grievance Portal Update',
            'A 30-minute walkthrough of new portal features will be held Wednesday '
            '11 March at 10:00 via MS Teams. Link sent to your DUT email.',
            'Staff',
        ),
        (
            'Examination Timetables Published',
            'Semester 1 examination timetables are available on the student portal. '
            'Report any clashes immediately via the grievance portal.',
            'Student',
        ),
    ]
    for title, message, audience in announcements_data:
        if not Announcement.query.filter_by(Title=title).first():
            db.session.add(Announcement(
                Title=title, Message=message,
                TargetAudience=audience,
                CreatedBy=admin_user.UserId,
                IsActive=True,
                CreatedAt=days_ago(random.randint(1, 10)),
            ))

    db.session.commit()

    # ── Print summary ─────────────────────────────────────────────────────────
    print('\n' + '═' * 70)
    print('  ✅  TEST DATA SEEDED SUCCESSFULLY')
    print('═' * 70)

    print('\n── ADMIN ───────────────────────────────────────────────────────────')
    print(f'  {"Email":<45} Password')
    print(f'  {"admin@dut.ac.za":<45} Admin@1234')

    print('\n── STAFF ───────────────���───────────────────────────────────────────')
    print(f'  {"Email":<45} {"Password":<14} Department')
    for name, email, pw, dept in staff_data:
        print(f'  {email:<45} {pw:<14} {dept.Name}')

    print('\n── STUDENTS ────────────────────────────────────────────────────────')
    print(f'  {"Email":<50} Password')
    for name, email, pw in student_data:
        print(f'  {email:<50} {pw}')

    print('\n── TICKETS ─────────────────────────────────────────────────────────')
    ticket_summary = [
        (t1,  'Academic',         'Ayanda → Sipho',    'Resolved ⭐⭐⭐⭐⭐'),
        (t2,  'Academic',         'Zanele → Priya',    'In Progress'),
        (t3,  'Academic',         'Rishi  → Sipho',    'In Progress'),
        (t4,  'Financial',        'Keegan → James',    'Resolved ⭐⭐⭐⭐'),
        (t5,  'Financial',        'Rishi  → Fatima',   'Pending Info'),
        (t6,  'Financial',        'Zanele → James',    'Resolved ⭐⭐⭐⭐⭐'),
        (t7,  'Examination',      'Chloe  → Priya',    'In Progress'),
        (t8,  'Bursary & Funding','Lethiwe → James',   'Assigned'),
        (t9,  'Registration',     'Mohammed → Mandla', 'In Progress'),
        (t10, 'Facilities',       'Chloe  → Rajan',    'Assigned'),
        (t11, 'Facilities',       'Tayla  → Rajan',    'In Progress'),
        (t12, 'Facilities',       'Ayanda → Rajan',    'Resolved ⭐⭐⭐⭐'),
        (t13, 'IT Support',       'Lethiwe → Nomsa',   'In Progress'),
        (t14, 'IT Support',       'Mohammed → Thabo',  'Resolved ⭐⭐⭐'),
        (t15, 'IT Support',       'Keegan → Nomsa',    'Resolved ⭐⭐⭐⭐⭐'),
        (t16, 'IT Support',       'Chloe  → Thabo',    'Assigned'),
        (t17, 'Accommodation',    'Tayla  → Linda',    'Pending Info'),
        (t18, 'Accommodation',    'Lethiwe → Linda',   'Resolved ⭐⭐⭐⭐'),
        (t19, 'Health & Wellness','Ayanda → Mandla',   'Resolved ⭐⭐⭐⭐⭐'),
        (t20, 'Library',          'Keegan → Mandla',   'Rejected'),
        (t21, 'Transport',        'Rishi  → Rajan',    'In Progress'),
        (t22, 'Administration',   'Ayanda → Unassigned','Submitted (admin notif)'),
        (t23, 'Student Conduct',  'Tayla  → Mandla',   'In Progress'),
        (t24, 'Other',            'Mohammed → Thabo',  'Assigned'),
        (t25, 'Academic',         'Lethiwe → Priya',   'Assigned'),
    ]
    print(f'  {"#":<5} {"Category":<20} {"Parties":<28} Status')
    print('  ' + '─' * 65)
    for t, cat, parties, status in ticket_summary:
        print(f'  #{t.TicketId:<4} {cat:<20} {parties:<28} {status}')

    print('\n── KEYWORD FLAGS TRIGGERED ─────────────────────────────────────────')
    from app.models.ticket_flag import TicketFlag
    flags = TicketFlag.query.all()
    for f in flags:
        print(f'  [{f.Category}] keyword="{f.Keyword}" count={f.TicketCount} status={f.Status}')

    print('\n── ANNOUNCEMENTS ───────────────────────────────────────────────────')
    for title, _, audience in announcements_data:
        print(f'  [{audience:<7}] {title}')

    print('\n' + '═' * 70 + '\n')