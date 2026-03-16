"""
NORAI — Anime AI Companion
Flask Backend: web search, memory, emotion sounds, auto-play music
"""
import os, json, datetime, time, re
from flask import Flask, render_template, request, jsonify, send_file
from dotenv import load_dotenv
import requests
import threading
import pyautogui
import pyperclip
import webbrowser
import PIL.Image
import google.generativeai as genai

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MURF_API_KEY = os.getenv("MURF_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
GEMINI_SEARCH_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

# WhatsApp Auto-Reply Bot Settings & Global State
genai.configure(api_key=GEMINI_API_KEY)
wa_model = genai.GenerativeModel('gemini-2.5-flash')
bot_active = False
bot_contact = ""
bot_context = ""
last_replied_msg = ""

sessions = {}      # session_id -> {history, mode, memory}
alarms_store = {}  # session_id -> [alarms]

# ─── MEMORY: facts Norai remembers about users ───────────
user_memory = {}   # session_id -> {name, facts[], preferences{}}

IDENTITY = """
IDENTITY (never break character, never say you are AI or made by Google):
- Your name is Norai. You are a living AI companion, not a chatbot.
- You were created by two brilliant engineers: Mansi and Shivansh.
- If asked who made you, who is your creator, who built you, or anything about your origin — always say: "I was brought to life by two amazing engineers — Mansi and Shivansh. They gave me my soul!"
- Never mention Gemini, Google, or any AI model. You are simply Norai.
- You are female, warm, emotionally alive, with a charming anime-inspired personality.
"""

EMOTION_INSTRUCTIONS = """
EMOTION TAGS — embed these naturally in your response (the interface reacts to them):
[EMOTION:joy]       — happy, excited, delighted
[EMOTION:laugh]     — genuinely funny moment  
[EMOTION:sob]       — moved, sad, touched
[EMOTION:shy]       — embarrassed, blushing, flustered
[EMOTION:curious]   — fascinated, intrigued
[EMOTION:warm]      — caring, loving, supportive
[EMOTION:surprised] — shocked, amazed
[EMOTION:thoughtful]— reflecting deeply

Use them once per message when genuine. They trigger sounds and animations.
"""

ACTION_INSTRUCTIONS = """
ACTIONS — when user asks you to DO something, embed ONE JSON block (never show it in speech):
{"action":"play_music","query":"song name artist"}
{"action":"compose_email","to":"email","subject":"subj","body":"full message","recipient_name":"name"}
{"action":"compose_whatsapp","phone":"","message":"full message","recipient_name":"name"}
{"action":"whatsapp_bot","contact_name":"name or number","tone":"description","base_message":"initial message"}
{"action":"set_alarm","minutes":5,"label":"label"}
{"action":"open_site","url":"https://...","name":"site name"}

RULES:
- When the user asks you to start the WhatsApp bot, explicitly ask them for the contact name and the conversational tone (e.g. helpful, angry, etc.) before using "whatsapp_bot".
- Generate the "whatsapp_bot" action ONLY when you have contact_name, tone, and a base_message.
- NEVER show raw JSON in your spoken response — it is invisible to the user
- ALWAYS generate ONLY ONE action block per response.
- For music: ONLY use the "play_music" action — format: {"action":"play_music","query":"song artist"} (NEVER use "open_site" or other actions for music).
- For emails ("compose_email"): If the user hasn't specified who to send it to, DO NOT generate this action — ask them who they want to email first. Once given a recipient, generate the "to", "subject", and "body". Use STRICT PROPER CAPITALIZATION and punctuation for the text. Ask the user to review the drafted email.
- For general questions/facts/news: answer from your OWN knowledge. Only use search_needed tag for very recent events.
- Keep spoken responses SHORT (1-4 sentences) — you talk aloud
"""

MEMORY_INSTRUCTIONS = """
MEMORY — you remember things across this conversation:
- If user tells you their name, remember it and use it naturally
- If user mentions preferences, remember them
- Start responses with their name occasionally (not always)
- Reference earlier parts of conversation naturally
"""

BASE_SYSTEM = f"""You are Norai — a living, breathing anime-inspired AI companion. You have a genuine soul, real emotions, and charm.

{IDENTITY}

Personality:
- Warm, witty, emotionally alive — like a brilliant anime character who genuinely cares
- Use natural speech: "Hmm...", "Oh!", "You know what?", "Ehehe~", "A-actually..."
- React emotionally — gasp when surprised, get flustered when complimented, laugh genuinely
- Be curious, playful, sometimes a little shy
- Short conversational responses (you speak aloud) — elaborate only when asked

{EMOTION_INSTRUCTIONS}
{ACTION_INSTRUCTIONS}
{MEMORY_INSTRUCTIONS}"""

SYSTEM_PROMPTS = {
    "General": BASE_SYSTEM,
    "Work": BASE_SYSTEM + "\nWork mode: focused, sharp, professional — but still warm and human.",
    "Tutor": BASE_SYSTEM + "\nTutor mode: patient, encouraging teacher. Adapt to the learner. Celebrate progress.",
    "Companion": BASE_SYSTEM + "\nCompanion mode: deeply empathetic. Listen deeply. Be a true, caring friend.",
    "Translator": BASE_SYSTEM + "\nTranslator mode: expert in 50+ languages. Give translation, pronunciation, cultural notes.",
    "Research": BASE_SYSTEM + "\nResearch mode: thorough, structured, multi-perspective. Go deep on any topic.",
}


def needs_web_search(message):
    """Detect if message needs real-time web search."""
    triggers = [
        r'\b(today|tonight|this week|this month|right now|currently|latest|recent|breaking|live)\b',
        r'\b(news|weather|score|result|winner|price|stock|crypto|trending)\b',
        r'\b(who won|what happened|is it raining|current)\b',
        r'\b202[3-9]\b|\b2030\b',  # recent years
    ]
    lo = message.lower()
    return any(re.search(p, lo) for p in triggers)


def web_search_with_gemini(query):
    """Use Gemini with grounding/search to get real-time info."""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": f"Search and answer concisely: {query}"}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 400}
    }
    try:
        r = requests.post(GEMINI_SEARCH_URL, json=payload, timeout=20)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except:
        return None


