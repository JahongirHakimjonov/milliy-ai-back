from django.db import models


class WSAction(models.TextChoices):
    GENERATE_FILE = "generate_file", "Generate File"


class FileFormat(models.TextChoices):
    PDF = "pdf", "PDF"
    DOCX = "docx", "DOCX"
