"""
Antigravity spike — prove managed agent round-trip works.
Run: source .venv/bin/activate && GEMINI_API_KEY=... python agent/spike.py
"""
import os
import json
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

contract = {
    "deal": "Acme Corp",
    "product": "Enterprise Platform",
    "seats": 1000,
    "tcv_usd": 450000,
    "annual_schedule_usd": [100000, 150000, 200000],
    "discount_pct": 10,
    "y1_monthly_invoice_usd": 8333.33,
    "term_years": 3,
}

crm = {
    "deal": "Acme Corp",
    "product": "Enterprise Platform",
    "seats": 1000,
    "tcv_usd": 450000,
    "annual_schedule_usd": [150000, 150000, 150000],
    "discount_pct": 10,
    "y1_monthly_invoice_usd": 8333.00,
    "term_years": 3,
}

agents_md = """\
You are a RevOps Finance Agent. Your job is to reconcile signed contracts against CRM records.

When given a contract and a CRM record:
1. Compare the total contract value (TCV)
2. Report any differences you find
3. Recommend who should review each difference

Keep your analysis brief and structured.
"""

# --- Test 1: Antigravity Managed Agent ---
print("=" * 60)
print("TEST 1: Antigravity Managed Agent (Interactions API)")
print("=" * 60)

try:
    interaction = client.interactions.create(
        agent="antigravity-preview-05-2026",
        input=(
            "Compare the signed contract against the CRM record. "
            "List every field, whether it matches or not. "
            "Flag any discrepancies.\n\n"
            f"SIGNED CONTRACT:\n{json.dumps(contract, indent=2)}\n\n"
            f"CRM RECORD:\n{json.dumps(crm, indent=2)}"
        ),
        environment={
            "type": "remote",
            "sources": [
                {
                    "type": "inline",
                    "target": ".agents/AGENTS.md",
                    "content": agents_md,
                },
            ],
        },
    )

    print(f"Interaction ID: {interaction.id}")
    print(f"Environment ID: {interaction.environment_id}")
    print(f"\nAgent output:\n{interaction.output_text[:800]}")

    # Test session continuity
    print("\n--- TESTING SESSION CONTINUITY ---")
    interaction_2 = client.interactions.create(
        agent="antigravity-preview-05-2026",
        previous_interaction_id=interaction.id,
        environment=interaction.environment_id,
        input="Which discrepancy is material and which is immaterial? Explain why.",
    )

    print(f"Continuity preserved: {interaction_2.environment_id == interaction.environment_id}")
    print(f"Output:\n{interaction_2.output_text[:500]}")

    print("\n✓ ANTIGRAVITY WORKS — use as primary runtime")

except Exception as e:
    print(f"✗ Antigravity failed: {e}")
    print("\nFalling back to regular Gemini generate_content...")

    # --- Test 2: Fallback - regular Gemini ---
    print("\n" + "=" * 60)
    print("TEST 2: Fallback — gemini-2.5-flash generate_content")
    print("=" * 60)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            "Compare the signed contract against the CRM record. "
            "List every field, whether it matches or not. "
            "Flag any discrepancies.\n\n"
            f"SIGNED CONTRACT:\n{json.dumps(contract, indent=2)}\n\n"
            f"CRM RECORD:\n{json.dumps(crm, indent=2)}"
        ),
    )
    print(f"Output:\n{response.text[:800]}")
    print("\n✓ FALLBACK WORKS — use generate_content as primary runtime")
