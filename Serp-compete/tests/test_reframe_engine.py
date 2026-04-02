import pytest
from unittest.mock import MagicMock, patch
from src.reframe_engine import ReframeEngine

def test_reframe_engine_missing_key():
    with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
        engine = ReframeEngine()
        result = engine.generate_bowen_reframe("anxiety", "example.com", 10)
        assert "OPENAI_API_KEY missing" in result['reframe']

def test_clinical_pivot():
    engine = ReframeEngine()
    
    assert engine.clinical_pivot("anxiety") == "Anxiety: Intercepting the Relationship Loop"
    assert engine.clinical_pivot("avoidant attachment") == "Emotional Distance / Pursuer-Distancer"
    assert engine.clinical_pivot("anxious attachment") == "Emotional Fusion / Pursuit"
    assert engine.clinical_pivot("boundaries") == "Differentiation of Self"
    assert engine.clinical_pivot("toxic person") == "Functional Position in the System"
    assert engine.clinical_pivot("trauma") == "Multigenerational Emotional Process"
    assert engine.clinical_pivot("anger management") == "Anger as a Systemic Reactive Process"
    assert engine.clinical_pivot("introvert signs") == "Introversion as a Function of Systemic Anxiety"
    assert engine.clinical_pivot("adhd symptoms") == "ADHD as a Systemic Functioning Variation"
    assert engine.clinical_pivot("gottman method") == "Beyond Gottman: A Systemic Differentiation Approach"

@patch('src.reframe_engine.OpenAI')
def test_spec_3_prompt_injection(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Systemic Reframe Content"))]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    mock_client.chat.completions.create.return_value = mock_response
    
    with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
        engine = ReframeEngine()
        # Test keyword that triggers remapping
        engine.generate_bowen_reframe("avoidant attachment", "example.com", 10, paa_questions=["Am I avoidant?"])
        
        call_args = mock_client.chat.completions.create.call_args
        prompt = call_args.kwargs['messages'][0]['content']
        
        assert "You are strictly forbidden from using diagnostic labels" in prompt
        assert "Emotional Distance / Pursuer-Distancer" in prompt
        assert "Anxiety Loop Evidence" in prompt
        assert "Am I avoidant?" in prompt
