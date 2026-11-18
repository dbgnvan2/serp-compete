import os
from openai import OpenAI
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Default Bowen reframes (fallback if clinical_pivots not in config)
DEFAULT_CLINICAL_PIVOTS = {
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

# C-M-15: what a reframe says when the page carries no medical vocabulary at all.
# The engine is handed a keyword, a URL and a score, never the page text, so with a
# medical score of 0 there is no medical model to reframe — stating that is the
# honest output, and it is what the vacuum gate in database.identify_strategic_openings
# now prevents from arising on the run path in the first place.
def _messages(messages=None):
    """The words, from `briefing_messages.json` (chunk Y17).

    The notes below are rendered into the briefing; the prompt blocks are what
    is sent to the model. Both are editorial — the owner is the person who
    would reword a Bowen instruction — and the file keeps them apart under
    `reframes.prompt`.
    """
    from src.briefing_messages import Messages
    return messages or Messages()




class ReframeEngine:
    def __init__(self, config: Dict[str, Any] = None, messages=None):
        """Initialize ReframeEngine with optional config and messages.

        Args:
            config: Optional dict with clinical_pivots
            messages: the render's already-loaded `Messages` (P25); with none
                the file is read here, ONCE, so a per-reframe call does not
                re-read it.
        """
        if config is None:
            config = {}
        self._words = _messages(messages)

        self.api_key = os.getenv("OPENAI_API_KEY")
        # Initialize client with api_key
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.model = "gpt-4o"
        # Load pivot_map from config or use defaults
        self.pivot_map = config.get("clinical_pivots", DEFAULT_CLINICAL_PIVOTS)
        # `eeat_client_messaging` was read into `self.client_messaging` here and
        # never used by anything. Its words are now `eeat.*` in
        # `briefing_messages.json` and the block is gone from shared_config.json
        # (chunk Y17), so the dead attribute goes with it.

    def _no_prompt(self, key: str) -> Dict[str, Any]:
        """What a missing prompt block returns: no call, no reframe, a reason.

        `generated: False` is the same honest status as "no API key" and "no
        medical vocabulary", so every caller already handles it.
        """
        return {"reframe": self._words.get("reframes.prompt_unavailable",
                                           key=key),
                "usage": {}, "generated": False}

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

        C-M-15: the prompt used to assert that the competitor page "is winning …
        using a 'Medical Model' approach (Medical Score: 0)" whatever the score was,
        which is how run_11 produced 600 words on "Triangles within the Archdiocese
        community" for a page with no medical vocabulary at all. A page with
        medical_score 0 now returns the stated absence instead, and spends no tokens.

        Every generated reframe carries a provenance marker. It is literally true:
        the prompt is built from the keyword, the URL and the score — the competitor's
        page text is never fetched for it.
        """
        if (medical_score or 0) <= 0:
            return {"reframe": self._words.get(
                        "reframes.no_medical_vocabulary"), "usage": {},
                    "generated": False}

        if not self.client:
            return {"reframe": self._words.get("reframes.no_api_key"),
                    "usage": {}, "generated": False}

        # (The prompt blocks are read below and `_no_prompt` is what a missing
        # one returns: the same shape as the two returns above, so a caller
        # that checks `generated` already handles it.)

        # Apply clinical pivot to keyword
        remapped_focus = self.clinical_pivot(keyword)
        
        # Spec 3: Strict Prompt Injection.
        #
        # Read with `prompt()`, not `get()`: `get`'s missing-key policy is to
        # render a visible marker, which is right for a sentence the reader
        # sees and wrong for a prompt. A marker in the prompt would be sent to
        # the model, paid for, and its answer written into the briefing as a
        # reframe — and nothing in the report would say a hedge went missing,
        # because the prompt is not rendered. Worse for
        # `instruction_override`: the body would still render and the model
        # would be asked the full task with the Bowen and
        # anti-diagnostic-label guard replaced by a marker (found by the cold
        # review of chunk Y17).
        instruction_override = self._words.prompt(
            "reframes.prompt.instruction_override")
        if instruction_override is None:
            return self._no_prompt("reframes.prompt.instruction_override")

        paa_context = ""
        if paa_questions:
            paa_context = self._words.prompt(
                "reframes.prompt.paa_context",
                questions="\n- ".join(paa_questions[:5]))
            if paa_context is None:
                return self._no_prompt("reframes.prompt.paa_context")

        prompt = self._words.prompt(
            "reframes.prompt.body",
            instruction_override=instruction_override,
            competitor_url=competitor_url, keyword=keyword,
            medical_score=medical_score, paa_context=paa_context,
            remapped_focus=remapped_focus)
        if prompt is None:
            return self._no_prompt("reframes.prompt.body")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            usage = response.usage
            return {
                "reframe": (f"{response.choices[0].message.content}\n\n"
                            f"{self.provenance_marker()}"),
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens
                },
                "generated": True
            }
        except Exception as e:
            print(self._words.get("reframes.api_error_console", error=e))
            return {"reframe": self._words.get("reframes.api_error", error=e),
                    "usage": {}, "generated": False}

    def provenance_marker(self) -> str:
        """The one-line marker appended to every generated reframe (C-M-15)."""
        return self._words.get("reframes.provenance", model=self.model)
