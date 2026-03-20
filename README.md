

## 🚀 Getting Started

### Prerequisites

- Python 3.12 or higher
- `pip` and `venv`
- Git

### 1. Clone the repository
download zip file or clone the repo inside your windows cmd window
```bash
git clone https://github.com/aviapollyon/ComplaintOrgGrp24.git
cd ComplaintOrgGrp24
```

### 2. Create and activate a virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Initialise the database

```bash
del instance\grievance.db
del migrations\versions\*.py
flask db init        # only needed on first clone if migrations/ folder is absent
flask db migrate -m "Initial schema"
flask db upgrade
```
```bash
pip install -r requirements.txt #run this again just in case
```
### 5. Seed departments and default admin

```bash
python seed_test_data.py
```

Role: Admin

System Admin | aviapollyonc@gmail.com | Admin@1234

Role: Staff

Sipho Nkosi | aviapollyon@gmail.com | Staff@1234 | Academic Affairs
Priya Pillay | priya.pillay@dut.ac.za | Staff@1234 | Academic Affairs
James Mokoena | james.mokoena@dut.ac.za | Staff@1234 | Finance & Accounts
Fatima Dlamini | fatima.dlamini@dut.ac.za | Staff@1234 | Finance & Accounts
Rajan Govender | rajan.govender@dut.ac.za | Staff@1234 | Facilities Management
Nomsa Zulu | nomsa.zulu@dut.ac.za | Staff@1234 | Information Technology
Thabo Sithole | thabo.sithole@dut.ac.za | Staff@1234 | Information Technology
Linda Maharaj | linda.maharaj@dut.ac.za | Staff@1234 | Student Housing
Mandla Khumalo | mandla.khumalo@dut.ac.za | Staff@1234 | Student Administration

Role: Student

Ayanda Mthembu | 22218367@dut4life.ac.za | Student@1234
Keegan Peters | keegan.example@dut4life.ac.za | Student@1234
Zanele Ntuli | zanele.example@dut4life.ac.za | Student@1234
Rishi Naidoo | rishi.example@dut4life.ac.za | Student@1234
Chloe van Wyk | chloe.example@dut4life.ac.za | Student@1234
Lethiwe Cele | lethiwe.example@dut4life.ac.za | Student@1234
Mohammed Cassim | mohammed.example@dut4life.ac.za | Student@1234
Tayla Botha | tayla.example@dut4life.ac.za | Student@1234
2. All dependencies are installed (`pip install -r requirements.txt`).
3. The database has been migrated (`flask db upgrade`).
4. Departments have been seeded (`python seed_departments.py`).
5. Your `.env` file exists and contains a valid `SECRET_KEY`.
