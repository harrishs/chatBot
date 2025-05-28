from decouple import config
from cryptography.fernet import Fernet

ENCRYPTION_KEY = config('ENCRYPTION_KEY')
fernet = Fernet(ENCRYPTION_KEY)