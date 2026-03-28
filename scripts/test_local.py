"""
Local testing script for NOVA without WhatsApp.
Test Claude responses, database operations, and tools.

Usage:
    python scripts/test_local.py
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import settings
from app.memory import Base, save_message, get_messages, set_context
from app.agent import Agent


async def test_commander_mode():
    """Test Commander Mode agent"""
    print("\n" + "="*70)
    print("Testing Commander Mode")
    print("="*70)

    # Initialize database
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Test session
    async with AsyncSessionLocal() as session:
        # Set up Raunak context
        await set_context(session, "raunak_info", """
        Name: Raunk Bohra
        Role: Founder, Entrepreneur
        Company: [TBD - edit with /set_context]
        Timezone: Asia/Kolkata (IST)
        Availability: Mon-Thu, 10am-6pm IST
        VIPs: [None yet]
        """)

        # Create agent
        agent = Agent()

        # Test message
        test_message = "Hello NOVA, what can you help me with?"
        print(f"\n👤 Raunak: {test_message}")

        # Process
        response = await agent.process_commander_message(test_message, session)
        print(f"\n🤖 NOVA: {response}")

        # Test another message
        test_message_2 = "Save a note: Project Alpha - Series A target ₹5Cr, timeline Q3"
        print(f"\n👤 Raunak: {test_message_2}")

        response_2 = await agent.process_commander_message(test_message_2, session)
        print(f"\n🤖 NOVA: {response_2}")

    await engine.dispose()


async def test_receptionist_mode():
    """Test Receptionist Mode agent"""
    print("\n" + "="*70)
    print("Testing Receptionist Mode")
    print("="*70)

    # Initialize database
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Test session
    async with AsyncSessionLocal() as session:
        agent = Agent()

        # Simulate external contact
        test_phone = "+919876543210"
        test_message = "Hi, I'm Amit Sharma from XYZ Ventures. I'd like to discuss investment opportunities."

        print(f"\n📞 External (+919876543210): {test_message}")

        response = await agent.process_receptionist_message(test_phone, test_message, session)
        print(f"\n🤖 NOVA: {response}")

    await engine.dispose()


async def test_database():
    """Test database operations"""
    print("\n" + "="*70)
    print("Testing Database Operations")
    print("="*70)

    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # Save message
        print("\n✓ Saving message to database...")
        await save_message(session, "user", "Test message")

        # Get messages
        print("✓ Retrieving messages from database...")
        messages = await get_messages(session, limit=10)
        print(f"  Retrieved {len(messages)} messages")

        # Set context
        print("✓ Setting Raunak context...")
        await set_context(session, "test_key", "test_value")

    await engine.dispose()
    print("\n✅ Database operations successful")


async def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("NOVA Local Testing Suite")
    print("="*70)
    print(f"Database: {settings.database_url}")
    print(f"Log Level: {settings.log_level}")

    try:
        # Test 1: Database
        await test_database()

        # Test 2: Commander Mode
        await test_commander_mode()

        # Test 3: Receptionist Mode
        await test_receptionist_mode()

        print("\n" + "="*70)
        print("✅ All tests completed successfully!")
        print("="*70)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
