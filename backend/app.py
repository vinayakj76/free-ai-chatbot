import os
import httpx
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Session, select
from dotenv import load_dotenv
from authlib.integrations.starlette_client import OAuth
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain.text_splitter import CharacterTextSplitter

# Local imports
from models import User, UserSettings, Chat, Message
import security

# --- CONFIGURATION ---
load_dotenv()
app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Setup (SQLite)
sqlite_url = f"sqlite:///data/sqlite_db/database.db"
os.makedirs("data/sqlite_db", exist_ok=True)
engine = SQLModel.create_engine(sqlite_url, echo=False)

def create_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

# OAuth Setup (Google Example)
oauth = OAuth()
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- RAG SETUP (ChromaDB) ---
# We initialize embeddings and vector store
os.makedirs("data/chroma_db", exist_ok=True)

def get_vector_store(api_key: str):
    """Creates a vector store instance with the user's API key"""
    embeddings = OpenAIEmbeddings(
        openai_api_key=api_key,
        openai_api_base="https://openrouter.ai/api/v1" # OpenRouter supports OpenAI SDK
    )
    return Chroma(
        persist_directory="data/chroma_db",
        embedding_function=embeddings
    )

# --- EVENTS ---
@app.on_event("startup")
def on_startup():
    create_db()

# --- AUTH ROUTES ---
@app.get("/auth/login/{provider}")
async def login(request: Request, provider: str):
    redirect_uri = request.url_for('auth_callback', provider=provider)
    return await oauth.create_client(provider).authorize_redirect(request, redirect_uri)

@app.get("/auth/callback/{provider}")
async def auth_callback(request: Request, provider: str, session: Session = Depends(get_session)):
    token = await oauth.create_client(provider).authorize_access_token(request)
    user_info = token.get('userinfo')
    
    # Fallback for GitHub if userinfo isn't standard
    if not user_info:
        resp = await oauth.github.get('user', token=token)
        user_info = resp.json()
        if not user_info.get('email'):
             emails_resp = await oauth.github.get('user/emails', token=token)
             for e in emails_resp.json():
                 if e['primary']: user_info['email'] = e['email']

    if not user_info or not user_info.get('email'):
        raise HTTPException(status_code=400, detail="Email not found")

    # DB Logic
    user = session.exec(select(User).where(User.email == user_info['email'])).first()
    if not user:
        user = User(email=user_info['email'], name=user_info.get('name'))
        session.add(user)
        session.commit()
        session.refresh(user)
        
        settings = UserSettings(user_id=user.id)
        session.add(settings)
        session.commit()

    response = RedirectResponse(url="/")
    response.set_cookie(key="session_email", value=user.email, httponly=True)
    return response

@app.get("/auth/me")
async def get_me(request: Request, session: Session = Depends(get_session)):
    email = request.cookies.get("session_email")
    if not email: raise HTTPException(status_code=401)
    
    user = session.exec(select(User).where(User.email == email)).first()
    settings = session.exec(select(UserSettings).where(UserSettings.user_id == user.id)).first()
    
    return {
        "id": user.id, "email": user.email, "name": user.name,
        "settings": {"model": settings.default_model, "has_key": bool(settings.openrouter_api_key_enc)}
    }

@app.post("/auth/logout")
async def logout():
    response = JSONResponse(content={"ok": True})
    response.delete_cookie("session_email")
    return response

# --- SETTINGS ROUTES ---
from pydantic import BaseModel

class SettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None

@app.post("/api/settings")
async def update_settings(data: SettingsUpdate, request: Request, session: Session = Depends(get_session)):
    email = request.cookies.get("session_email")
    if not email: raise HTTPException(status_code=401)
    
    user = session.exec(select(User).where(User.email == email)).first()
    settings = session.exec(select(UserSettings).where(UserSettings.user_id == user.id)).first()
    
    if data.api_key:
        settings.openrouter_api_key_enc = security.encrypt_value(data.api_key)
    if data.model:
        settings.default_model = data.model
    
    session.add(settings)
    session.commit()
    return {"status": "ok"}

