import os, json
try:
    from google import genai
except Exception:
    genai=None

class GeminiService:
    def __init__(self):
        self.key=os.getenv("GEMINI_API_KEY")
        self.model=os.getenv("GEMINI_MODEL","gemini-3.8-flash")
        self.client=genai.Client(api_key=self.key) if self.key and genai else None
    def generate_meals(self, prompt):
        if not self.client: return None
        instruction=f"Return ONLY valid JSON array of 4 meals. Each meal must have id,name,description,time,difficulty,cost,cuisine,tags,ingredients,image. ingredients is arrays [normalized_name,quantity,unit]. User request: {prompt}"
        try:
            r=self.client.models.generate_content(model=self.model, contents=instruction)
            raw=r.text.strip().removeprefix("```json").removesuffix("```").strip()
            return json.loads(raw)
        except Exception: return None
