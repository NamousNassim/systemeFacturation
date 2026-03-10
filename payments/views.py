from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from dashboard.models import Facture, FactureStatut
from payments.models import PaymentAttempt, PaymentStatus
from payments.services.test_gateway import TestPaymentGateway

gateway = TestPaymentGateway()


@login_required
def start_payment(request, facture_id: int):
    facture = get_object_or_404(Facture, pk=facture_id)

    if facture.statut == FactureStatut.PAYEE:
        messages.info(request, "Cette facture est déjà payée.")
        return redirect("dashboard:facture_detail", pk=facture_id)

    existing = PaymentAttempt.objects.filter(
        facture=facture, status__in=[PaymentStatus.CREATED, PaymentStatus.PENDING]
    ).first()
    if existing:
        payment = existing
    else:
        payment = gateway.create_payment(facture)

    return redirect("payments:test_payment", payment_id=payment.pk)


@login_required
def test_payment(request, payment_id: int):
    payment = get_object_or_404(PaymentAttempt.objects.select_related("facture"), pk=payment_id)
    context = gateway.get_redirect_context(payment)
    return render(request, "payments/test_payment.html", context)


@login_required
def process_result(request, payment_id: int, result: str):
    payment = get_object_or_404(PaymentAttempt, pk=payment_id)
    gateway.process_result(payment, result)
    return redirect("payments:payment_result", payment_id=payment.pk)


@login_required
def payment_result(request, payment_id: int):
    payment = get_object_or_404(PaymentAttempt.objects.select_related("facture"), pk=payment_id)
    return render(request, "payments/payment_result.html", {"payment": payment})
