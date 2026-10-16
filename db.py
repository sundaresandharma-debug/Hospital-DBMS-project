import os
import sqlite3
from werkzeug.security import generate_password_hash

# Vercel serverless environments require writable files to reside in /tmp
if os.environ.get("VERCEL"):
    DATABASE = "/tmp/hnm_hospital.db"
else:
    DATABASE = os.path.join(os.path.abspath(os.path.dirname(__file__)), "hnm_hospital.db")


def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after the original schema shipped. CREATE TABLE IF NOT EXISTS
# does not alter existing tables, so these are applied with ALTER TABLE.
MIGRATION_COLUMNS = {
    "USER_DATA": [
        ("TERMS_ACCEPTED_AT", "TIMESTAMP"),
        ("POLICY_VERSION", "TEXT"),
        ("HEALTH_DATA_CONSENT_AT", "TIMESTAMP"),
        ("MARKETING_OPT_IN", "INTEGER DEFAULT 0"),
        ("IS_MINOR", "INTEGER DEFAULT 0"),
        ("GUARDIAN_NAME", "TEXT"),
        ("GUARDIAN_CONSENT_AT", "TIMESTAMP"),
    ],
    "PATIENTS": [
        ("GUARDIAN_NAME", "TEXT"),
    ],
}


def apply_migrations(conn):
    cursor = conn.cursor()
    for table, columns in MIGRATION_COLUMNS.items():
        existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns:
            if column not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Employees (10 Specialist Doctors)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS EMPLOYEES (
            EID TEXT PRIMARY KEY,
            NAME TEXT NOT NULL,
            DEPARTMENT TEXT NOT NULL,
            AGE INTEGER,
            GENDER TEXT,
            SALARY REAL,
            MOBILE_NO TEXT
        )
    """
    )

    # 2. Patients (20 Clinical Records + Extended Health Data)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS PATIENTS (
            PID TEXT PRIMARY KEY,
            NAME TEXT NOT NULL,
            ISSUE TEXT,
            AGE INTEGER,
            GENDER TEXT,
            FEES REAL DEFAULT 0,
            MOBILE_NO TEXT,
            BILL_NO TEXT UNIQUE,
            USERNAME TEXT,
            BLOOD_GROUP TEXT DEFAULT 'Unknown',
            ALLERGIES TEXT DEFAULT 'None reported',
            MEDICAL_HISTORY TEXT DEFAULT 'No prior chronic conditions'
        )
    """
    )

    # 3. Hospital Ward Beds Layout (Exact 70 Beds Matrix)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS BEDS (
            BED_ID TEXT PRIMARY KEY,
            WARD_TYPE TEXT NOT NULL,
            BED_NUMBER TEXT NOT NULL,
            STATUS TEXT DEFAULT 'Available' CHECK (STATUS IN ('Available', 'Occupied', 'Maintenance')),
            PATIENT_ID TEXT,
            ASSIGNED_DATE TEXT,
            FOREIGN KEY (PATIENT_ID) REFERENCES PATIENTS(PID) ON DELETE SET NULL
        )
    """
    )

    # 4. Emergency Medical Transport (Ambulance Fleet)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS EMT (
            VNO TEXT PRIMARY KEY,
            VTYPE TEXT NOT NULL,
            DRIVER_NAME TEXT NOT NULL,
            MOBILE_NO TEXT NOT NULL
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS EMT_STATUS (
            VNO TEXT PRIMARY KEY,
            STATUS TEXT DEFAULT 'Available' CHECK (STATUS IN ('Available', 'Dispatched', 'Maintenance')),
            FOREIGN KEY (VNO) REFERENCES EMT(VNO) ON DELETE CASCADE
        )
    """
    )

    # 5. Pharmacy Inventory
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS PHARMACY (
            MEDICINE_NAME TEXT PRIMARY KEY,
            MEDICINE_TYPE TEXT NOT NULL,
            STOCK INTEGER NOT NULL CHECK (STOCK >= 0),
            PRICE REAL NOT NULL CHECK (PRICE >= 0)
        )
    """
    )

    # 6. Patient Medicine Purchase History
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS MEDICINE_PURCHASES (
            PURCHASE_ID TEXT PRIMARY KEY,
            PATIENT_ID TEXT NOT NULL,
            PATIENT_NAME TEXT NOT NULL,
            MEDICINE_NAME TEXT NOT NULL,
            QUANTITY INTEGER NOT NULL CHECK (QUANTITY > 0),
            TOTAL_PRICE REAL NOT NULL,
            PURCHASE_DATE TEXT NOT NULL,
            USERNAME TEXT
        )
    """
    )

    # 7. User Authentication & Role Access
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS USER_DATA (
            USERNAME TEXT PRIMARY KEY,
            PASSWORD TEXT NOT NULL,
            ROLE TEXT NOT NULL DEFAULT 'patient' CHECK (ROLE IN ('staff', 'patient')),
            NAME TEXT,
            MOBILE_NO TEXT,
            CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # 8. Consultations
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS CONSULTATION (
            CONSULTATION_ID TEXT PRIMARY KEY,
            PATIENT_ID TEXT NOT NULL,
            EMP_ID TEXT NOT NULL,
            REASON TEXT,
            FEES REAL DEFAULT 0,
            TIME TEXT,
            STATUS TEXT DEFAULT 'Scheduled' CHECK (STATUS IN ('Scheduled', 'Completed', 'Cancelled')),
            FOREIGN KEY (PATIENT_ID) REFERENCES PATIENTS(PID) ON DELETE RESTRICT,
            FOREIGN KEY (EMP_ID) REFERENCES EMPLOYEES(EID) ON DELETE RESTRICT
        )
    """
    )

    # 9. Digital Prescriptions
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS PRESCRIPTION (
            PRESCRIPTION_ID TEXT PRIMARY KEY,
            CONSULTATION_ID TEXT NOT NULL UNIQUE,
            DATE TEXT NOT NULL,
            DIAGNOSIS TEXT,
            INSTRUCTIONS TEXT,
            FOREIGN KEY (CONSULTATION_ID) REFERENCES CONSULTATION(CONSULTATION_ID) ON DELETE RESTRICT
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS PRESCRIBED_MEDICINE (
            PM_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            PRESCRIPTION_ID TEXT NOT NULL,
            MEDICINE_NAME TEXT NOT NULL,
            DOSAGE TEXT NOT NULL,
            FREQUENCY TEXT NOT NULL,
            DURATION TEXT NOT NULL,
            FOREIGN KEY (PRESCRIPTION_ID) REFERENCES PRESCRIPTION(PRESCRIPTION_ID) ON DELETE CASCADE,
            FOREIGN KEY (MEDICINE_NAME) REFERENCES PHARMACY(MEDICINE_NAME) ON DELETE RESTRICT
        )
    """
    )

    # 10. Admin Notification Feed
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS NOTIFICATIONS (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TYPE TEXT NOT NULL,
            MESSAGE TEXT NOT NULL,
            CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            IS_READ INTEGER DEFAULT 0
        )
    """
    )

    # 11. Privacy / data subject requests (account & data deletion)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS DATA_REQUESTS (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            USERNAME TEXT NOT NULL,
            REQUEST_TYPE TEXT NOT NULL DEFAULT 'deletion' CHECK (REQUEST_TYPE IN ('deletion')),
            STATUS TEXT NOT NULL DEFAULT 'Pending' CHECK (STATUS IN ('Pending', 'Completed', 'Rejected')),
            REASON TEXT,
            RESOLUTION_NOTE TEXT,
            CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            RESOLVED_AT TIMESTAMP,
            RESOLVED_BY TEXT
        )
    """
    )

    conn.commit()
    apply_migrations(conn)
    seed_data(conn)
    conn.close()


