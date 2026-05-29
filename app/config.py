'''
App Configuration
 This file contains the configuration for the app, 
 including the database URI and other settings.
 
'''

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    '''
    App Settings
     This class defines the settings for the app, 
     including the database URI and other settings.
    '''
    OLLAMA_BASE_URL: str = 'http://localhost:11434'
    MODEL_NAME: str = 'qwen2.5:1.5b'

    CHAT_PROMPT_PATH: str
    TOOL_PROMPT_PATH: str

    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'

settings = Settings()   


def load_prompt(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")

