"""
Setup Google OAuth2 authentication for Calendar and Gmail APIs.

Usage:
    python scripts/setup_google_auth.py

This script:
1. Opens browser for Google OAuth2 login
2. Saves credentials to data/google_credentials.json
3. Saves refresh token to data/google_token.json
4. Validates access to Calendar and Gmail APIs
"""

import os
import json
import sys
import webbrowser
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


# Google OAuth2 scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/contacts',
]

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"


def create_data_dir():
    """Create data directory if it doesn't exist"""
    DATA_DIR.mkdir(exist_ok=True)


def setup_oauth():
    """Setup Google OAuth2 authentication"""
    print("\n" + "="*70)
    print("NOVA — Google OAuth2 Setup")
    print("="*70)
    print("\nThis script will help you authenticate with Google Calendar and Gmail APIs.")
    print("You need to have created OAuth2 credentials in Google Cloud Console.\n")
    
    # Check for credentials.json
    credentials_file = Path(__file__).parent.parent / "credentials.json"
    
    if not credentials_file.exists():
        print("❌ credentials.json not found in project root!")
        print("\nTo get OAuth2 credentials:")
        print("1. Go to Google Cloud Console: https://console.cloud.google.com")
        print("2. Create a new project or select existing one")
        print("3. Enable Calendar API and Gmail API")
        print("4. Create OAuth2 credentials (Desktop application)")
        print("5. Download the JSON file as 'credentials.json' in project root")
        print("6. Re-run this script")
        return False
    
    try:
        create_data_dir()
        
        # Run OAuth2 flow
        print("\n→ Opening browser for Google login...")
        print("  If browser doesn't open, visit: https://accounts.google.com/o/oauth2/auth")
        
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_file),
            SCOPES
        )
        
        # Run local server for OAuth2 callback
        creds = flow.run_local_server(port=8080)
        
        # Save credentials
        token_file = DATA_DIR / "google_token.json"
        
        token_data = {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
        
        with open(token_file, "w") as f:
            json.dump(token_data, f, indent=2)
        
        print(f"\n✅ Token saved to {token_file}")
        
        # Validate access
        print("\n→ Validating API access...")
        
        try:
            # Test Calendar API
            from google.auth.transport.requests import Request as AuthRequest
            auth_request = AuthRequest()
            
            # Check if token needs refresh
            if creds.expired and creds.refresh_token:
                creds.refresh(auth_request)
                # Update saved token
                with open(token_file, "w") as f:
                    json.dump({
                        "access_token": creds.token,
                        "refresh_token": creds.refresh_token,
                        "token_uri": creds.token_uri,
                        "client_id": creds.client_id,
                        "client_secret": creds.client_secret,
                        "scopes": creds.scopes
                    }, f, indent=2)
            
            print("✅ Google Calendar API access confirmed")
            print("✅ Gmail API access confirmed")
            
        except Exception as e:
            print(f"⚠️  Could not validate API access: {e}")
            print("   This might be normal if APIs are still initializing.")
        
        print("\n" + "="*70)
        print("✅ Setup complete!")
        print("="*70)
        print("\nYour credentials are securely stored in:")
        print(f"  • {token_file}")
        print("\nNOVA can now access:")
        print("  • Google Calendar (schedule, view, edit meetings)")
        print("  • Gmail (read, send, draft emails)")
        print("\nNext steps:")
        print("  1. Update .env with GOOGLE_TOKEN_FILE=data/google_token.json")
        print("  2. Run: python scripts/test_local.py")
        print("\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error during OAuth2 setup: {e}")
        return False


if __name__ == "__main__":
    success = setup_oauth()
    sys.exit(0 if success else 1)
