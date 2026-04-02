import os
from openai import OpenAI
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

class ReframeEngine:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        # Initialize client with api_key
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.model = "gpt-4o"
        # Spec 3 Mapping Dictionary
        self.pivot_map = {
            "avoidant attachment": "Emotional Distance / Pursuer-Distancer",
            "anxious attachment": "Emotional Fusion / Pursuit",
            "boundaries": "Differentiation of Self",
            "toxic person": "Functional Position in the System",
            "trauma": "Multigenerational Emotional Process",
            "anger": "Anger as a Systemic Reactive Process",
            "infidelity": "Infidelity: Reciprocity in the Relationship System",
            "grief": "Grief as a Family Emotional Process",
            "depression": "Depression: A Systemic Functioning Perspective",
            "anxiety": "Anxiety: Intercepting the Relationship Loop",
            "marriage counselling": "Observing the Marriage as an Emotional System",
            "couples counselling": "Relationship Reciprocity and Differentiation",
            "introvert": "Introversion as a Function of Systemic Anxiety",
            "gottman": "Beyond Gottman: A Systemic Differentiation Approach",
            "sexuality": "Sexuality and the Emotional System",
            "narcissist": "The Narcissism Label vs. Systemic Reciprocity",
            "cbt": "Beyond CBT: Focus on Emotional Process",
            "adhd": "ADHD as a Systemic Functioning Variation",
            "attachment styles": "From Attachment Labels to Pursuit-Distance Cycles",
            "self care": "Self-Care as a Differentiation Strategy"
        }

    def clinical_pivot(self, text: str) -> str:
        """
        Spec 3: Semantic Remapper.
        Scans for 'Anxiety Loop' terms and returns Bowen equivalents.
        """
        text_lower = text.lower()
        for trigger, pivot in self.pivot_map.items():
            if trigger in text_lower:
                return pivot
        return text

    def generate_bowen_reframe(self, keyword: str, competitor_url: str, medical_score: int, paa_questions: List[str] = None) -> Dict[str, Any]:
        """
        Generate a 'Pattern-First' blueprint and return usage stats.
        """
        if not self.client:
            return {"reframe": "OPENAI_API_KEY missing.", "usage": {}}

        # Apply clinical pivot to keyword
        remapped_focus = self.clinical_pivot(keyword)
        
        # Spec 3: Strict Prompt Injection
        instruction_override = (
            "You are a Bowen Family Systems expert. You are strictly forbidden from using diagnostic "
            "labels like 'Attachment Styles' or 'Toxic.' You must instead describe behavior as a "
            "reciprocal process of distance and pursuit to help the client see the system rather than "
            "the individual label. Use Bowen Natural Systems terminology exclusively."
        )

        paa_context = ""
        if paa_questions:
            paa_context = f"\n**Anxiety Loop Evidence (User Questions):**\n- " + "\n- ".join(paa_questions[:5]) + "\n"

        prompt = f"""
{instruction_override}

A competitor page ({competitor_url}) is winning on the keyword '{keyword}' using a "Medical Model" approach (Medical Score: {medical_score}).

Your task is to draft a "Pattern-First" content reframe blueprint (approx 500 words).

### Instructions:
1. **Identify the Anxiety Loop:** How does the medical model reinforce chronic anxiety? Use the following PAA questions to demonstrate the user's 'Label-Seeking' behavior:
{paa_context}
Explain how these questions represent an 'Anxiety Loop' where the user seeks a diagnostic label to lower the intensity of the relationship process.

2. **The Systemic Reframe:** Shift the focus from individual pathology to the relationship system. Focus specifically on: {remapped_focus}.
Example: If the user is asking 'Am I avoidant?' (Anxiety Loop), shift this to 'How is distance being used to regulate anxiety in the relationship?' (Systemic Reframe).

3. **Bowen Concepts:** Apply concepts like Differentiation of Self, Triangles, and the Multigenerational Emotional Process.

4. **Differentiation Strategy:** Why is a Bowen approach more effective for long-term functioning than individual 'tips and tools'?

Format as a professional Strategic Briefing.
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            usage = response.usage
            return {
                "reframe": response.choices[0].message.content,
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens
                }
            }
        except Exception as e:
            print(f"OpenAI API Error: {e}")
            return {"reframe": f"Error generating reframe: {e}", "usage": {}}
