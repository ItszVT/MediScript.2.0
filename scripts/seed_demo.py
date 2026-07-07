"""
seed_demo.py — create a demo chemist account with clearly-labelled demo
inventory (is_demo=True), so the chemist portal has something to show
immediately. All demo rows can be removed from the Inventory page
("Clear demo inventory") or by re-running with --clear.

Usage:
    python scripts/seed_demo.py            # create demo chemist + inventory
    python scripts/seed_demo.py --clear    # remove demo inventory only
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.security import hash_password           # noqa: E402
from app.models.inventory import InventoryItem        # noqa: E402
from app.models.user import User                       # noqa: E402

DEMO_EMAIL = "demo.chemist@mediscript.app"
DEMO_PASSWORD = "demo1234"

# Real medicine names, DEMO stock numbers (rack/expiry/supplier are illustrative).
DEMO_STOCK = [
    ("Paracetamol", "Calpol", 120, 18.0, "A1", 400, "MedSupply Co"),
    ("Amoxicillin-Clavulanate", "Augmentin", 40, 132.0, "B2", 200, "PharmaDist"),
    ("Pantoprazole", "Pan-D", 8, 96.0, "B3", 30, "PharmaDist"),
    ("Azithromycin", "Azithral", 25, 84.0, "C1", 120, "MedSupply Co"),
    ("Metformin", "Glycomet", 60, 24.0, "C2", 400, "HealthWholesale"),
    ("Cetirizine", "Cetzine", 0, 15.0, "D1", 90, "MedSupply Co"),
    ("Diclofenac", "Voveran", 15, 30.0, "D2", 60, "PharmaDist"),
    ("Telmisartan", "Telma", 45, 72.0, "E1", 150, "HealthWholesale"),
]


def get_or_create_chemist(db):
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if user:
        return user
    user = User(email=DEMO_EMAIL, full_name="Demo Chemist",
                hashed_password=hash_password(DEMO_PASSWORD), role="chemist",
                pharmacy_name="City Care Pharmacy (Demo)")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="remove demo inventory only")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        chemist = get_or_create_chemist(db)

        removed = db.query(InventoryItem).filter(
            InventoryItem.owner_id == chemist.id,
            InventoryItem.is_demo.is_(True)).delete()
        db.commit()
        if args.clear:
            print(f"Removed {removed} demo inventory rows.")
            return

        today = date.today()
        for i, (name, brand, qty, price, rack, reorder, supplier) in enumerate(DEMO_STOCK):
            db.add(InventoryItem(
                owner_id=chemist.id, name=name, brand=brand, quantity=qty, price=price,
                rack_location=rack, reorder_level=reorder, supplier=supplier,
                expiry_date=today + timedelta(days=45 if i % 4 == 2 else 400),
                is_demo=True))
        db.commit()
        print(f"Demo chemist ready:\n  email: {DEMO_EMAIL}\n  password: {DEMO_PASSWORD}")
        print(f"Seeded {len(DEMO_STOCK)} DEMO inventory items (is_demo=True).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