def seed_data(conn):
    cursor = conn.cursor()

    # Seed Default User Accounts
    cursor.execute("SELECT COUNT(*) FROM USER_DATA")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO USER_DATA (USERNAME, PASSWORD, ROLE, NAME, MOBILE_NO) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "admin",
                    generate_password_hash("admin123"),
                    "staff",
                    "Dr. Eleanor Vance (Chief Medical Officer)",
                    "9876543210",
                ),
                (
                    "doctor_raj",
                    generate_password_hash("doctor123"),
                    "staff",
                    "Dr. Rajesh Sharma",
                    "9876543211",
                ),
                (
                    "patient_john",
                    generate_password_hash("patient123"),
                    "patient",
                    "Johnathan Doe",
                    "9123456780",
                ),
            ],
        )

    # 1. Seed 10 Doctors
    cursor.execute("SELECT COUNT(*) FROM EMPLOYEES")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO EMPLOYEES (EID, NAME, DEPARTMENT, AGE, GENDER, SALARY, MOBILE_NO) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("EMP001", "Dr. Rajesh Sharma", "Cardiology", 46, "Male", 195000, "9876543211"),
                ("EMP002", "Dr. Priya Patel", "Pediatrics", 38, "Female", 165000, "9876543212"),
                ("EMP003", "Dr. Michael Chen", "Orthopedics", 50, "Male", 210000, "9876543213"),
                ("EMP004", "Dr. Anita Desai", "Neurology", 43, "Female", 185000, "9876543214"),
                ("EMP005", "Dr. Vikram Sethi", "Oncology", 54, "Male", 230000, "9876543215"),
                ("EMP006", "Dr. Meera Nambiar", "Dermatology", 36, "Female", 150000, "9876543216"),
                ("EMP007", "Dr. Arjun Kapoor", "General Surgery", 49, "Male", 220000, "9876543217"),
                ("EMP008", "Dr. Sunita Rao", "ENT Specialist", 41, "Female", 155000, "9876543218"),
                ("EMP009", "Dr. David Miller", "Radiology", 45, "Male", 175000, "9876543219"),
                ("EMP010", "Dr. Kavita Nair", "Emergency Medicine", 39, "Female", 180000, "9876543220"),
            ],
        )

    # 2. Seed 20 Patients with Clinical Health Records
    cursor.execute("SELECT COUNT(*) FROM PATIENTS")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            """INSERT INTO PATIENTS (
                PID, NAME, ISSUE, AGE, GENDER, FEES, MOBILE_NO, BILL_NO, USERNAME,
                BLOOD_GROUP, ALLERGIES, MEDICAL_HISTORY
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("PAT001", "Johnathan Doe", "Chest tightness & Hypertension", 52, "Male", 1500, "9123456780", "BILL-1001", "patient_john", "O+", "Penicillin", "Hypertension (5 yrs), Mild Arrhythmia"),
                ("PAT002", "Emily Watson", "Severe Migraine & Nausea", 34, "Female", 900, "9123456781", "BILL-1002", None, "A+", "Sulfa drugs", "Chronic episodic migraine"),
                ("PAT003", "Aarav Kumar", "Viral Fever and Bronchitis", 9, "Male", 600, "9123456782", "BILL-1003", None, "B+", "Peanuts", "Childhood asthma"),
                ("PAT004", "Robert Taylor", "Right Knee Ligament Tear", 63, "Male", 1800, "9123456783", "BILL-1004", None, "AB+", "Aspirin", "Osteoarthritis, Knee arthroscopy"),
                ("PAT005", "Sophia Martinez", "Stage II Lymphoma Review", 47, "Female", 2500, "9123456784", "BILL-1005", None, "O-", "None reported", "Lymphoma under chemotherapy"),
                ("PAT006", "Ananya Iyer", "Chronic Eczema Flare-up", 28, "Female", 750, "9123456785", "BILL-1006", None, "A-", "Topical steroids", "Atopic dermatitis"),
                ("PAT007", "Karan Malhotra", "Acute Appendicitis Post-op", 31, "Male", 3200, "9123456786", "BILL-1007", None, "B-", "None reported", "Emergency appendectomy 2026"),
                ("PAT008", "Fatima Sheikh", "Chronic Sinusitis & Vertigo", 42, "Female", 800, "9123456787", "BILL-1008", None, "AB-", "Dust, Pollen", "Benign positional vertigo"),
                ("PAT009", "George Thomas", "Lumbar Spine MRI Follow-up", 58, "Male", 1200, "9123456788", "BILL-1009", None, "O+", "Ibuprofen", "L4-L5 disc herniation"),
                ("PAT010", "Neha Reddy", "Dehydration & Food Poisoning", 24, "Female", 1100, "9123456789", "BILL-1010", None, "B+", "Shellfish", "Acute bacterial gastroenteritis"),
                ("PAT011", "Vikramaditya Bose", "Coronary Angioplasty Recovery", 65, "Male", 4500, "9123456790", "BILL-1011", None, "A+", "Iodine contrast", "Coronary artery disease, Stent placement"),
                ("PAT012", "Chloe Bennett", "Pediatric Asthma Exacerbation", 6, "Female", 700, "9123456791", "BILL-1012", None, "O+", "Dairy", "Bronchial asthma"),
                ("PAT013", "Siddharth Joshi", "Shoulder Dislocation & Sprain", 37, "Male", 1400, "9123456792", "BILL-1013", None, "B+", "Codeine", "Sports injury dislocation"),
                ("PAT014", "Zoya Akhtar", "Epileptic Seizure Assessment", 29, "Female", 2100, "9123456793", "BILL-1014", None, "A-", "None reported", "Focal epilepsy"),
                ("PAT015", "Harpreet Singh", "Chemotherapy Cycle 3 Check", 53, "Male", 3800, "9123456794", "BILL-1015", None, "AB+", "Latex", "Colorectal cancer treatment"),
                ("PAT016", "Divya Pillai", "Psoriasis Plaque Management", 33, "Female", 850, "9123456795", "BILL-1016", None, "O+", "None reported", "Psoriatic arthritis"),
                ("PAT017", "Manish Verma", "Inguinal Hernia Repair Post-op", 49, "Male", 2900, "9123456796", "BILL-1017", None, "A+", "Morphine", "Hernia mesh repair 2026"),
                ("PAT018", "Tanya Grewal", "Tonsillitis & Vocal Strain", 22, "Female", 650, "9123456797", "BILL-1018", None, "B+", "None reported", "Recurrent pharyngitis"),
                ("PAT019", "Lucas Silva", "Cerebral CT Scan Consultation", 41, "Male", 1350, "9123456798", "BILL-1019", None, "O-", "Contrast dye", "Post-concussion syndrome"),
                ("PAT020", "Pooja Hegde", "Multiple Trauma & Fracture", 27, "Female", 5200, "9123456799", "BILL-1020", None, "B+", "None reported", "Motor vehicle accident recovery"),
            ],
        )

    # 3. Seed Exact 70 Beds Matrix
    # ICU: 10, Emergency: 15, General: 30, Deluxe: 15
    cursor.execute("SELECT COUNT(*) FROM BEDS")
    if cursor.fetchone()[0] == 0:
        bed_records = []

        # A) ICU Ward (10 Beds)
        for i in range(1, 11):
            bed_id = f"ICU-{i:02d}"
            bed_num = f"Bed {i:02d}"
            if bed_id == "ICU-01":
                bed_records.append((bed_id, "ICU Ward", bed_num, "Occupied", "PAT001", "2026-10-10"))
            elif bed_id == "ICU-02":
                bed_records.append((bed_id, "ICU Ward", bed_num, "Occupied", "PAT011", "2026-10-11"))
            elif bed_id == "ICU-04":
                bed_records.append((bed_id, "ICU Ward", bed_num, "Occupied", "PAT020", "2026-10-12"))
            elif bed_id == "ICU-10":
                bed_records.append((bed_id, "ICU Ward", bed_num, "Maintenance", None, None))
            else:
                bed_records.append((bed_id, "ICU Ward", bed_num, "Available", None, None))

        # B) Emergency Care (15 Beds)
        for i in range(1, 16):
            bed_id = f"EMG-{i:02d}"
            bed_num = f"Bed {i:02d}"
            if bed_id == "EMG-01":
                bed_records.append((bed_id, "Emergency Care", bed_num, "Occupied", "PAT010", "2026-10-12"))
            elif bed_id == "EMG-03":
                bed_records.append((bed_id, "Emergency Care", bed_num, "Occupied", "PAT007", "2026-10-11"))
            elif bed_id == "EMG-15":
                bed_records.append((bed_id, "Emergency Care", bed_num, "Maintenance", None, None))
            else:
                bed_records.append((bed_id, "Emergency Care", bed_num, "Available", None, None))

        # C) General Ward (30 Beds)
        for i in range(1, 31):
            bed_id = f"GEN-{i:02d}"
            bed_num = f"Bed {i:02d}"
            if bed_id == "GEN-01":
                bed_records.append((bed_id, "General Ward", bed_num, "Occupied", "PAT003", "2026-10-10"))
            elif bed_id == "GEN-03":
                bed_records.append((bed_id, "General Ward", bed_num, "Occupied", "PAT012", "2026-10-11"))
            elif bed_id == "GEN-05":
                bed_records.append((bed_id, "General Ward", bed_num, "Occupied", "PAT017", "2026-10-11"))
            elif bed_id == "GEN-30":
                bed_records.append((bed_id, "General Ward", bed_num, "Maintenance", None, None))
            else:
                bed_records.append((bed_id, "General Ward", bed_num, "Available", None, None))

        # D) Deluxe Suite (15 Beds)
        for i in range(1, 16):
            bed_id = f"DLX-{i:02d}"
            bed_num = f"Suite {100 + i}"
            if bed_id == "DLX-01":
                bed_records.append((bed_id, "Deluxe Suite", bed_num, "Occupied", "PAT004", "2026-10-09"))
            elif bed_id == "DLX-02":
                bed_records.append((bed_id, "Deluxe Suite", bed_num, "Occupied", "PAT015", "2026-10-11"))
            else:
                bed_records.append((bed_id, "Deluxe Suite", bed_num, "Available", None, None))

        cursor.executemany(
            "INSERT INTO BEDS (BED_ID, WARD_TYPE, BED_NUMBER, STATUS, PATIENT_ID, ASSIGNED_DATE) VALUES (?, ?, ?, ?, ?, ?)",
            bed_records,
        )

    # 4. Seed Ambulance Fleet
    cursor.execute("SELECT COUNT(*) FROM EMT")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO EMT (VNO, VTYPE, DRIVER_NAME, MOBILE_NO) VALUES (?, ?, ?, ?)",
            [
                ("KA01AB1234", "Advanced Cardiac Life Support (ALS)", "Ramesh Gowda", "9988776655"),
                ("KA01CD5678", "Basic Trauma Life Support (BLS)", "Suresh Kumar", "9988776656"),
                ("KA02EF9012", "Patient Transport Care Unit", "Anil Patil", "9988776657"),
                ("KA02GH3456", "Neonatal Intensive Care Ambulance", "Vikram Das", "9988776658"),
            ],
        )
        cursor.executemany(
            "INSERT INTO EMT_STATUS (VNO, STATUS) VALUES (?, ?)",
            [
                ("KA01AB1234", "Available"),
                ("KA01CD5678", "Dispatched"),
                ("KA02EF9012", "Available"),
                ("KA02GH3456", "Available"),
            ],
        )

    # 5. Seed Pharmacy Catalog
    cursor.execute("SELECT COUNT(*) FROM PHARMACY")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO PHARMACY (MEDICINE_NAME, MEDICINE_TYPE, STOCK, PRICE) VALUES (?, ?, ?, ?)",
            [
                ("Paracetamol 650mg", "Tablet", 500, 30.0),
                ("Amoxicillin 500mg", "Capsule", 250, 120.0),
                ("Atorvastatin 10mg", "Tablet", 180, 210.0),
                ("Cetirizine 10mg", "Tablet", 400, 45.0),
                ("Salbutamol Inhaler", "Inhaler", 60, 250.0),
                ("Azithromycin 500mg", "Tablet", 140, 160.0),
                ("Pantoprazole 40mg", "Tablet", 320, 85.0),
                ("Metformin 500mg", "Tablet", 450, 60.0),
                ("Diclofenac Gel 30g", "Ointment", 90, 110.0),
                ("Ondansetron 4mg", "Injection", 110, 95.0),
            ],
        )

    # 6. Seed Sample Medicine Purchase History
    cursor.execute("SELECT COUNT(*) FROM MEDICINE_PURCHASES")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO MEDICINE_PURCHASES (PURCHASE_ID, PATIENT_ID, PATIENT_NAME, MEDICINE_NAME, QUANTITY, TOTAL_PRICE, PURCHASE_DATE, USERNAME) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("ORD-1001", "PAT001", "Johnathan Doe", "Paracetamol 650mg", 2, 60.0, "2026-10-10", "patient_john"),
                ("ORD-1002", "PAT001", "Johnathan Doe", "Atorvastatin 10mg", 1, 210.0, "2026-10-11", "patient_john"),
                ("ORD-1003", "PAT003", "Aarav Kumar", "Amoxicillin 500mg", 1, 120.0, "2026-10-11", None),
            ],
        )

    # 7. Seed Consultations & Prescriptions
    cursor.execute("SELECT COUNT(*) FROM CONSULTATION")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO CONSULTATION (CONSULTATION_ID, PATIENT_ID, EMP_ID, REASON, FEES, TIME, STATUS) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("CON-001", "PAT001", "EMP001", "Cardiac ECG & Blood Pressure Check", 1500, "2026-10-10 10:30", "Completed"),
                ("CON-002", "PAT002", "EMP004", "Neurology consultation for chronic migraine", 900, "2026-10-11 11:15", "Completed"),
                ("CON-003", "PAT003", "EMP002", "Pediatric chest auscultation and fever check", 600, "2026-10-12 14:00", "Scheduled"),
                ("CON-004", "PAT004", "EMP003", "Orthopedic knee ligament MRI assessment", 1800, "2026-10-13 15:30", "Scheduled"),
                ("CON-005", "PAT007", "EMP007", "Post-appendectomy wound review", 1200, "2026-10-13 16:45", "Scheduled"),
            ],
        )
        cursor.executemany(
            "INSERT INTO PRESCRIPTION (PRESCRIPTION_ID, CONSULTATION_ID, DATE, DIAGNOSIS, INSTRUCTIONS) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "RX-001",
                    "CON-001",
                    "2026-10-10",
                    "Stage 1 Essential Hypertension & Arrhythmia",
                    "Low sodium Mediterranean diet, 30 min daily brisk walk, monitor BP weekly.",
                ),
                (
                    "RX-002",
                    "CON-002",
                    "2026-10-11",
                    "Chronic Migraine with Visual Aura",
                    "Avoid prolonged screen strain, stay well hydrated, maintain regular sleep hours.",
                ),
            ],
        )
        cursor.executemany(
            "INSERT INTO PRESCRIBED_MEDICINE (PRESCRIPTION_ID, MEDICINE_NAME, DOSAGE, FREQUENCY, DURATION) VALUES (?, ?, ?, ?, ?)",
            [
                ("RX-001", "Atorvastatin 10mg", "1 Tablet", "Once daily after dinner", "30 Days"),
                ("RX-001", "Pantoprazole 40mg", "1 Tablet", "Once daily before breakfast", "15 Days"),
                ("RX-002", "Cetirizine 10mg", "1 Tablet", "Once daily at bedtime", "7 Days"),
                ("RX-002", "Paracetamol 650mg", "1 Tablet", "As needed for acute head pain", "5 Days"),
            ],
        )

    # 8. Seed Initial Notifications
    cursor.execute("SELECT COUNT(*) FROM NOTIFICATIONS")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO NOTIFICATIONS (TYPE, MESSAGE) VALUES (?, ?)",
            [
                ("bed", "Patient Johnathan Doe allocated to Bed ICU-01 (Intensive Care)."),
                ("bed", "Patient Pooja Hegde allocated to Bed ICU-04 (Trauma Care)."),
                ("pharmacy", "System: Ward beds and pharmacy inventory loaded."),
            ],
        )

    conn.commit()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully with Extended Health Data and Purchase History.")
