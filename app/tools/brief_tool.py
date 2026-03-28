"""
Brief Tool — Smart pre-meeting and person/company research briefs.
Combines Perplexity web research + Calendar + Contacts into one sharp brief.
"""

import logging
from app.tools.base import BaseTool, ToolResult
from app.config import settings

logger = logging.getLogger(__name__)


class BriefTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "brief"

    @property
    def description(self) -> str:
        return """Generate a smart pre-meeting or research brief on a person or company.

Use this when Raunk says things like:
- "I'm meeting Amit from XYZ Ventures in 10 mins"
- "Brief me on Sequoia before my call"
- "Who is this person I'm meeting?"
- "What should I know about [company] before the meeting?"

Actions:
- meeting: Full pre-meeting brief — company background, recent news, talking points, questions to ask
- person: Research a specific person (LinkedIn background, company, role)
- company: Deep dive on a company (what they do, funding, news, key people)

Examples:
- "Brief me on my 3pm with Raj from Tiger Global" → meeting(name="Raj", company="Tiger Global")
- "Research Zomato before my call" → company(company="Zomato")
- "Who is Kunal Shah?" → person(name="Kunal Shah")
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["meeting", "person", "company"],
                    "description": "'meeting' for pre-meeting brief, 'person' to research someone, 'company' for company deep dive"
                },
                "name": {
                    "type": "string",
                    "description": "Person's name (for meeting or person action)"
                },
                "company": {
                    "type": "string",
                    "description": "Company name (for meeting or company action)"
                },
                "context": {
                    "type": "string",
                    "description": "Optional extra context — e.g. 'Series A investor', 'potential supplier'"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, name: str = None, company: str = None,
                      context: str = None, **kwargs) -> ToolResult:
        try:
            if action == "meeting":
                return await self._meeting_brief(name, company, context)
            elif action == "person":
                return await self._person_brief(name, context)
            elif action == "company":
                return await self._company_brief(company, context)
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Brief tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _research(self, query: str) -> str:
        """Run a Perplexity search and return the answer text."""
        import httpx
        api_key = getattr(settings, "perplexity_api_key", None)
        if not api_key:
            return "No Perplexity API key configured — web research unavailable."

        payload = {
            "model": "sonar",
            "messages": [
                {"role": "system", "content": "Be concise and factual. Focus on the most relevant business information."},
                {"role": "user", "content": query}
            ],
            "max_tokens": 800,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post("https://api.perplexity.ai/chat/completions",
                                     json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def _get_contact_history(self, name: str) -> str:
        """Check if this person is in contacts and pull any notes."""
        try:
            import app.memory as _db
            from sqlalchemy.sql import select
            from app.memory import Contact
            async with _db.AsyncSessionLocal() as session:
                stmt = select(Contact).where(Contact.name.ilike(f"%{name}%")).limit(1)
                result = await session.execute(stmt)
                contact = result.scalar_one_or_none()
                if contact:
                    return (f"Known contact: {contact.name}"
                            f"{' at ' + contact.company if contact.company else ''}"
                            f"{' — Purpose: ' + contact.purpose if contact.purpose else ''}"
                            f"{' [VIP]' if contact.is_vip else ''}"
                            f". First seen: {contact.first_seen.strftime('%b %Y') if contact.first_seen else 'unknown'}")
        except Exception:
            pass
        return None

    async def _meeting_brief(self, name: str, company: str, context: str) -> ToolResult:
        subject = " ".join(filter(None, [name, f"from {company}" if company else None]))
        if not subject:
            return ToolResult(tool_name=self.name, success=False,
                              error="Provide at least a name or company for the brief")

        # Run research queries
        queries = []
        if company:
            queries.append(f"What does {company} do? Key facts, funding, business model, recent news.")
        if name and company:
            queries.append(f"Who is {name} at {company}? Role, background, LinkedIn profile.")
        elif name:
            queries.append(f"Who is {name}? Professional background, role, company.")

        research_parts = []
        for q in queries:
            try:
                research_parts.append(await self._research(q))
            except Exception:
                pass

        contact_note = await self._get_contact_history(name) if name else None

        brief = {
            "subject": subject,
            "context": context,
            "contact_history": contact_note,
            "research": research_parts,
            "suggested_talking_points": self._talking_points(name, company, context),
        }

        return ToolResult(tool_name=self.name, success=True, data=brief)

    async def _person_brief(self, name: str, context: str) -> ToolResult:
        if not name:
            return ToolResult(tool_name=self.name, success=False, error="name is required")
        query = f"Who is {name}? Professional background, current role, company, notable work."
        if context:
            query += f" Context: {context}"
        research = await self._research(query)
        contact_note = await self._get_contact_history(name)
        return ToolResult(tool_name=self.name, success=True, data={
            "name": name,
            "contact_history": contact_note,
            "research": research,
        })

    async def _company_brief(self, company: str, context: str) -> ToolResult:
        if not company:
            return ToolResult(tool_name=self.name, success=False, error="company is required")
        query = f"{company}: what do they do, business model, funding/valuation, key people, recent news."
        if context:
            query += f" Context: {context}"
        research = await self._research(query)
        return ToolResult(tool_name=self.name, success=True, data={
            "company": company,
            "research": research,
        })

    @staticmethod
    def _talking_points(name: str, company: str, context: str) -> list:
        points = []
        if context and "investor" in (context or "").lower():
            points = [
                "What stage are you investing at right now?",
                "What's your typical cheque size?",
                "What sectors are you most active in currently?",
                "Have you looked at fashion/e-commerce recently?",
            ]
        elif context and ("client" in (context or "").lower() or "customer" in (context or "").lower()):
            points = [
                "What's the main problem you're trying to solve?",
                "What have you tried before?",
                "What does success look like for you?",
                "Timeline and budget in mind?",
            ]
        else:
            points = [
                f"What brings {name or 'you'} to this conversation?",
                "What are you working on right now?",
                "How can I be most useful to you today?",
            ]
        return points
