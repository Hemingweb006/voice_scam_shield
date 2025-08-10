# 📞 Voice Scam Shield

**Voice Scam Shield** is a real-time scam call detection system designed to protect users from fraudulent and malicious calls.  
It listens to live conversations, detects scam patterns instantly, and alerts the user before any damage is done.

---

## 🚀 How It Works

1. **Live Call Analysis**  
   Incoming calls are transcribed in real time and analyzed by our AI engine.

2. **AI Scam Detection**  
   We use **OpenAI 20B OSS**, chosen for being **fast** and **lightweight**, as our main detection model.  
   The model is given a **specialized system prompt** that includes detailed descriptions of known scammer strategies.

3. **Structured Detection Output**  
   For every analyzed call, the AI returns a JSON object like this:

```json
{
  "scam": true,
  "risk_score": 85,
  "detected_strategies": ["Fake Authority", "Credential Harvesting"],
  "rationale": "Caller impersonated a bank and requested PIN code under urgency.",
  "recommended_action": "Do not share information. End call immediately."
}
```
# 📥 Installation

## 1. Clone the Repository
```bash
git clone https://github.com/Hemingweb006/voice-scam-shield.git
cd voice-scam-shield
```
2. Install Dependencies
```bash
pip install -r requirements.txt
```
🛠️ Technical Details
Model: OpenAI 20B OSS (fast + lightweight)

Detection Approach: Prompt-engineered LLM trained with real scam patterns

Output: Structured JSON with scam detection, risk score, strategies, rationale, and recommended actions

Use Case: Fraud prevention, financial scam protection, and real-time social engineering defense

📜 License
This project is open-source under the MIT License.

🏆 Acknowledgments
This project was developed as part of the HackNation Hackathon, organized by the MIT Sloan Club in collaboration with OpenAI.
