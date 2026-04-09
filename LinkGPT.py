import streamlit as st
import re
import os
import yt_dlp
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from groq import Groq
from supabase import create_client, Client

# ----------------- 1. INITIALIZATION & SECRETS -----------------
st.set_page_config(page_title="LinkGPT — Video Intelligence", page_icon="🎬", layout="wide")

# Secrets Load
try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    
    client = Groq(api_key=GROQ_API_KEY)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Secrets missing! Please check Streamlit Cloud Dashboard.")
    st.stop()

# Session State
if "user" not in st.session_state:
    st.session_state.user = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# ----------------- 2. AUTHENTICATION LOGIC -----------------
def login_user(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.user = res.user
        st.success("Welcome back!")
        st.rerun()
    except Exception as e:
        st.error(f"Login Failed: {str(e)}")

def signup_user(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        st.info("Signup successful! Please check your email for confirmation (if enabled).")
    except Exception as e:
        st.error(f"Signup Failed: {str(e)}")

# ----------------- 3. CORE UTILS (WHISPER & TRANSCRIPT) -----------------
def extract_video_id(url: str) -> str:
    patterns = [r"(?:v=|\/)([0-9A-Za-z_-]{11})", r"youtu\.be\/([0-9A-Za-z_-]{11})"]
    for p in patterns:
        match = re.search(p, url)
        if match: return match.group(1)
    return None

def get_transcript(video_url):
    video_id = extract_video_id(video_url)
    if not video_id: return None, "Invalid URL"
    
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript(['en', 'hi']).fetch()
        return " ".join([t['text'] for t in transcript]), None
    except:
        return whisper_transcribe(video_url)

def whisper_transcribe(video_url):
    save_path = os.path.join(os.getcwd(), "temp_audio")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": save_path + ".%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
        "quiet": True, "noplaylist": True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        audio_file = "temp_audio.mp3"
        with open(audio_file, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(audio_file, f.read()),
                model="whisper-large-v3-turbo",
                response_format="text",
            )
        os.remove(audio_file)
        return transcription, None
    except Exception as e:
        return None, f"Deep Scan Error: {str(e)}"

# ----------------- 4. SIDEBAR & UI -----------------
st.markdown("""
    <style>
    .stCard { background: rgba(255, 255, 255, 0.05); border-radius: 16px; padding: 20px; border: 1px solid rgba(255, 255, 255, 0.1); }
    .chat-item { padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 14px; }
    </style>
    """, unsafe_allow_html=True)

with st.sidebar:
    if st.session_state.user:
        st.write(f"Logged in as: **{st.session_state.user.email}**")
        if st.button("Log Out"):
            st.session_state.user = None
            st.rerun()
        
        st.markdown("---")
        st.write("Recent Chats")
        # Fetch from Supabase History
        chats = supabase.table("video_chats").select("*").eq("user_email", st.session_state.user.email).order("created_at", desc=True).limit(5).execute()
        for c in chats.data:
            st.caption(f"📄 {c['query'][:30]}...")
    else:
        st.title("LinkGPT Access")
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        with tab1:
            e = st.text_input("Email", key="l_email")
            p = st.text_input("Password", type="password", key="l_pass")
            if st.button("Login"): login_user(e, p)
        with tab2:
            se = st.text_input("Email", key="s_email")
            sp = st.text_input("Password", type="password", key="s_pass")
            if st.button("Create Account"): signup_user(se, sp)

# ----------------- 5. MAIN PAGE -----------------
st.title("LinkGPT — Video Intelligence")

if not st.session_state.user:
    st.warning("Please login from the sidebar to start analyzing videos.")
    st.stop()

raw_url = st.text_input("🔗 Paste YouTube Link")
query = st.text_area("💬 What would you like to know?")

if st.button("Analyze Video"):
    if raw_url and query:
        with st.spinner("Processing..."):
            text, err = get_transcript(raw_url)
            if err:
                st.error(err)
            else:
                # Simple AI Call
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": f"Based on this: {text[:15000]}, answer: {query}"}]
                )
                ans = response.choices[0].message.content
                st.markdown(ans)
                
                # Save to History
                supabase.table("video_chats").insert({
                    "user_email": st.session_state.user.email,
                    "query": query,
                    "response": ans,
                    "video_url": raw_url
                }).execute()
                st.success("Analysis saved to history!")
    else:
        st.error("Bhai, dono fields fill karo!")
