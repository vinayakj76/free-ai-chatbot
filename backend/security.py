from cryptography.fernet import Fernet
import os

# Generate a key once and save it in your .env file as ENCRYPTION_KEY
# Run this in python once: print(Fernet.generate_key().decode())
def get_encryption_key():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY not found in .env")
    return key.encode()

def encrypt_value(value: str) -> str:
    if not value: return ""
    f = Fernet(get_encryption_key())
    return f.encrypt(value.encode()).decode()

def decrypt_value(encrypted_value: str) -> str:
    if not encrypted_value: return ""
    f = Fernet(get_encryption_key())
    return f.decrypt(encrypted_value.encode()).decode()