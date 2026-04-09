import streamlit as st
import re
import os
import yt_dlp
import base64
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from groq import Groq
from supabase import create_client, Client

# ----------------- 1. CONFIG & BACKEND -----------------
st.set_page_config(page_title="LinkGPT — Video Intelligence Platform", page_icon="🎬", layout="wide")

# Secrets Loading
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

client = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------- 2. AUTHENTICATION LOGIC -----------------
def google_login():
    # Supabase Google Auth URL generate karega
    res = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {
            "redirect_to": "https://linkgpt.streamlit.app" # Apna actual URL yahan dalo
        }
    })
    # Isse user Google login page par redirect ho jayega
    st.markdown(f'<meta http-equiv="refresh" content="0;url={res.url}">', unsafe_allow_html=True)

# Session State for User
if "user_data" not in st.session_state:
    # Page load hone par check karo ki kya user oauth se wapas aaya hai
    try:
        curr_user = supabase.auth.get_user()
        if curr_user:
            st.session_state.user_data = {
                "name": curr_user.user.user_metadata.get('full_name', 'User'),
                "email": curr_user.user.email,
                "dp_url": curr_user.user.user_metadata.get('avatar_url', 'https://api.dicebear.com/7.x/initials/svg?seed=User')
            }
        else:
            st.session_state.user_data = None
    except:
        st.session_state.user_data = None

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

u = st.session_state.user_data if st.session_state.user_data else {}

# ----------------- 3. PREMIUM UI (ORIGINAL CSS) -----------------
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif !important;
        color: #c9d1d9 !important;
    }

    .main {
        background: radial-gradient(circle at top right, #1e1e2f, #0e1117);
    }

    section[data-testid="stSidebar"] {
        background-color: rgba(17, 25, 40, 0.75);
        backdrop-filter: blur(12px);
        border-right: 1px solid rgba(255, 255, 255, 0.1);
    }

    .stButton>button {
        background: linear-gradient(135deg, #FF4B4B 0%, #cc0000 100%);
        color: white;
        border-radius: 12px;
        border: none;
        padding: 0.6rem 2rem;
        font-weight: 700;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(255, 75, 75, 0.3);
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(255, 75, 75, 0.5);
    }

    .stCard {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 1.5rem;
        backdrop-filter: blur(10px);
    }

    div.stTextArea textarea, div.stTextInput input {
        background-color: rgba(255, 255, 255, 0.02) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: white !important;
        border-radius: 12px !important;
        padding: 15px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ----------------- 4. UTILS & TRANSCRIPTION -----------------
def cleanup_temp_audio():
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

def whisper_transcribe(video_url):
    save_path = os.path.join(os.getcwd(), "temp_audio")
    cleanup_temp_audio()
    
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "outtmpl": save_path + ".%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        audio_file = "temp_audio.mp3"
        with open(audio_file, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(audio_file, file.read()),
                model="whisper-large-v3-turbo",
                response_format="text",
            )
        return transcription, None
    except Exception as e:
        return None, f"❌ Whisper Error: {str(e)}"
    finally:
        cleanup_temp_audio()

def get_transcript(video_url):
    video_id = extract_video_id(video_url)
    if not video_id: return None, "❌ Invalid YouTube URL"
    
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript(['en', 'hi']).fetch()
        clean_text = " ".join([t['text'] for t in transcript])
        return clean_text, None
    except:
        return whisper_transcribe(video_url)

# ----------------- 5. AI ENGINE -----------------
def get_ai_response(transcript, user_query):
    # (Same prompt logic as before - abbreviated for code block)
    system_prompt = "You are LinkGPT Pro. Provide 10x intelligent insights. Use markdown structure."
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Transcript: {transcript[:18000]}\nQuery: {user_query}"}],
            temperature=0.5, stream=True
        )
        return completion
    except Exception as e:
        return f"❌ Error: {str(e)}"

# ----------------- 6. SIDEBAR (ORIGINAL LOOK) -----------------
with st.sidebar:
    if st.session_state.user_data:
        col_dp, col_txt = st.columns([1, 3])
        with col_dp:
            st.markdown(f"""<img src="{u.get('dp_url')}" style="border-radius: 50%; width: 50px;">""", unsafe_allow_html=True)
        with col_txt:
            st.markdown(f"**{u.get('name')}**")
            st.caption(u.get('email'))
        
        st.button("✨ Upgrade", use_container_width=True)
        
        if st.button("Log Out", use_container_width=True):
            supabase.auth.sign_out()
            st.session_state.user_data = None
            st.rerun()
    else:
        st.markdown('<div style="text-align:center;"><img src="https://api.dicebear.com/7.x/initials/svg?seed=Guest" style="width:80px; border-radius:50%; margin-bottom:10px;"></div>', unsafe_allow_html=True)
        st.markdown("<h3 style='text-align:center;'>Welcome</h3>", unsafe_allow_html=True)
        
        # --- NEW GOOGLE SIGNUP BUTTON ---
        if st.button("🚀 Continue with Google", use_container_width=True, type="primary"):
            google_login()

# ----------------- 7. MAIN UI -----------------
st.title("LinkGPT — Video Intelligence")
st.write("Extract insights from any YouTube video in seconds.")

st.markdown('<div class="stCard">', unsafe_allow_html=True)
raw_input_url = st.text_input("🔗 Paste YouTube Video Link", placeholder="https://youtube.com/watch?v=...")
video_url = clean_youtube_url(raw_input_url) if raw_input_url else ""
st.markdown('</div>', unsafe_allow_html=True)

if video_url:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="stCard">', unsafe_allow_html=True)
    user_query = st.text_area("💬 What do you want to know?", placeholder="Summarize / Key Takeaways...", height=150)
    
    if st.button("🚀 Analyze Video Intel"):
        if not st.session_state.user_data:
            st.error("Please Sign in with Google to use LinkGPT.")
        elif not user_query:
            st.warning("Query toh likho, bhai!")
        else:
            with st.spinner("🧠 Brainstorming with AI..."):
                transcript, error = get_transcript(video_url)
                if error: st.error(error)
                else:
                    res_box = st.empty()
                    full_res = ""
                    for chunk in get_ai_response(transcript, user_query):
                        if chunk.choices[0].delta.content:
                            full_res += chunk.choices[0].delta.content
                            res_box.markdown(full_res + "▌")
                    res_box.markdown(full_res)
                    
                    # History Save in Supabase
                    try:
                        supabase.table("video_chats").insert({
                            "user_email": u.get('email'),
                            "query": user_query,
                            "video_url": video_url
                        }).execute()
                    except: pass
    st.markdown('</div>', unsafe_allow_html=True)
