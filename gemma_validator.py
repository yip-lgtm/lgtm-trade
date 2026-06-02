"""
LLM Validator - Uses Gemma 4 26B via OpenRouter
===================================================
Validates trading signals with LLM analysis.

Requires: OPENAI_API_KEY environment variable (OpenRouter API key)

Usage:
    export OPENAI_API_KEY=sk-or-v1-...
    from gemma_validator import LLMValidator
    validator = LLMValidator()
    result = validator.analyze(symbol, direction, entry, sl)
"""

import os
from openai import OpenAI

MODEL = 'google/gemma-4-26b-a4b-it:free'

class LLMValidator:
    """
    LLM validator for trading signals using Gemma 4 26B.
    """
    
    def __init__(self, api_key=None):
        if api_key:
            os.environ['OPENAI_API_KEY'] = api_key
        
        self.api_key = os.environ.get('OPENAI_API_KEY', '')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        
        self.client = OpenAI(
            base_url='https://openrouter.ai/api/v1',
            api_key=self.api_key
        )
        
        self.model = MODEL
        print(f"[LLM] Validator initialized ({self.model})")
    
    def analyze(self, symbol, direction, entry, sl, tp1=None, tp2=None):
        """
        Analyze a trading signal with LLM.
        
        Returns:
            dict with keys: 'approve' (bool), 'confidence' (str), 'reasoning' (str)
        """
        if not self.client:
            return {'approve': True, 'confidence': 'unknown', 'reasoning': 'LLM not initialized'}
        
        prompt = f"""You are a professional futures trader.

## Position Details
- Symbol: {symbol}
- Direction: {direction.upper()}
- Entry Price: {entry}
- Stop Loss: {sl}
"""
        if tp1:
            prompt += f"- Take Profit 1: {tp1}\n"
        if tp2:
            prompt += f"- Take Profit 2: {tp2}\n"
        
        prompt += """
## Risk Parameters
- Risk per trade: $200 (kill-switch)
- R:R: 1:3 (TP1) / 1:6 (TP2)

Analyze this trade setup.

Respond with ONLY this format:
APPROVE - [Confidence] - [1 sentence]
or
REJECT - [Confidence] - [1 sentence]"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': 'You are a professional futures trader.'},
                    {'role': 'user', 'content': prompt}
                ],
                max_tokens=100,
                temperature=0.3
            )
            
            content = response.choices[0].message.content.strip()
            print(f"[LLM] {symbol}: {content}")
            
            if content.startswith('APPROVE'):
                approve = True
                parts = content.split(' - ', 2)
                confidence = parts[1] if len(parts) > 1 else 'Medium'
                reasoning = parts[2] if len(parts) > 2 else content
            elif content.startswith('REJECT'):
                approve = False
                parts = content.split(' - ', 2)
                confidence = parts[1] if len(parts) > 1 else 'Medium'
                reasoning = parts[2] if len(parts) > 2 else content
            else:
                approve = True
                confidence = 'Medium'
                reasoning = content
            
            return {
                'approve': approve,
                'confidence': confidence,
                'reasoning': reasoning[:200]
            }
            
        except Exception as e:
            print(f"[LLM] Error: {e}")
            return {
                'approve': True,
                'confidence': 'unknown',
                'reasoning': f'Error: {str(e)[:100]}'
            }


if __name__ == "__main__":
    print("=== LLM Validator Test ===")
    print("Set OPENAI_API_KEY environment variable before running")