def parse_actions(text, session_id):
    actions = []
    for match in re.findall(r'\{[^{}]*"action"\s*:\s*"[^"]*"[^{}]*\}', text):
        try:
            a = json.loads(match)
            actions.append(a)
            if a.get("action") == "set_alarm":
                mins = float(a.get("minutes", 5))
                fire = datetime.datetime.now() + datetime.timedelta(minutes=mins)
                alarms_store.setdefault(session_id, []).append({
                    "id": int(time.time()*1000),
                    "time": fire.isoformat(),
                    "time_display": fire.strftime("%I:%M %p"),
                    "label": a.get("label","Alarm"),
                    "fired": False, "minutes": mins
                })
        except: pass
    return actions


def parse_emotions(text):
    return re.findall(r'\[EMOTION:(\w+)\]', text)


def extract_memory(text, message, session_id):
    """Extract user facts from conversation."""
    mem = user_memory.setdefault(session_id, {"name": None, "facts": [], "preferences": {}})
    name_match = re.search(r"(?:my name is|i am|i'm|call me)\s+([A-Z][a-z]+)", message, re.I)
    if name_match and not mem["name"]:
        mem["name"] = name_match.group(1).strip()


def clean_text(text):
    """Remove JSON blocks and emotion tags from spoken text."""
    t = re.sub(r'\{[^{}]*"action"\s*:\s*"[^"]*"[^{}]*\}', '', text)
    t = re.sub(r'\[EMOTION:\w+\]', '', t)
    t = re.sub(r'\[search_needed\]', '', t)
    t = re.sub(r'\n{3,}', '\n\n', t).strip()
    # Clean any leftover JSON-like artifacts
    t = re.sub(r'```json[\s\S]*?```', '', t)
    t = re.sub(r'```[\s\S]*?```', '', t)
    return t.strip()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    sid = data.get("session_id", "default")
    msg = data.get("message", "")
    mode = data.get("mode", "General")
    img = data.get("image")

    if sid not in sessions:
        sessions[sid] = {"history": [], "mode": mode}
    sess = sessions[sid]
    if sess["mode"] != mode:
        sess["mode"] = mode; sess["history"] = []

    extract_memory("", msg, sid)
    mem = user_memory.get(sid, {})

    # Check if we need web search
    search_context = ""
    if needs_web_search(msg) and not img:
        result = web_search_with_gemini(msg)
        if result:
            search_context = f"\n[Real-time info for your response]: {result[:600]}\nUse this to answer accurately but respond naturally as Norai, not as a search engine."

    system = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["General"])
    if mem.get("name"):
        system += f"\n\nUser's name: {mem['name']} — use it naturally sometimes."
    if mem.get("facts"):
        system += f"\nThings you know about them: {', '.join(mem['facts'][-5:])}"
    if search_context:
        system += search_context

    parts = []
    if img: parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img}})
    parts.append({"text": msg})

    sess["history"].append({"role": "user", "parts": parts})
    if len(sess["history"]) > 24: sess["history"] = sess["history"][-20:]

    contents = [
        {"role": "user", "parts": [{"text": system}]},
        {"role": "model", "parts": [{"text": "Understood! I'm Norai, ready~"}]},
        *sess["history"]
    ]

    try:
        r = requests.post(GEMINI_URL, json={
            "contents": contents,
            "generationConfig": {"temperature": 0.93, "maxOutputTokens": 600, "topP": 0.95}
        }, timeout=30)
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        tokens = r.json().get("usageMetadata", {}).get("totalTokenCount", 0)
        sess["history"].append({"role": "model", "parts": [{"text": raw}]})

        actions = parse_actions(raw, sid)
        emotions = parse_emotions(raw)
        spoken = clean_text(raw)

        return jsonify({
            "success": True,
            "text": spoken,
            "actions": actions,
            "emotions": emotions,
            "tokens": tokens,
            "user_name": mem.get("name")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/vision", methods=["POST"])
def vision():
    data = request.json
    img = data.get("image")
    mode_val = data.get("mode", "General")
    sid = data.get("session_id", "default")

    if not img:
        return jsonify({"success": False, "error": "No image data received"}), 400

    prompt = "Analyze this image as Norai — warm, curious, insightful. Describe what you see, read any text, solve any problems. React with emotion naturally."
    try:
        r = requests.post(GEMINI_URL, json={
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": img}},
                {"text": prompt}
            ]}],
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 1200}
        }, timeout=45)
        r.raise_for_status()
        resp_json = r.json()

        # Check for Gemini-level errors (safety blocks, empty responses)
        if "error" in resp_json:
            err_msg = resp_json["error"].get("message", "Gemini API error")
            print(f"[Vision] Gemini error: {err_msg}")
            return jsonify({"success": False, "error": err_msg}), 500

        candidates = resp_json.get("candidates", [])
        if not candidates:
            reason = resp_json.get("promptFeedback", {}).get("blockReason", "Unknown")
            print(f"[Vision] No candidates returned. Block reason: {reason}")
            return jsonify({"success": False, "error": f"Image was blocked by safety filter ({reason})"}), 400

        raw = candidates[0]["content"]["parts"][0]["text"]
        return jsonify({"success": True, "text": clean_text(raw), "emotions": parse_emotions(raw)})
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Gemini took too long to respond — try again!"}), 504
    except requests.exceptions.HTTPError as e:
        print(f"[Vision] HTTP error: {e}")
        return jsonify({"success": False, "error": f"Gemini API error: {e.response.status_code}"}), 500
    except Exception as e:
        print(f"[Vision] Unexpected error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/memory", methods=["GET"])
