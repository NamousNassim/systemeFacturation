from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from dashboard.models import Client as FactureClient, Facture, FactureStatut
from payments.models import PaymentAttempt, PaymentStatus


class PaymentFlowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="pass1234")
        self.client = Client()
        self.client.force_login(self.user)
        self.client_obj = FactureClient.objects.create(nom="Client Test")
        self.facture = Facture.objects.create(
            client=self.client_obj,
            objet="Test",
            montant_ht=Decimal("100.00"),
            subtotal_ht=Decimal("100.00"),
            tva_rate=Decimal("0.00"),
            tva_amount=Decimal("0.00"),
            total_ttc=Decimal("100.00"),
            statut=FactureStatut.ENVOYEE,
        )

    def test_create_payment_from_unpaid_facture(self):
        url = reverse("payments:start_payment", args=[self.facture.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        payment = PaymentAttempt.objects.first()
        self.assertEqual(payment.facture, self.facture)
        self.assertEqual(payment.status, PaymentStatus.PENDING)

    def test_success_payment_marks_facture_paid(self):
        self.client.get(reverse("payments:start_payment", args=[self.facture.pk]))
        payment = PaymentAttempt.objects.first()
        self.client.get(reverse("payments:payment_success", args=[payment.pk]))
        payment.refresh_from_db()
        self.facture.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(self.facture.statut, FactureStatut.PAYEE)

    def test_failed_payment_keeps_facture_unpaid(self):
        self.client.get(reverse("payments:start_payment", args=[self.facture.pk]))
        payment = PaymentAttempt.objects.first()
        self.client.get(reverse("payments:payment_fail", args=[payment.pk]))
        payment.refresh_from_db()
        self.facture.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)
        self.assertNotEqual(self.facture.statut, FactureStatut.PAYEE)

    def test_cancel_payment_keeps_facture_unpaid(self):
        self.client.get(reverse("payments:start_payment", args=[self.facture.pk]))
        payment = PaymentAttempt.objects.first()
        self.client.get(reverse("payments:payment_cancel", args=[payment.pk]))
        payment.refresh_from_db()
        self.facture.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.CANCELED)
        self.assertNotEqual(self.facture.statut, FactureStatut.PAYEE)

    def test_cannot_create_payment_for_paid_facture(self):
        self.facture.statut = FactureStatut.PAYEE
        self.facture.save()
        url = reverse("payments:start_payment", args=[self.facture.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(PaymentAttempt.objects.count(), 0)

    def test_reuse_pending_payment(self):
        url = reverse("payments:start_payment", args=[self.facture.pk])
        self.client.get(url)
        first = PaymentAttempt.objects.first()
        self.client.get(url)
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        self.assertEqual(PaymentAttempt.objects.first().pk, first.pk)
