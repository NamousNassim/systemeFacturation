from django.contrib import admin
from .models import Client, Prospect, Facture, LigneFacture


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display  = ['nom', 'prenom', 'societe', 'email', 'telephone', 'statut', 'created_at']
    list_filter   = ['statut', 'created_at']
    search_fields = ['nom', 'prenom', 'email', 'societe', 'siret']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Identité', {'fields': ('nom', 'prenom', 'societe', 'siret')}),
        ('Contact',  {'fields': ('email', 'telephone', 'adresse')}),
        ('Gestion',  {'fields': ('statut', 'notes', 'created_by')}),
        ('Dates',    {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(Prospect)
class ProspectAdmin(admin.ModelAdmin):
    list_display  = ['nom', 'prenom', 'societe', 'email', 'statut', 'source',
                     'date_dernier_contact', 'created_at']
    list_filter   = ['statut', 'source', 'created_at']
    search_fields = ['nom', 'prenom', 'email', 'societe']
    readonly_fields = ['created_at', 'updated_at']


class LigneFactureInline(admin.TabularInline):
    model  = LigneFacture
    extra  = 1
    fields = ['description', 'quantite', 'prix_unitaire', 'item_type']


@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    list_display    = ['numero', 'client', 'objet', 'subtotal_ht', 'tva_amount', 'total_ttc',
                       'statut', 'date_emission', 'date_echeance']
    list_filter     = ['statut', 'date_emission']
    search_fields   = ['numero', 'objet', 'client__nom', 'client__societe']
    readonly_fields = ['numero', 'created_at', 'updated_at', 'subtotal_ht', 'tva_amount', 'total_ttc']
    inlines         = [LigneFactureInline]

