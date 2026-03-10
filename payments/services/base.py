from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from dashboard.models import Facture
from payments.models import PaymentAttempt


class BasePaymentGateway(ABC):
    provider_code: str

    @abstractmethod
    def create_payment(self, facture: Facture) -> PaymentAttempt:
        ...

    @abstractmethod
    def get_redirect_context(self, payment: PaymentAttempt) -> Dict[str, Any]:
        ...

    @abstractmethod
    def process_result(self, payment: PaymentAttempt, result: str) -> PaymentAttempt:
        ...