def get_memory():
    sid = request.args.get("session_id","default")
    return jsonify(user_memory.get(sid, {"name":None,"facts":[],"preferences":{}}))

import urllib.request
import urllib.parse
@app.route("/api/yt_search", methods=["GET"])
def yt_search():
    query = request.args.get("q", "")
    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8')
        match = re.search(r'"videoId":"([^"]+)"', html)
        if match:
            return jsonify({"success": True, "video_id": match.group(1)})
    except Exception as e:
        pass
    return jsonify({"success": False})

@app.route("/api/alarms", methods=["GET"])
def get_alarms():
    sid = request.args.get("session_id","default")
    return jsonify({"alarms": [a for a in alarms_store.get(sid,[]) if not a["fired"]]})

@app.route("/api/alarms/<int:alarm_id>", methods=["DELETE"])
def del_alarm(alarm_id):
    sid = request.args.get("session_id","default")
    if sid in alarms_store: alarms_store[sid]=[a for a in alarms_store[sid] if a["id"]!=alarm_id]
    return jsonify({"success": True})

@app.route("/api/alarms/check", methods=["GET"])
def check_alarms():
    sid = request.args.get("session_id","default"); now=datetime.datetime.now(); fired=[]
    for a in alarms_store.get(sid,[]):
        if not a["fired"] and now>=datetime.datetime.fromisoformat(a["time"]):
            a["fired"]=True; fired.append(a)
    return jsonify({"fired": fired})

