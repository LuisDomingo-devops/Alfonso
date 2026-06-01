import os

DEFAULT_SERVER = os.getenv("ALFONSO_SERVER", "http://localhost:8000")
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", "3"))
ORDER_SECONDS = int(os.getenv("ORDER_SECONDS", "10"))
SILENCE_THRESHOLD = int(os.getenv("SILENCE_THRESHOLD", "500"))
MAX_SILENCE_SECONDS = 1.6
MAX_SILENCE_CHUNKS = 3
WAKE_WORD_RETRIES = 3
EXIT_WORDS = {
    "adiós", "adios", "hasta luego", "para", "stop", 
    "salir", "bye", "terminar"
}