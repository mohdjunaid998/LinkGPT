import streamlit as st
import re
import os
import base64
import streamlit.components.v1 as components
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from groq import Groq
from supabase import create_client, Client # <--- BACKEND LIBRARY
from dotenv import load_dotenv
import shutil
import requests

# --- 1. LOAD CONFIG & VARIABLES ---
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TRANSCRIPT_API_KEY = os.getenv("TRANSCRIPT_API_KEY")

if not TRANSCRIPT_API_KEY:
    st.error("TRANSCRIPT_API_KEY missing! Railway settings mein jaakar add karein.")
    st.stop()

# --- 2. INITIALIZE CLIENTS ---
if not GROQ_API_KEY:
    st.error("GROQ_API_KEY missing! Check Railway Variables.")
    st.stop()

client = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- UI CONFIG ---
st.set_page_config(page_title="LinkGPT", layout="wide")

if "user_data" not in st.session_state:
    st.session_state.user_data = None 

# ----------------- UTILS -----------------

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

# ----------------- NEW PREMIUM TRANSCRIPT LOGIC -----------------

def get_transcript(video_url):
    video_id = extract_video_id(video_url)
    if not video_id: return None, "❌ Invalid YouTube URL"
    
    # --- STEP 1: CHECK SUPABASE CACHE FIRST ---
    try:
        cached_data = supabase.table("transcripts_cache") \
            .select("transcript") \
            .eq("video_id", video_id) \
            .execute()
        
        if cached_data.data and len(cached_data.data) > 0:
            st.toast("⚡ Speed Mode: Using cached data!", icon="🚀")
            return cached_data.data[0]['transcript'], None
    except Exception as e:
        print(f"Cache check error: {e}") # Agar cache fail ho toh API par move karenge

    # --- STEP 2: IF NOT IN CACHE, CALL PREMIUM API ---
    api_url = 'https://transcriptapi.com/api/v2/youtube/transcript'
    params = {'video_url': video_url, 'format': 'json'}
    headers = {'Authorization': f'Bearer {TRANSCRIPT_API_KEY}'}
    
    try:
        response = requests.get(api_url, params=params, headers=headers, timeout=45)
        
        if response.status_code == 200:
            full_text = response.json().get('transcript', '')
            
            if full_text:
                # --- STEP 3: SAVE TO CACHE FOR NEXT TIME ---
                try:
                    supabase.table("transcripts_cache").upsert({
                        "video_id": video_id,
                        "transcript": full_text
                    }).execute()
                    st.toast("✅ Saved to cache for next time!", icon="💾")
                except Exception as cache_err:
                    print(f"Failed to save to cache: {cache_err}")
                
                return full_text, None
            else:
                return None, "❌ API ne transcript return nahi ki."
        else:
            return None, f"❌ Transcript API Error: Code {response.status_code}"
            
    except Exception as e:
        return None, f"❌ Connection Error: {str(e)}"
    
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

raw_input_url = st.text_input("🔗 Paste YouTube Video Link", placeholder="https://youtube.com/watch?v=...")
video_url = clean_youtube_url(raw_input_url) if raw_input_url else ""

if video_url:
    user_query = st.text_area("💬 Ask anything about the video?", height=120, placeholder="Summarize this video...")
    
    if st.button("🚀 Analyze Video Intel", type="primary"):
        if not user_query:
            st.warning("Query likho bhai!")
        else:
            with st.spinner("🧠 Premium Intelligence Extracting..."):
                # Pehle check cache, then API logic inside this function
                transcript, error = get_transcript(video_url)
                
                if error:
                    st.error(error)
                else:
                    st.markdown("---")
                    res_box = st.empty()
                    full_response = ""
                    response_stream = get_ai_response(transcript, user_query)
                    
                    if isinstance(response_stream, str):
                        st.error(response_stream)
                    else:
                        for chunk in response_stream:
                            if chunk.choices[0].delta.content:
                                full_response += chunk.choices[0].delta.content
                                res_box.markdown(full_response + "▌")
                        res_box.markdown(full_response)
                        
                        # Database Save History Logic
                        if st.session_state.user_data:
                            try:
                                supabase.table("video_chats").insert({
                                    "user_email": st.session_state.user_data['email'],
                                    "query": user_query,
                                    "video_url": video_url
                                }).execute()
                            except: pass
else:
    st.info("👆 YouTube link dalo aur magic dekho.")
