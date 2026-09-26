"""
Add test transactions to the database
Usage: python scripts/add-test-transactions-direct.py
"""

from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Database connection
DATABASE_URL = "postgresql://coach:coach@localhost:5432/financial_wellness"
engine = create_engine(DATABASE_URL)

# Test user ID
TEST_USER_ID = "test-user-001"

# Generate 6 months of test data
base_date = date.today() - timedelta(days=150)

transactions_data = []

for month in range(6):
    month_date = base_date + timedelta(days=30 * month)
    month_str = month_date.strftime("%Y-%m")
    
    # Normal dining expenses (gradual increase)
    transactions_data.append({
        "user_id": TEST_USER_ID,
        "description": "Restaurant dinner",
        "category": "dining",
        "amount": 100.0 + (month * 10),
        "occurred_on": month_date + timedelta(days=5),
        "recurring": False,
        "currency": "SGD"
    })
    
    # Add anomaly in month 5 (450 SGD - 3x normal)
    if month == 4:
        transactions_data.append({
            "user_id": TEST_USER_ID,
            "description": "Fancy restaurant anniversary",
            "category": "dining",
            "amount": 450.0,
            "occurred_on": month_date + timedelta(days=15),
            "recurring": False,
            "currency": "SGD"
        })
    
    # Grocery shopping (increasing trend)
    transactions_data.append({
        "user_id": TEST_USER_ID,
        "description": "Grocery shopping",
        "category": "food",
        "amount": 150.0 + (month * 15),
        "occurred_on": month_date + timedelta(days=1),
        "recurring": False,
        "currency": "SGD"
    })
    
    # Transport (stable)
    transactions_data.append({
        "user_id": TEST_USER_ID,
        "description": "Bus fare",
        "category": "transport",
        "amount": 50.0 + (month * 2),
        "occurred_on": month_date + timedelta(days=10),
        "recurring": False,
        "currency": "SGD"
    })
    
    # Entertainment (weekend pattern)
    if month % 2 == 0:
        transactions_data.append({
            "user_id": TEST_USER_ID,
            "description": "Movie tickets",
            "category": "entertainment",
            "amount": 30.0,
            "occurred_on": month_date + timedelta(days=15),
            "recurring": False,
            "currency": "SGD"
        })
    
    # Utilities (recurring, increasing)
    transactions_data.append({
        "user_id": TEST_USER_ID,
        "description": "Electric bill",
        "category": "utilities",
        "amount": 120.0 + (month * 5),
        "occurred_on": month_date + timedelta(days=20),
        "recurring": True,
        "currency": "SGD"
    })

print(f"Generated {len(transactions_data)} transactions for user {TEST_USER_ID}")
print(f"Date range: {base_date} to {date.today()}")
print(f"Anomaly included: 450 SGD dining expense in month 5")
print("")

# Insert into database
try:
    from app.infrastructure.database import Base
    from app.infrastructure.repositories import SQLAlchemyTransactionRecord
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    with Session(engine) as session:
        for txn_data in transactions_data:
            record = SQLAlchemyTransactionRecord(**txn_data)
            session.add(record)
        
        session.commit()
        print(f"✓ Successfully added {len(transactions_data)} transactions")
        print(f"✓ User ID: {TEST_USER_ID}")
        print("")
        print("Next steps:")
        print("1. Go to Overview dashboard")
        print("2. You should see spending insights, anomalies, and patterns")
        print("3. Ask the Coach: 'Review my spending patterns'")
        
except Exception as e:
    print(f"✗ Error: {e}")
    print("Make sure the database is running and accessible")
