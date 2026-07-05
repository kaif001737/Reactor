#!/usr/bin/env python
"""
MeasiConnect - Bulk CSV User Import CLI Script
Allows administrators to import student, staff, and admin accounts from a CSV file.

CSV Format:
role,name,email,roll_no,department,semester,password

Usage:
  python import_users.py <path_to_csv_file>
"""

import os
import sys
import csv
from dotenv import load_dotenv

# Add parent directory to path so we can load configurations/db
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db
from models import User

def run_import(csv_path):
    # Load environment variables
    load_dotenv()
    
    # Check if file exists
    if not os.path.exists(csv_path):
        print(f"[ERROR] CSV file not found: {csv_path}")
        sys.exit(1)
        
    print("Connecting to MongoDB Atlas...")
    try:
        db = get_db()
        # Trigger query to test connection
        db.users.count_documents({})
    except Exception as e:
        print(f"[ERROR] Could not connect to MongoDB database: {e}")
        print("Please check that the MONGO_URI in your .env is correct and your IP is whitelisted on MongoDB Atlas.")
        sys.exit(1)
        
    print(f"Opening CSV file: {csv_path}...")
    success = 0
    failed = 0
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        for idx, row in enumerate(reader, 1):
            role = row.get('role', '').strip().lower()
            name = row.get('name', '').strip()
            email = row.get('email', '').strip().lower()
            roll_no = row.get('roll_no', '').strip().upper()
            department = row.get('department', '').strip()
            semester = row.get('semester', '').strip()
            password = row.get('password', '').strip()
            
            if not role or not name:
                print(f"[Line {idx}] Skipped: Role or Name is missing.")
                failed += 1
                continue
                
            if role not in ['student', 'staff', 'admin']:
                print(f"[Line {idx}] Skipped: Invalid role '{role}' for user '{name}'")
                failed += 1
                continue
                
            if not password:
                password = "Password123"
                
            try:
                # Check existance first
                if role == 'student':
                    if not roll_no:
                        print(f"[Line {idx}] Skipped: Roll number missing for student '{name}'")
                        failed += 1
                        continue
                    if db.users.find_one({"roll_no": roll_no}):
                        print(f"[Line {idx}] Skipped: Roll number '{roll_no}' already exists for student '{name}'")
                        failed += 1
                        continue
                else:
                    if not email:
                        print(f"[Line {idx}] Skipped: Email missing for staff/admin '{name}'")
                        failed += 1
                        continue
                    if db.users.find_one({"email": email}):
                        print(f"[Line {idx}] Skipped: Email '{email}' already exists for user '{name}'")
                        failed += 1
                        continue
                
                # Create user
                User.create_user(
                    role=role,
                    name=name,
                    email=email if email else None,
                    roll_no=roll_no if roll_no else None,
                    password=password,
                    department=department if department else None,
                    semester=int(semester) if semester else None
                )
                print(f"[SUCCESS] Imported {role} '{name}'")
                success += 1
                
            except Exception as e:
                print(f"[Line {idx}] Error importing '{name}': {e}")
                failed += 1
                
    print("\n" + "="*40)
    print(f"Import process completed.")
    print(f"Successfully Imported: {success}")
    print(f"Failed / Skipped: {failed}")
    print("="*40)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python import_users.py <path_to_csv_file>")
        sys.exit(1)
        
    csv_file_path = sys.argv[1]
    run_import(csv_file_path)
