"""
One-time setup script: creates the LiveKit SIP trunk + dispatch rule
so inbound Vobiz calls get routed to the NOVA voice agent.

Usage:
    python voice_agent/setup_livekit.py

Requires these env vars (or in .env):
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
    VOBIZ_SIP_DOMAIN, VOBIZ_SIP_USERNAME, VOBIZ_SIP_PASSWORD
    VOBIZ_PHONE_NUMBER
"""

import os
import asyncio
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from livekit import api as livekit_api


async def main():
    lk = livekit_api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    phone = os.environ.get("VOBIZ_PHONE_NUMBER", "+911171366938")
    sip_domain = os.environ.get("VOBIZ_SIP_DOMAIN", "a32d2301.sip.vobiz.ai")
    sip_user = os.environ.get("VOBIZ_SIP_USERNAME", "nova_agent")
    sip_pass = os.environ.get("VOBIZ_SIP_PASSWORD")

    print("=== Creating LiveKit Inbound SIP Trunk ===")
    inbound_trunk = await lk.sip.create_sip_inbound_trunk(
        livekit_api.CreateSIPInboundTrunkRequest(
            trunk=livekit_api.SIPInboundTrunkInfo(
                name="Vobiz NOVA Inbound",
                numbers=[phone],
                allowed_addresses=["0.0.0.0/0"],  # Restrict in production
            )
        )
    )
    print(f"  Inbound trunk ID: {inbound_trunk.sip_trunk_id}")

    print("\n=== Creating LiveKit Outbound SIP Trunk ===")
    outbound_trunk = await lk.sip.create_sip_outbound_trunk(
        livekit_api.CreateSIPOutboundTrunkRequest(
            trunk=livekit_api.SIPOutboundTrunkInfo(
                name="Vobiz NOVA Outbound",
                address=sip_domain,
                auth_username=sip_user,
                auth_password=sip_pass,
                numbers=[phone],
            )
        )
    )
    print(f"  Outbound trunk ID: {outbound_trunk.sip_trunk_id}")

    print("\n=== Creating Dispatch Rule ===")
    dispatch = await lk.sip.create_sip_dispatch_rule(
        livekit_api.CreateSIPDispatchRuleRequest(
            rule=livekit_api.SIPDispatchRule(
                dispatch_rule_individual=livekit_api.SIPDispatchRuleIndividual(
                    room_prefix="call-",
                ),
            ),
            trunk_ids=[inbound_trunk.sip_trunk_id],
            name="NOVA Voice Agent",
        )
    )
    print(f"  Dispatch rule ID: {dispatch.sip_dispatch_rule_id}")

    # Print the LiveKit SIP URI to configure in Vobiz
    livekit_url = os.environ["LIVEKIT_URL"]
    sip_uri = livekit_url.replace("wss://", "").replace("ws://", "")
    print(f"\n=== IMPORTANT: Set this as Vobiz inbound destination ===")
    print(f"  LiveKit SIP URI: {sip_uri}")
    print(f"  Vobiz trunk ID: a32d2301-5338-4e90-9abc-45c7375ad5ca")
    print(f"  Run this to configure Vobiz:")
    print(f'  curl -X PATCH "https://api.vobiz.ai/api/v1/account/MA_38OTWKMJ/trunks/a32d2301-5338-4e90-9abc-45c7375ad5ca"')
    print(f'    -H "X-Auth-ID: MA_38OTWKMJ" -H "X-Auth-Token: ..." ')
    print(f'    -d \'{{"inbound_destination": "{sip_uri}"}}\'')

    print("\n=== Done! Now run the voice agent: ===")
    print("  python voice_agent/agent.py dev")


if __name__ == "__main__":
    asyncio.run(main())
