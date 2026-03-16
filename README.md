# NORAI — AI Reality Interface Agent
### Full-Stack Python + Flask AI Companion

---

## 🚀 Setup & Run (2 minutes)

### 1. Install dependencies
```bash
pip install flask requests
```

### 2. Run the server
```bash
python app.py
```

### 3. Open browser
```
http://localhost:5000
```

That's it. Norai is live.

---

## 📁 Project Structure

```
norai/
├── app.py              ← Python Flask backend (ALL logic lives here)
├── requirements.txt    ← pip dependencies
├── templates/
│   └── index.html      ← Frontend UI (talks to Python via /api/* routes)
└── README.md
```

---

## 🔌 API Endpoints (Python handles everything)

| Method | Endpoint | What it does |
|--------|----------|--------------|
| GET | `/` | Serves the UI |
| POST | `/api/chat` | Sends message → Gemini → returns response |
| POST | `/api/vision` | Sends camera image → Gemini Vision → returns analysis |
| GET | `/api/alarms` | Lists active alarms |
| POST | `/api/alarms` | Creates a new alarm |
| DELETE | `/api/alarms/<id>` | Deletes an alarm |
| GET | `/api/alarms/check` | Polls for fired alarms (frontend calls every second) |
| POST | `/api/session/clear` | Resets conversation history |
| GET | `/api/health` | Checks Gemini API connectivity |

---

## ✅ What's Fully Functional

- **🎙️ Voice Recognition** — Browser mic → Python processes → Gemini responds → TTS reads it back
- **🤖 Real AI Chat** — Full conversation history stored in Python, sent to Gemini 1.5 Flash
- **📷 Camera Vision** — Capture frame → Python sends to Gemini Vision → spoken analysis
- **⏰ Real Alarms** — Python stores alarms with real timestamps, frontend polls `/api/alarms/check` every second, fires with audio beep + speech
- **🎭 6 Modes** — Each mode sends a different system prompt to Gemini from Python, resets history
- **🌐 Streaming** — `/api/chat/stream` endpoint for token-by-token streaming (SSE)
- **🔊 Text-to-Speech** — Browser Web Speech API reads Norai's responses aloud
- **🎵 Music** — Opens Spotify search in new tab
- **💾 Session Memory** — Conversation history per session stored in Python dict

---

## 🔑 API Key
Already configured in `app.py`:
```python
GEMINI_API_KEY = "YOUR_API_KEY"
```

---

## 🌐 Deploy to Google Cloud Run
```bash
# Build and deploy
gcloud run deploy norai \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 5000
```

Add a `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```
