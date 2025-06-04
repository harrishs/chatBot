from decouple import config
from cryptography.fernet import Fernet

ENCRYPTION_KEY = config('ENCRYPTION_KEY')
fernet = Fernet(ENCRYPTION_KEY)

def encrypt_api_key(api_key: str) -> str:
    """
    Encrypts the API key using the configured Fernet key.
    
    :param api_key: The raw API key to encrypt.
    :return: The encrypted API key as a string.
    """
    return fernet.encrypt(api_key.encode()).decode()

def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypts the API key using the configured Fernet key.
    
    :param encrypted_key: The encrypted API key to decrypt.
    :return: The decrypted API key as a string.
    """
    return fernet.decrypt(encrypted_key.encode()).decode()