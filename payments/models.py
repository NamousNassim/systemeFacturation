from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from dashboard.models import Facture, FactureStatut


class PaymentStatus(models.TextChoices):
    CREATED = "CREATED", "Créé"
    PENDING = "PENDING", "En attente"
    SUCCESS = "SUCCESS", "Réussi"
    FAILED = "FAILED", "Échoué"
    CANCELED = "CANCELED", "Annulé"


class PaymentAttempt(models.Model):
    facture = models.ForeignKey(Facture, on_delete=models.PROTECT, related_name="paiements")
    provider = models.CharField(max_length=50, default="CMI_TEST")
    merchant_txn_id = models.CharField(max_length=64, unique=True, editable=False)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="MAD")
    status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.CREATED)
    request_payload = models.JSONField(blank=True, null=True)
    response_payload = models.JSONField(blank=True, null=True)
    signature_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    failed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Tentative de paiement"
        verbose_name_plural = "Tentatives de paiement"

    def __str__(self) -> str:
        return f"{self.merchant_txn_id} ({self.status})"

    @classmethod
    def generate_txn_id(cls) -> str:
        return uuid.uuid4().hex[:20].upper()

    def mark_success(self):
        self.status = PaymentStatus.SUCCESS
        self.paid_at = timezone.now()
        self.failed_at = None
        self.save(update_fields=["status", "paid_at", "failed_at", "updated_at"])
        self._mark_facture_paid()

    def mark_failed(self):
        self.status = PaymentStatus.FAILED
        self.failed_at = timezone.now()
        self.save(update_fields=["status", "failed_at", "updated_at"])

    def mark_canceled(self):
        self.status = PaymentStatus.CANCELED
        self.failed_at = timezone.now()
        self.save(update_fields=["status", "failed_at", "updated_at"])

    def _mark_facture_paid(self):
        # Utilise le statut existant pour marquer la facture payée
        if self.facture.statut != FactureStatut.PAYEE:
            self.facture.statut = FactureStatut.PAYEE
            self.facture.save(update_fields=["statut", "updated_at"])


class PaymentEvent(models.Model):
    payment = models.ForeignKey(PaymentAttempt, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=50)
    payload = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Événement de paiement"
        verbose_name_plural = "Événements de paiement"

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M:%S}"
