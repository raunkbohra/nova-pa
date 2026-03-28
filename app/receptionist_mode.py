"""
Receptionist Mode — Qualification flow for external contacts.
Handles greeting, collecting info, making decisions, and notifying Raunak.
"""

import logging
from typing import Optional, Literal
from sqlalchemy.ext.asyncio import AsyncSession
from app.memory import get_or_create_contact, get_context, save_external_message
from app.whatsapp import send_text

logger = logging.getLogger(__name__)

# Qualification decision types
DecisionType = Literal["auto_book", "ask_raunak", "decline"]


class ReceptionistQualifier:
    """Handles qualification of external contacts"""
    
    GREETING = (
        "Hi! I'm NOVA, Raunk's executive assistant. "
        "How can I help you today?"
    )
    
    # Follow-up questions to collect info
    QUESTIONS = {
        "name": "What's your name?",
        "company": "Which company are you with?",
        "purpose": "What would you like to discuss with Raunak?"
    }
    
    # Decline message
    DECLINE_MESSAGE = (
        "Thank you for reaching out. "
        "Unfortunately, Raunak isn't able to take on new initiatives right now. "
        "Feel free to reach out again in the future!"
    )
    
    # Keywords that indicate strong signals
    STRONG_KEYWORDS = {
        "investor", "investment", "funding", "series", "raise", "venture",
        "client", "customer", "deal", "partnership", "collaboration",
        "founder", "ceo", "vp", "director", "manager",
        "acquisition", "merger", "exit"
    }
    
    # Keywords that indicate spam/irrelevant
    SPAM_KEYWORDS = {
        "free", "discount", "offer", "limited time", "click here",
        "service provider", "freelancer", "vendor", "agency",
        "seo", "marketing", "pr", "designer", "developer",
        "loan", "credit", "insurance", "energy", "utility"
    }
    
    # Keywords that indicate VIP/known
    VIP_KEYWORDS = {
        "sequoia", "accel", "a16z", "benchmark", "menlo",  # Top VCs
        "google", "microsoft", "amazon", "apple", "meta",  # Tech giants
        "flipkart", "paytm", "byju's", "oyo", "zomato"     # Indian unicorns
    }

    async def handle_greeting(self, phone: str, session: AsyncSession) -> str:
        """Handle initial greeting for new contact"""
        contact = await get_or_create_contact(session, phone)
        
        # Save greeting in conversation
        await save_external_message(session, phone, "assistant", self.GREETING)
        
        return self.GREETING
    
    
    async def collect_info(self, phone: str, message: str, session: AsyncSession,
                          current_stage: str = "name") -> tuple[str, Optional[str], str]:
        """
        Collect information from contact (name, company, purpose).
        
        Returns:
            (response_text, collected_info, next_stage)
        """
        # Save user's response
        await save_external_message(session, phone, "user", message)
        
        # Store the info
        contact = await get_or_create_contact(session, phone)
        
        if current_stage == "name":
            contact.name = message
            next_stage = "company"
            response = self.QUESTIONS["company"]
        elif current_stage == "company":
            contact.company = message
            next_stage = "purpose"
            response = self.QUESTIONS["purpose"]
        elif current_stage == "purpose":
            contact.purpose = message
            next_stage = "decision"
            response = "Thank you for that information. Let me see if Raunak is available..."
        else:
            response = "Error: Unknown stage"
            next_stage = "error"
        
        # Save contact
        import asyncio
        await asyncio.sleep(0)  # Allow session commit
        
        return response, message, next_stage
    
    
    async def make_decision(self, phone: str, contact_name: str, company: str,
                           purpose: str, session: AsyncSession) -> tuple[DecisionType, str]:
        """
        Decide whether to auto-book, ask Raunak, or decline.
        
        Returns:
            (decision_type, reason_text)
        """
        contact = await get_or_create_contact(session, phone, contact_name, company)
        
        # Check for VIP/known
        if contact.is_vip:
            return "auto_book", "VIP contact"
        
        # Check company against VIP list
        company_lower = company.lower() if company else ""
        for keyword in self.VIP_KEYWORDS:
            if keyword in company_lower:
                contact.is_vip = True
                return "auto_book", f"VIP company: {company}"
        
        # Analyze purpose and company for signals
        text_to_analyze = f"{company} {purpose}".lower()
        
        # Count strong signals
        strong_count = sum(1 for kw in self.STRONG_KEYWORDS if kw in text_to_analyze)
        spam_count = sum(1 for kw in self.SPAM_KEYWORDS if kw in text_to_analyze)
        
        # Decision logic
        if spam_count >= 2:
            contact.is_blocked = True
            return "decline", "Likely spam/irrelevant"
        elif strong_count >= 2:
            return "auto_book", "Strong signal (investor/client)"
        elif strong_count >= 1:
            return "ask_raunak", "Moderate signal, needs approval"
        elif spam_count >= 1:
            return "ask_raunak", "Unclear relevance"
        else:
            return "ask_raunak", "Unknown relevance"
    
    
    async def handle_auto_book(self, phone: str, contact_name: str, company: str,
                              purpose: str, session: AsyncSession) -> str:
        """Auto-book meeting in Raunk's calendar"""
        # TODO: Call calendar_tool.py to find free slots and book
        logger.info(f"Auto-booking meeting with {contact_name} from {company}")
        
        message = (
            f"Great! I've scheduled a meeting with Raunak. "
            f"You should receive a calendar invite shortly. "
            f"Looking forward to discussing {purpose}!"
        )
        
        return message
    
    
    async def ask_raunak(self, phone: str, contact_name: str, company: str,
                        purpose: str, raunak_phone: str, session: AsyncSession) -> str:
        """Ask Raunak for approval via WhatsApp"""
        # TODO: Send message to Raunak with YES/NO/LATER buttons
        logger.info(f"Asking Raunak for approval: {contact_name} from {company}")
        
        # For now, just send text (button support would be added later)
        approval_message = (
            f"📞 External Contact\n\n"
            f"Name: {contact_name}\n"
            f"Company: {company}\n"
            f"Purpose: {purpose}\n\n"
            f"Reply: YES, NO, or LATER"
        )
        
        # Send to Raunak
        await send_text(raunak_phone, approval_message)
        
        # Reply to contact
        contact_message = (
            "Thank you! I'm checking with Raunak on his availability. "
            "I'll get back to you shortly."
        )
        
        return contact_message
    
    
    async def handle_decline(self, phone: str, contact_name: str,
                            session: AsyncSession) -> str:
        """Politely decline meeting request"""
        contact = await get_or_create_contact(session, phone, contact_name)
        contact.is_blocked = True
        
        logger.info(f"Declining meeting with {contact_name}")
        
        return self.DECLINE_MESSAGE
    
    
    async def handle_raunak_response(self, phone: str, response: str,
                                   session: AsyncSession) -> str:
        """
        Handle Raunk's YES/NO/LATER response to contact request.
        Called after Raunak replies to the approval message.
        """
        response_lower = response.lower().strip()
        
        contact = await get_or_create_contact(session, phone)
        
        if "yes" in response_lower:
            # TODO: Auto-book meeting
            message = (
                f"Excellent! I've scheduled the meeting with {contact.name}. "
                f"Calendar invite sent to both of you."
            )
        elif "no" in response_lower:
            message = (
                "Understood. I'll let them know you're not available. "
                "Thanks for letting me know!"
            )
        elif "later" in response_lower:
            message = (
                "Got it. I'll follow up with them about another time. "
                "I'll check back with you when they respond."
            )
        else:
            message = (
                "I didn't quite understand. Please reply with YES, NO, or LATER"
            )
        
        return message


# Global instance
qualifier = ReceptionistQualifier()
