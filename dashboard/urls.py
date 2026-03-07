from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    # Dashboard
    path("", views.home, name="home"),

    # Clients
    path("clients/",                  views.ClientListView.as_view(),  name="client_list"),
    path("clients/ajouter/",          views.ClientCreateView.as_view(), name="client_create"),
    path("clients/<int:pk>/",         views.client_detail,             name="client_detail"),
    path("clients/<int:pk>/modifier/",views.ClientUpdateView.as_view(), name="client_update"),

    # Prospects
    path("prospects/",                   views.ProspectListView.as_view(),   name="prospect_list"),
    path("prospects/ajouter/",           views.ProspectCreateView.as_view(), name="prospect_create"),
    path("prospects/<int:pk>/modifier/", views.ProspectUpdateView.as_view(), name="prospect_update"),

    # Factures
    path("factures/",                   views.FactureListView.as_view(), name="facture_list"),
    path("factures/creer/",             views.facture_create,            name="facture_create"),
    path("factures/<int:pk>/",          views.facture_detail,            name="facture_detail"),
    path("factures/<int:pk>/modifier/", views.facture_update,            name="facture_update"),
    path("factures/<int:pk>/pdf/",      views.facture_pdf,               name="facture_pdf"),
]