# --- RAG: INGEST DATA ---
class IngestData(BaseModel):
    text: str

@app.post("/api/ingest")
async def ingest_data(data: IngestData, request: Request, session: Session = Depends(get_session)):
    email = request.cookies.get("session_email")
    if not email: raise HTTPException(status_code=401)
    
    user = session.exec(select(User).where(User.email == email)).first()
    settings = session.exec(select(UserSettings).where(UserSettings.user_id == user.id)).first()
    
    if not settings.openrouter_api_key_enc:
        raise HTTPException(status_code=400, detail="API Key not set")
    
    api_key = security.decrypt_value(settings.openrouter_api_key_enc)
    vector_store = get_vector_store(api_key)
    
    # Split and Store
    text_splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = text_splitter.split_text(data.text)
    vector_store.add_texts(chunks)
    
    return {"status": "Ingested", "chunks": len(chunks)}

# --- CHAT ROUTES ---
@app.get("/api/chats")
async def get_chats(request: Request, session: Session = Depends(get_session)):
    email = request.cookies.get("session_email")
    if not email: raise HTTPException(status_code=401)
    user = session.exec(select(User).where(User.email == email)).first()
    return session.exec(select(Chat).where(Chat.user_id == user.id)).all()

@app.post("/api/chat")
async def chat(request: Request, session: Session = Depends(get_session)):
    data = await request.json()
    user_msg_content = data.get("message")
    chat_id = data.get("chat_id")
    
    email = request.cookies.get("session_email")
    if not email: raise HTTPException(status_code=401)
    
    user = session.exec(select(User).where(User.email == email)).first()
    settings = session.exec(select(UserSettings).where(UserSettings.user_id == user.id)).first()
    
    if not settings.openrouter_api_key_enc:
        raise HTTPException(status_code=400, detail="API Key required")

    api_key = security.decrypt_value(settings.openrouter_api_key_enc)
    
    # 1. Manage Chat Session
    if not chat_id:
        new_chat = Chat(user_id=user.id, title=user_msg_content[:30])
        session.add(new_chat)
        session.commit()
        session.refresh(new_chat)
        chat_id = new_chat.id
        chat_obj = new_chat
    else:
        chat_obj = session.get(Chat, chat_id)

    # Save User Message
    session.add(Message(chat_id=chat_id, role="user", content=user_msg_content))
    session.commit()

    # 2. RAG: Retrieve Context
    vector_store = get_vector_store(api_key)
    docs = vector_store.similarity_search(user_msg_content, k=3)
    context_text = "\n".join([d.page_content for d in docs])

    # 3. Build Prompt for LLM
    # Get history
    history = session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.timestamp)).all()
    formatted_history = [{"role": m.role, "content": m.content} for m in history]
    
    # Inject RAG context into the last system prompt or modify the last user message
    # For simplicity, we'll inject it into the current user prompt sent to LLM
    rag_enhanced_message = f"Context:\n{context_text}\n\nUser Question: {user_msg_content}"
    
    # If using standard history, we replace the last user message content with RAG enhanced
    # But to keep it simple with LangChain/OpenAI SDK compatibility:
    
    llm = ChatOpenAI(
        model=settings.default_model, 
        openai_api_key=api_key,
        openai_api_base="https://openrouter.ai/api/v1"
    )
    
    # Simple chain call
    from langchain_core.prompts import ChatPromptTemplate
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant. Use the following context if helpful: {context}"),
        ("user", "{input}")
    ])
    
    chain = prompt | llm
    
    # We send the history separately or just the current context+question
    # To keep it compatible with memory, you might use LangChain Memory, but here is a manual way:
    
    response = await chain.ainvoke({
        "context": context_text, 
        "input": user_msg_content
        # Note: Passing full history requires constructing the prompt differently, 
        # but this demonstrates the RAG logic.
    })
    
    ai_content = response.content

    # 4. Save AI Response
    session.add(Message(chat_id=chat_id, role="assistant", content=ai_content))
    session.commit()

    return {"reply": ai_content, "chat_id": chat_id}

# --- SERVE FRONTEND ---
app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")