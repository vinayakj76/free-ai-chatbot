from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    name: Optional[str] = None
    picture: Optional[str] = None
    
    settings: Optional["UserSettings"] = Relationship(back_populates="user")
    chats: List["Chat"] = Relationship(back_populates="user")

class UserSettings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(foreign_key="user.id", unique=True)
    openrouter_api_key_enc: Optional[str] = None # Encrypted key
    default_model: str = "stepfun/step-3.5-flash:free"
    
    user: Optional[User] = Relationship(back_populates="settings")

class Chat(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(foreign_key="user.id")
    title: str = "New Chat"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: Optional[User] = Relationship(back_populates="chats")
    messages: List["Message"] = Relationship(back_populates="chat")

class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: Optional[int] = Field(foreign_key="chat.id")
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    chat: Optional[Chat] = Relationship(back_populates="messages")