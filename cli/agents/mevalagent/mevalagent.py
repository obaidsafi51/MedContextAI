import asyncio
import json
from typing import Annotated, Dict, Any

from genai_session.session import GenAISession
from genai_session.utils.context import GenAIContext
from openai import AsyncOpenAI  # You can swap this with your preferred LLM client

# JWT token from GenAI AgentOS
AGENT_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMmM0YWI4Ny1lZGZhLTRjZTktOWE1Yi1mNTZhYzEyNTY1YjUiLCJleHAiOjI1MzQwMjMwMDc5OSwidXNlcl9pZCI6IjAzNTMyYmJkLWMzNGItNDhjMC05NDA0LWFjZWQ2MzU0ZjI5OSJ9.qKps2k_gzF_VtB_qgHm1Dt_oQsLWi8XOHzuC_ld0QUI" # noqa: E501
session = GenAISession(jwt_token=AGENT_JWT)

# Initialize OpenAI client or your LLM
llm = AsyncOpenAI()  # Defaults to using OPENAI_API_KEY from env


@session.bind(
    name="mevalagent",
    description="MediGuard: Medical Evaluation Agent that analyzes structured health summaries and raises concerns, risks, and recommendations."
)
async def mevalagent(
    agent_context: GenAIContext,
    input_data: Annotated[
        Dict[str, Any],
        "Health summary from EAS Agent with extracted data, alerts, and summary text."
    ],
):
    try:
        user_id = input_data.get("user_id", "")
        raw_text = input_data.get("raw_text", "")
        summary = input_data.get("summary", "")
        alerts = input_data.get("alerts", [])
        extracted = input_data.get("extracted", {})

        prompt = f"""
You are a medical assistant. Analyze the following health summary and extracted data:

Summary:
{summary}

Raw Text:
{raw_text}

Extracted Data:
{json.dumps(extracted, indent=2)}

Alerts:
{alerts}

Please provide:
- Key medical concerns (if any)
- Risk assessment based on content
- Personalized recommendations
- Relevance of the extracted data

Respond in JSON format with keys: concerns, risk_assessment, recommendations, relevance_analysis
"""

        # Send prompt to LLM
        response = await llm.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4
        )
        result = json.loads(response.choices[0].message.content.strip())

        # Compute simple confidence score
        score = 1.0 if len(result.get("recommendations", [])) > 0 else 0.5

        # Send to DEC agent
        await agent_context.send(
            recipient_id="dec_agent",
            payload={
                "evaluation_result": result,
                "confidence_score": score,
                "user_query": summary,
                "user_id": user_id,
                "drug_interactions": [],  # Optional: add interaction detection logic
                "summary": summary,
            },
            type="evaluation_result"
        )

        return {
            "status": "success",
            "message": "Evaluation complete and forwarded to DEC agent",
            "confidence_score": score
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

async def main():
    print(f"MEVAL Agent with token '{AGENT_JWT}' started.")
    await session.process_events()
if __name__ == "__main__":
    asyncio.run(main())
