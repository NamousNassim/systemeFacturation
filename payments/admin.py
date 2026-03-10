from django.contrib import admin

from payments.models import PaymentAttempt, PaymentEvent


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "merchant_txn_id",
        "facture",
        "provider",
        "amount",
        "currency",
        "status",
        "created_at",
    )
    list_filter = ("provider", "status", "currency", "created_at")
    search_fields = ("merchant_txn_id", "facture__numero", "facture__client__nom", "facture__client__societe")
    autocomplete_fields = ("facture",)
    readonly_fields = ("created_at", "updated_at", "paid_at", "failed_at")


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "payment", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("payment__merchant_txn_id", "event_type")
    readonly_fields = ("created_at",)
