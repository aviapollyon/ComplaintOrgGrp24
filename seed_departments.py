"""
Run once to seed university departments and create a test admin account.

    python seed_departments.py
"""
from app import create_app, db
from app.models.department import Department
from app.models.user import User, RoleEnum

DEPARTMENTS = [
    ("Academic Affairs",       "Handles academic queries, results, and curriculum issues."),
    ("Finance & Accounts",     "Manages student fees, bursaries, and financial records."),
    ("Facilities Management",  "Responsible for campus buildings, maintenance, and safety."),
    ("Information Technology", "Manages campus IT infrastructure, Wi-Fi, and software support."),
    ("Student Housing",        "Handles on-campus accommodation and residence queries."),
    ("Student Administration", "Registration, records, and general administrative support."),
]

app = create_app()

with app.app_context():
    # ── Seed departments ─────────────────────────���────────────────────────────
    added = 0
    for name, desc in DEPARTMENTS:
        if not Department.query.filter_by(Name=name).first():
            db.session.add(Department(Name=name, Description=desc))
            added += 1
    db.session.commit()
    print(f"✅  {added} department(s) seeded.")

    # ── Create a default Admin account (if none exists) ───────────────────────
    if not User.query.filter_by(Role=RoleEnum.Admin).first():
        admin = User(
            FullName = 'System Administrator',
            Email    = 'admin@dut.ac.za',
            Role     = RoleEnum.Admin,
            # Admin has no department
        )
        admin.set_password('Admin@1234')
        db.session.add(admin)
        db.session.commit()
        print("✅  Default admin created  →  admin@dut.ac.za / Admin@1234")
    else:
        print("ℹ️   Admin account already exists — skipped.")

    # ── Print department table ────────────────────────────────────────────────
    print("\n── Departments in DB ──────────────────────────────────────")
    for d in Department.query.order_by(Department.DepartmentId).all():
        print(f"  [{d.DepartmentId}] {d.Name}")