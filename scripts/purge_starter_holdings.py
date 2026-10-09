#!/usr/bin/env python3
"""
scripts/purge_starter_holdings.py

One-time cleanup script for NiftyTrade.
Lists users who have holdings in the database without executed delivery trades backing them.
With the --confirm flag, deletes those unbacked holdings and fires a HOLDINGS_CHANGED
outbox event for each affected user. Real executed trades are NEVER touched.
"""

import sys
import os
import argparse

# Add repo root to sys.path so app imports work
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from app.core.database import SessionLocal
from app.services.holdings_service import find_unbacked_holdings, purge_unbacked_holdings
from app.services.outbox_service import trigger_outbox_worker

def main():
    parser = argparse.ArgumentParser(
        description="List and purge unbacked starter/seeded holdings in NiftyTrade."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete unbacked holdings and fire HOLDINGS_CHANGED events. If omitted, performs a dry run."
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Optional specific user_id to target."
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print("=" * 70)
        print(" NiftyTrade - Starter / Unbacked Holdings Cleanup Tool")
        print("=" * 70)

        unbacked = find_unbacked_holdings(db, user_id=args.user_id)

        if not unbacked:
            print("[OK] No unbacked starter holdings found! All holdings are backed by real trades.")
            return

        print(f"\nFound {len(unbacked)} unbacked holding(s):")
        print(f"{'User Email':<32} {'Client ID':<10} {'Symbol':<12} {'Qty':<6} {'Avg Price'}")
        print("-" * 70)
        for item in unbacked:
            print(f"{item['user_email']:<32} {item['client_id']:<10} {item['symbol']:<12} {item['quantity']:<6} Rs. {item['average_price']:,.2f}")

        if args.confirm:
            print("\n[--confirm specified] Deleting unbacked holdings and firing HOLDINGS_CHANGED events...")
            deleted_count, affected_emails = purge_unbacked_holdings(db, user_id=args.user_id)
            db.commit()
            trigger_outbox_worker()

            print(f"[OK] Successfully deleted {deleted_count} unbacked holding(s) across {len(affected_emails)} user(s):")
            for email in affected_emails:
                print(f"  - HOLDINGS_CHANGED outbox event created for: {email}")
            print("\nReal executed trades were NOT touched.")
        else:
            print("\n[DRY RUN] No changes were made to the database.")
            print("Run with '--confirm' to delete these holdings and notify TradeOne:")
            print("  python scripts/purge_starter_holdings.py --confirm")

    finally:
        db.close()

if __name__ == "__main__":
    main()
