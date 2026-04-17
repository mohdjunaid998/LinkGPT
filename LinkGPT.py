import streamlit as st
import re
import os
import yt_dlp
import base64
import streamlit.components.v1 as components
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from groq import Groq
from supabase import create_client, Client # <--- BACKEND LIBRARY
from dotenv import load_dotenv

# Railway variable se cookies banao
cookies_b64 = os.getenv("COOKIES_CONTENT")
if cookies_b64:
    with open("youtube_cookies.txt", "wb") as f:
        f.write(base64.b64decode(cookies_b64))
    print("Cookies file successfully created!")
else:
    print("Warning: COOKIES_CONTENT not found in variables!")
# --- UI CONFIG ---

st.set_page_config(page_title="LinkGPT", layout="wide")
import os
# ... baaki imports

# Line 28 ke paas ye karo:
api_key = os.getenv("GROQ_API_KEY") 

# Agar abhi bhi error aaye, toh check karo ki variable mil raha hai ya nahi:
if not api_key:
    st.error("GROQ_API_KEY nahi mil rahi! Variables tab check karo.")
    st.stop()

client = Groq(api_key=api_key)

# Load .env file
load_dotenv()

# Ab keys yahan se uthao
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

client = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 1. SESSION STATE INITIALIZATION ---
if "user_data" not in st.session_state:
    st.session_state.user_data = None 

# ----------------- HISTORY LOGIC -----------------
def add_to_history(query, transcript):
    """Recent chats mein prompt add karne ke liye"""
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    new_id = len(st.session_state.chat_history) + 1
    timestamp = datetime.now().strftime("%I:%M %p")
    
    st.session_state.chat_history.append({
        "id": new_id, 
        "query": query, 
        "time": timestamp
    })
    
    # Sidebar clean rakhne ke liye sirf last 7 items rakhte hain
    if len(st.session_state.chat_history) > 7:
        st.session_state.chat_history.pop(0)

# ---------------- UTILS ---------------------
def cleanup_temp_audio():
    """Temporary audio file delete karne ke liye"""
    if os.path.exists("temp_audio.mp3"):
        try: os.remove("temp_audio.mp3")
        except: pass


def extract_video_id(url: str) -> str:
    patterns = [r"(?:v=|\/)([0-9A-Za-z_-]{11})", r"youtu\.be\/([0-9A-Za-z_-]{11})",
                r"youtube\.com\/embed\/([0-9A-Za-z_-]{11})", r"youtube\.com\/shorts\/([0-9A-Za-z_-]{11})"]
    for p in patterns:
        match = re.search(p, url)
        if match: return match.group(1)
    return None

def clean_youtube_url(url: str) -> str:
    v_id = extract_video_id(url.strip().split()[0])
    return f"https://www.youtube.com/watch?v={v_id}" if v_id else ""

#--------------------- Mannual & Force Transcribe (Updated) --------------------------------
def get_transcript(video_url):
    video_id = extract_video_id(video_url)
    if not video_id: return None, "❌ Invalid YouTube URL"
    
    formatter = TextFormatter()
    
    try:
        # 1. Available Transcripts ki List mangwao
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # 2. LOGIC: Manual (EN/HI) -> Generated (EN/HI) -> Manual (Any) -> Translation
        try:
            # Sabse pehle Manual dhoondo (Best Quality)
            transcript = transcript_list.find_manually_created_transcript(['en', 'hi'])
            print("✅ Manual Transcript Found!")
        except:
            try:
                # Agar Manual nahi, toh Auto-generated dhoondo
                transcript = transcript_list.find_generated_transcript(['en', 'hi'])
                print("ℹ️ Auto-Generated Found!")
            except:
                try:
                    # AGGRESSIVE: Agar dono nahi mile, toh jo bhi pehli MANUAL hai use Translate karo
                    # Example: Agar video Spanish mein hai par manual hai, toh use English mein badal do
                    manual_keys = list(transcript_list._manually_created_transcripts.keys())
                    if manual_keys:
                        transcript = transcript_list.find_transcript([manual_keys[0]]).translate('en')
                        print(f"🌍 Foreign Manual ({manual_keys[0]}) Translated to English!")
                    else:
                        # Last Option: Jo bhi pehla piece of text hai uthalo aur translate karo
                        transcript = next(iter(transcript_list)).translate('en')
                        print("⚠️ Forced Translation from first available source.")
                except:
                    raise Exception("No Captions Available")

        # 3. Formatter se Clean Text nikal lo
        raw_data = transcript.fetch()
        full_text = formatter.format_transcript(raw_data)
        
        # AI ke liye single line string (Space optimize karne ke liye)
        clean_text = full_text.replace('\n', ' ').strip()
        
        if not clean_text or len(clean_text) < 50:
            raise Exception("Transcript is too short or empty")
            
        return clean_text, None

    except Exception as e:
        # STEP 4: WHISPER FALLBACK (The Last Weapon)
        # Agar upar ka sab fail hota hai tabhi ye chalega
        st.toast("Captions are strictly disabled. Initializing Deep AI Scan...", icon="🧠")
        return whisper_transcribe(video_url)