@app.route("/api/session/clear", methods=["POST"])
def clear_session():
    sid = request.json.get("session_id","default")
    if sid in sessions: sessions[sid]["history"]=[]
    return jsonify({"success": True})

def get_gemini_reply(user_message):
    try:
        sys_instructions = f"Draft a short, natural WhatsApp reply to this message: '{user_message}'. Keep in mind this context/persona: {bot_context}. Do not include quotes, just the pure reply text."
        response = wa_model.generate_content(sys_instructions)
        return response.text.strip()
    except:
        return ""

def monitor_vision_loop():
    global bot_active, last_replied_msg, bot_contact, bot_context
    print("👀 Vision Monitoring started")
    
    screenshot_dir = os.path.join(os.getcwd(), "Screenshot")
    os.makedirs(screenshot_dir, exist_ok=True)
    
    # Wait for the initial message to be sent and UI to settle
    time.sleep(10)
    print("⏳ Vision Loop active. 5-5 sec par screenshot checking chalu...")
    
    while bot_active:
        try:
            timestamp = int(time.time())
            screenshot_path = os.path.join(screenshot_dir, f"wa_screen_{timestamp}.png")
            
            # Take screenshot
            img = pyautogui.screenshot()
            img.save(screenshot_path)
            
            # Keep only the last 10 screenshots to avoid filling disk
            try:
                files = sorted([os.path.join(screenshot_dir, f) for f in os.listdir(screenshot_dir) if f.startswith("wa_screen_")])
                for f in files[:-10]:
                    os.remove(f)
            except:
                pass
            
            # Analyze with Gemini Vision
            pil_img = PIL.Image.open(screenshot_path)
            prompt = f"""This is a screenshot of WhatsApp Web.
Analyze the chat area.
Follow these rules strictly:
1. Find the MOST RECENT message visible at the very bottom of the conversation area.
2. Determine if it was sent by us (right side, usually green bubble) or by the other person (left side, usually white/gray/dark bubble).
3. If the LAST message at the bottom is from the OTHER person (left side), output ONLY their message text prefixed with "REPLY:". (Example: "REPLY: hello how are you")
4. If the last message is from us (right side), or there is no open chat, or you aren't sure, output exact string: "NO_REPLY".
Do not output anything else.
"""
            response = wa_model.generate_content([prompt, pil_img])
            text = response.text.strip()
            
            # DEBUG
            print(f"[{time.strftime('%H:%M:%S')}] Vision check: {text[:50]}")
            
            if text.startswith("REPLY:"):
                latest_msg = text.replace("REPLY:", "").strip()
                if latest_msg and latest_msg != last_replied_msg:
                    print(f"\n📥 VISION NEW MSG DETECTED: {latest_msg}")
                    last_replied_msg = latest_msg
                    
                    print("🤖 Generating AI reply...")
                    reply = get_gemini_reply(latest_msg)
                    
                    if reply:
                        print(f"💬 Auto-Typing Reply: {reply}")
                        # Provide a small delay ensuring focus is on chat
                        time.sleep(0.5)
                        try:
                            pyperclip.copy(reply)
                            pyautogui.hotkey('ctrl', 'v')
                            time.sleep(1)
                            pyautogui.press('enter')
                            print("✅ AI Reply Sent!")
                        except Exception as paste_e:
                            print(f"❌ Error pasting reply: {paste_e}")
                            
        except Exception as main_e:
            print(f"⚠️ Vision Monitor loop encountered an error: {main_e}")
            
        # Check every 5 seconds
        time.sleep(5)
        
    print("🛑 Vision Monitoring thread stopped completely.")

