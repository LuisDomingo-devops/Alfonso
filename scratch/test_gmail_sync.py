import asyncio
import os
import sys
from pathlib import Path

# Add app to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from app.adapters.gmail_sync import sync_from_gmail

async def main():
    print("Testing gmail sync...")
    print(f"GMAIL_EMAIL: {os.getenv('GMAIL_EMAIL')}")
    print(f"GMAIL_APP_PASSWORD length: {len(os.getenv('GMAIL_APP_PASSWORD', ''))}")
    
    # Run the sync
    inserted = await sync_from_gmail()
    print(f"Sync complete. Inserted: {inserted}")

if __name__ == "__main__":
    asyncio.run(main())
