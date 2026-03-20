

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

System Admin | aviapollyonc@gmail.com | Admin@1234<br />

Role: Staff

Sipho Nkosi | aviapollyon@gmail.com | Staff@1234 | Academic Affairs<br />
Priya Pillay | priya.pillay@dut.ac.za | Staff@1234 | Academic Affairs<br />
James Mokoena | james.mokoena@dut.ac.za | Staff@1234 | Finance & Accounts<br />
Fatima Dlamini | fatima.dlamini@dut.ac.za | Staff@1234 | Finance & Accounts<br />
Rajan Govender | rajan.govender@dut.ac.za | Staff@1234 | Facilities Management<br />
Nomsa Zulu | nomsa.zulu@dut.ac.za | Staff@1234 | Information Technology<br />
Thabo Sithole | thabo.sithole@dut.ac.za | Staff@1234 | Information Technology<br />
Linda Maharaj | linda.maharaj@dut.ac.za | Staff@1234 | Student Housing<br />
Mandla Khumalo | mandla.khumalo@dut.ac.za | Staff@1234 | Student Administration<br />

Role: Student

THIS STUDENT DELETED FOR SHOWCASING OF VERIFICATION SYSTEM | Ayanda Mthembu | 22218367@dut4life.ac.za | Student@1234<br />
Keegan Peters | keegan.example@dut4life.ac.za | Student@1234<br />
Zanele Ntuli | zanele.example@dut4life.ac.za | Student@1234<br />
Rishi Naidoo | rishi.example@dut4life.ac.za | Student@1234<br />
Chloe van Wyk | chloe.example@dut4life.ac.za | Student@1234<br />
Lethiwe Cele | lethiwe.example@dut4life.ac.za | Student@1234<br />
Mohammed Cassim | mohammed.example@dut4life.ac.za | Student@1234<br />
Tayla Botha | tayla.example@dut4life.ac.za | Student@1234<br />