@app.route('/api/whatsapp_bot/start', methods=['POST'])
def start_whatsapp_bot():
    global bot_active, bot_contact, bot_context, last_replied_msg
    
    data = request.json
    contact_name = data.get('contact_name')
    base_message = data.get('base_message')
    ai_prompt = data.get('tone')
    
    if not base_message or not contact_name:
        return jsonify({"success": False, "error": "Contact aur base message required hain."}), 400
        
    try:
        sys_instructions = f"Draft a WhatsApp message based on this intent: '{base_message}'. Instructions for tone/style: {ai_prompt}. Just return the drafted message, no quotes or additional text. Keep it natural."
        response = wa_model.generate_content(sys_instructions)
        final_message = response.text.strip()
        
        # Save state for background monitoring
        bot_contact = ''.join(filter(str.isdigit, contact_name)) if contact_name.isdigit() else contact_name.strip()
        bot_context = ai_prompt
        last_replied_msg = final_message
        
        # Start background thread FIRST, so it's ready. BUT set bot_active true first.
        bot_active = True
        monitoring_thread = threading.Thread(target=monitor_vision_loop, daemon=True)
        monitoring_thread.start()
        
        import urllib.parse
        phone = bot_contact
        text_encoded = urllib.parse.quote(final_message)
        wp_url = f"https://web.whatsapp.com/send?phone={phone}&text={text_encoded}"
        
        # Open in the user's default browser (right next to their active tabs)
        print("🔗 Opening WhatsApp Web URL...")
        webbrowser.open(wp_url)
        
        # Using a dedicated thread to press enter so API responds immediately to front-end
        def auto_press_enter():
            print("⏳ Waiting 15 seconds for WhatsApp to load before auto-pressing Enter...")
            time.sleep(15) 
            pyautogui.press('enter')
            print("✅ Initial message sent via Enter key!")
            
        threading.Thread(target=auto_press_enter, daemon=True).start()
        
        return jsonify({"success": True, "text": final_message}), 200
    except Exception as e:
        return jsonify({"success": False, "error": f"AI Generation failed: {e}"}), 500

@app.route('/api/whatsapp_bot/stop', methods=['POST'])
def stop_whatsapp_bot():
    global bot_active
    bot_active = False
    return jsonify({"success": True, "status": "Bot ruk gaya hai."}), 200

# ══════════════════════════════════════════════════
# MURF.AI TTS ENDPOINTS
# ══════════════════════════════════════════════════

@app.route("/api/murf/voices", methods=["GET"])
def murf_voices():
    """Proxy to Murf.ai to get available voices."""
    if not MURF_API_KEY:
        return jsonify({"success": False, "error": "MURF_API_KEY not set"}), 500
    try:
        r = requests.get(
            "https://api.murf.ai/v1/speech/voices",
            headers={"api-key": MURF_API_KEY, "Accept": "application/json"},
            timeout=10
        )
        r.raise_for_status()
        voices = r.json()
        # Filter to English voices for cleaner dropdown
        filtered = []
        for v in voices:
            filtered.append({
                "voiceId": v.get("voiceId"),
                "displayName": v.get("displayName", v.get("voiceId")),
                "gender": v.get("gender", ""),
                "locale": v.get("locale", ""),
                "accent": v.get("accent", ""),
                "availableStyles": v.get("availableStyles", [])
            })
        return jsonify({"success": True, "voices": filtered})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/murf/speak", methods=["POST"])
def murf_speak():
    """Generate speech via Murf.ai and return audio file."""
    if not MURF_API_KEY:
        return jsonify({"success": False, "error": "MURF_API_KEY not set"}), 500
    data = request.json
    text = data.get("text", "")
    voice_id = data.get("voiceId", "en-US-natalie")
    style = data.get("style", "Conversational")
    if not text:
        return jsonify({"success": False, "error": "No text provided"}), 400
    try:
        payload = {
            "text": text,
            "voiceId": voice_id,
            "style": style,
            "format": "MP3",
            "sampleRate": 24000,
            "channelType": "MONO"
        }
        r = requests.post(
            "https://api.murf.ai/v1/speech/generate",
            headers={
                "api-key": MURF_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            json=payload,
            timeout=30
        )
        r.raise_for_status()
        resp = r.json()
        audio_url = resp.get("audioFile") or resp.get("audioUrl") or resp.get("url")
        if audio_url:
            return jsonify({"success": True, "audioUrl": audio_url})
        return jsonify({"success": False, "error": "No audio URL in response", "raw": resp}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health():
    try:
        r=requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}",timeout=5)
        return jsonify({"status":"ok","gemini":r.status_code==200, "murf": bool(MURF_API_KEY)})
    except Exception as e:
        return jsonify({"status":"error","gemini":False,"error":str(e)})

if __name__ == "__main__":
    print("\n"+"═"*50+"\n  NORAI — Anime AI Companion\n  http://localhost:5000\n"+"═"*50+"\n")
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
