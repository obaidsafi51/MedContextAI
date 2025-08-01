import asyncio
from typing import Annotated
from genai_session.session import GenAISession
from genai_session.utils.context import GenAIContext

AGENT_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyNWNlZDBiNy01MTRkLTQ0OGItYWI4ZC00NTQwNmY2ZGYwMDkiLCJleHAiOjI1MzQwMjMwMDc5OSwidXNlcl9pZCI6IjAzNTMyYmJkLWMzNGItNDhjMC05NDA0LWFjZWQ2MzU0ZjI5OSJ9.jYYCWWrf2r35bLveDyzcE2k5qjpoJS445g9pAG__u7M" # noqa: E501
session = GenAISession(jwt_token=AGENT_JWT)


@session.bind(
    name="decagent",
    description="MediGuard: Makes decisions based on evaluation confidence and guides the user."
)
async def decagent(
    agent_context: GenAIContext,
    meval_output: Annotated[dict, "Output from MEVALAgent"]
):
    try:
        confidence = meval_output["confidence_score"]
        evaluation = meval_output["evaluation"]
        alerts = meval_output.get("alerts", [])

        if confidence >= 0.85:
            recommendation = "✅ High confidence. Share the PDF summary with your doctor."
        elif confidence >= 0.5:
            recommendation = "⚠️ Medium confidence. Please upload more data for better results."
        else:
            recommendation = "❌ Low confidence. Not enough data. Please consult your healthcare provider."

        return {
            "status": "success",
            "message": recommendation,
            "confidence_score": confidence,
            "alerts": alerts,
            "disclaimer": "This tool does not provide medical advice. Always consult a licensed medical professional."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def main():
    print("[DECAgent] Ready.")
    await session.process_events()

if __name__ == "__main__":
    asyncio.run(main())