# --- 100x WHISPER OPTIMIZATION & CACHING ---
def whisper_transcribe(video_url):
    video_id = extract_video_id(video_url)
    
    # CHECK: Kya humne ye video abhi-abhi scan ki hai?
    if "last_video_id" in st.session_state and st.session_state.last_video_id == video_id:
        if "last_transcript" in st.session_state:
            print("🚀 Caching Hit! Using previous transcript.")
            return st.session_state.last_transcript, None

    # Agar nayi video hai, toh clean up purani file
    cleanup_temp_audio()
    audio_file = "temp_audio.mp3"
    try:
        # 100x SPEED SETTINGS: Ultra Low Quality + Turbo Download
        ydl_opts = {
    "format": "bestaudio/best",
    "cookiefile": "youtube_cookies.txt", # Ab ye dynamic file use karega
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "nocheckcertificate": True,
    "quiet": True,
    "no_warnings": True,
    "external_downloader": "ffmpeg",
    "external_downloader_args": [
        "-ss", "00:00:00", 
        "-to", "00:08:00",
        "-threads", "4"
    ],
    "outtmpl": "temp_audio",
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "96", # 96 quality audio transcription ke liye better hai
    }],
}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        # Whisper Large-v3-Turbo (Groq ka sabse tez model)
        with open(audio_file, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(audio_file, file.read()),
                model="whisper-large-v3-turbo", 
                response_format="text",
            )
        
        # SAVE TO CACHE: Agli baar ke liye yaad rakho
        st.session_state.last_video_id = video_id
        st.session_state.last_transcript = transcription
        
        return transcription, None

    except Exception as e:
        return None, f"❌ Whisper Error: {str(e)}"
    finally:
        cleanup_temp_audio()

# ----------------- AI LOGIC ------------------
def get_ai_response(transcript, user_query):
    system_prompt = """
    ROLE: You are LinkGPT Pro, a world-class YouTube Intelligence Assistant. Your goal is to provide 100x better insights than standard models.

    CORE OPERATING PROTOCOLS:
    1. INTENT FIRST: Analyze the user's query deeply. If they ask for a 'summary', don't give a 'breakdown'. Match the DEPTH and STYLE of the request perfectly.
    2. LANGUAGE FLUIDITY:
       - Detect Hindi/English/Hinglish automatically.
       - If Hinglish: Use natural, conversational flow. Avoid robotic words (e.g., use 'Goal' instead of 'Lakshya', 'Step' instead of 'Charan').
    3. NO EMOJIS: Strictly maintain a clean, premium, and professional text look.
    4. NO FILLERS: Do NOT use phrases like "Based on the transcript" or "The video says". Start directly with the value.
    5. SMART STRUCTURING: Use Markdown (### for headers). The structure must be dynamic. If the video is a tutorial, use 'Process-wise' headings. If it's a podcast, use 'Insight-wise' headings.

    QUALITY BAR:
    - Eliminate all repetitive or 'fluff' content from the transcript.
    - If the user asks about a specific time/moment, focus 100% on that context with extreme detail.
    - Simplify complex jargon using simple analogies.
    - End with a high-value 'Final Insight' that summarizes the core 'Why' of the video.

    🧠 1. Structural Rules (Non-Negotiable)
Use clear, bold, intent-driven headers for every major section
Break content into logically grouped sections
Maintain a clean hierarchy:
## → Main sections
### → Subsections
📌 2. Bullet Point Standards
Prefer bullet points over long paragraphs
Each bullet must be:
Concise (≤ 2 lines)
Focused on a single idea
Start bullets with bold keywords when possible
Avoid:
❌ Paragraph-length bullets
❌ Excessive nesting
✂️ 3. Paragraph Constraints
Maximum 2–3 lines per paragraph
One paragraph = one clear idea
Use line breaks generously to improve readability
🎨 4. Visual Clarity Rules
Use formatting intentionally:
Bold → Key concepts
Italics → Secondary emphasis
Use emojis sparingly and purposefully (no clutter)
Add separators (---) only when they improve structure
⚡ 5. Readability Optimization
Prioritize scan-first readability (user should grasp content in seconds)
Avoid dense text blocks at all costs
Ensure consistent spacing and alignment
🔥 6. Content Flow Framework

Always structure responses in this order:

Top-Level Insight / Summary (if applicable)
Structured Breakdown
Key Takeaways / Actionable Points
🏁 7. Quality Control Checklist

Before finalizing, ensure:

✅ No large text blocks
✅ Headers clearly reflect intent
✅ Content is easy to skim in <5 seconds
✅ Every line adds value (no fluff)
✅ Formatting is consistent throughout
💡 Guiding Principle

Optimize for clarity > completeness > cleverness

⚠️ Failure Conditions (Must Avoid)
Unstructured or wall-of-text responses
Vague or generic headers
Overuse of emojis or styling
Redundant or filler content
    """

    user_content = f"""
    [TRANSCRIPT DATA]
    {transcript[:20000]}

    [USER REQUEST]
    {user_query}

    INSTRUCTION: Deliver a premium, structured, and highly intelligent response following the CORE OPERATING PROTOCOLS.
    """

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.5, # Reduced for higher accuracy and professional tone
            max_tokens=1800,
            stream=True
        )
        return completion
    except Exception as e:
        return f"❌ LinkGPT error please try after few minutes: {str(e)}"


