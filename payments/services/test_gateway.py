from __future__ import annotations

from typing import Any, Dict

from django.db import transaction

from dashboard.models import Facture
from payments.models import PaymentAttempt, PaymentStatus, PaymentEvent
from payments.services.base import BasePaymentGateway


class TestPaymentGateway(BasePaymentGateway):
    provider_code = "CMI_TEST"

    def create_payment(self, facture: Facture) -> PaymentAttempt:
        with transaction.atomic():
            payment = PaymentAttempt.objects.create(
                facture=facture,
                provider=self.provider_code,
                merchant_txn_id=PaymentAttempt.generate_txn_id(),
                amount=facture.total_ttc,
                currency="MAD",
                status=PaymentStatus.PENDING,
            )
            PaymentEvent.objects.create(payment=payment, event_type="created", payload={"facture": facture.id})
            return payment

    def get_redirect_context(self, payment: PaymentAttempt) -> Dict[str, Any]:
        return {
            "payment": payment,
            "facture": payment.facture,
            "montant": payment.amount,
        }

    def process_result(self, payment: PaymentAttempt, result: str) -> PaymentAttempt:
        with transaction.atomic():
            if result == "success":
                payment.mark_success()
                PaymentEvent.objects.create(payment=payment, event_type="success", payload={"result": result})
            elif result == "fail":
                payment.mark_failed()
                PaymentEvent.objects.create(payment=payment, event_type="failed", payload={"result": result})
            elif result == "cancel":
                payment.mark_canceled()
                PaymentEvent.objects.create(payment=payment, event_type="canceled", payload={"result": result})
            else:
                PaymentEvent.objects.create(payment=payment, event_type="unknown_result", payload={"result": result})
            return payment
