from django.db import models


class WSType(models.TextChoices):
    AI_CHUNK = "ai_chunk", "AI Chunk"
    AI_START = "ai_start", "AI Start"
    AI_END = "ai_end", "AI End"
    AI_FILE = "ai_file", "AI File"
    ERROR = "error", "Error"