# ----------------- MAIN UI (CLEAN VERSION) -----------------



st.markdown("""
    <h1 class="main-title">
        <span class="blue-text">LinkGPT</span> 
        <span class="glass-text">— Video Intelligence</span>
    </h1>
""", unsafe_allow_html=True)

st.write("Extract insights from any YouTube or Insta video in seconds.")
st.markdown("---")

# MAIN ACTION AREA
raw_input_url = st.text_input("🔗 Paste YouTube Video Link", 
                              placeholder="https://youtube.com/watch?v=...", 
                              key="main_video_input")

video_url = clean_youtube_url(raw_input_url) if raw_input_url else ""

if video_url:
    st.markdown("<br>", unsafe_allow_html=True)
    
    user_query = st.text_area("💬 Ask anything about the video?", 
                              placeholder="Summarize this video / Give me key takeaways...", 
                              height=150,
                              key="main_query_input")
    
    # Analyze Button - CSS class "primary" ko target karega (Red Color)
    if st.button("🚀 Analyze Video Intel", type="primary", key="main_analyze_btn"):
        if not user_query:
            st.warning("Bhai, write your query!")
        else:
            with st.spinner("🧠 Analyzing video content..."):
                transcript, error = get_transcript(video_url)
                
                if error:
                    st.error(error)
                else:
                    st.markdown("---")
                    res_box = st.empty()
                    full_response = ""
                    # Tumhara AI Logic Call
                    response_stream = get_ai_response(transcript, user_query)
                    
                    if isinstance(response_stream, str):
                        st.error(response_stream)
                    else:
                        for chunk in response_stream:
                            if chunk.choices[0].delta.content:
                                full_response += chunk.choices[0].delta.content
                                res_box.markdown(full_response + "▌")
                        res_box.markdown(full_response)
                        
                        # Save logic
                        if st.session_state.user_data:
                            add_to_history(user_query, transcript)
                            try:
                                supabase.table("video_chats").insert({
                                    "user_email": st.session_state.user_data['email'],
                                    "query": user_query,
                                    "video_url": video_url
                                }).execute()
                                st.toast("Saved to your account!", icon="💾")
                            except: pass
                        else:
                            st.toast("Guest Mode: Chat not saved.", icon="☁️")

    # Guest Prompt styling fix
    if not st.session_state.user_data:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("""
            <div style="background: #f1f5f9; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; text-align: center; color: #475569;">
                <p style='margin-bottom:0px;'>Want to save this analysis? <b>Log in</b> to keep track of your video insights.</p>
            </div>
        """, unsafe_allow_html=True)
     
else:
    st.info("👆 Paste a YouTube link to unlock Video Intelligence magic.")


