from django.urls import path

from payments import views

app_name = "payments"

urlpatterns = [
    path("facture/<int:facture_id>/start/", views.start_payment, name="start_payment"),
    path("test/<int:payment_id>/", views.test_payment, name="test_payment"),
    path("test/<int:payment_id>/result/", views.payment_result, name="payment_result"),
    path("test/<int:payment_id>/success/", views.process_result, {"result": "success"}, name="payment_success"),
    path("test/<int:payment_id>/fail/", views.process_result, {"result": "fail"}, name="payment_fail"),
    path("test/<int:payment_id>/cancel/", views.process_result, {"result": "cancel"}, name="payment_cancel"),
]
