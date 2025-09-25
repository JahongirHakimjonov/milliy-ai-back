from django.db import models

from apps.shared.models.base import AbstractBaseModel


class Specialization(AbstractBaseModel):
    name = models.CharField(max_length=255)
    prompt = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to="specializations", blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Specialization"
        verbose_name_plural = "Specializations"
        ordering = ["-created_at"]
        db_table = "specializations"
