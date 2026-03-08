from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import ListView, CreateView, UpdateView
from django.utils import timezone
from io import BytesIO

from .models import (
    Client, ClientStatut,
    Prospect, ProspectStatut, ProspectSource,
    Facture, FactureStatut, LigneFacture,
)
from .forms import ClientForm, ProspectForm, FactureForm, LigneFactureFormSet
from .services import compute_invoice_totals


# ── DASHBOARD ──────────────────────────────────────────────────────────────────

@login_required
def home(request):
    total_clients   = Client.objects.filter(statut=ClientStatut.ACTIF).count()
    total_prospects = Prospect.objects.exclude(
        statut__in=[ProspectStatut.GAGNE, ProspectStatut.PERDU]
    ).count()
    encours = (
        Facture.objects
        .filter(statut__in=[FactureStatut.ENVOYEE, FactureStatut.EN_RETARD])
        .aggregate(total=Sum('montant_ht'))['total'] or 0
    )
    retard_count = Facture.objects.filter(statut=FactureStatut.EN_RETARD).count()

    dernieres_factures  = Facture.objects.select_related('client').order_by('-created_at')[:6]
    factures_en_retard  = Facture.objects.select_related('client').filter(
        statut=FactureStatut.EN_RETARD
    )[:5]

    # Statuts pour le graphique
    payees     = Facture.objects.filter(statut=FactureStatut.PAYEE).count()
    retard     = retard_count
    impayees   = Facture.objects.filter(statut__in=[
        FactureStatut.ENVOYEE, FactureStatut.BROUILLON
    ]).count()
    total_fact = payees + retard + impayees
    def pct(part, total):
        return round((part / total) * 100) if total else 0

    context = {
        'total_clients':      total_clients,
        'total_prospects':    total_prospects,
        'encours':            encours,
        'retard_count':       retard_count,
        'dernieres_factures': dernieres_factures,
        'factures_en_retard': factures_en_retard,
        'factures_payees':    payees,
        'factures_impayees':  impayees,
        'factures_retard':    retard,
        'factures_total':     total_fact,
        'factures_pct_payees':   pct(payees, total_fact),
        'factures_pct_impayees': pct(impayees, total_fact),
        'factures_pct_retard':   pct(retard, total_fact),
    }

    return render(request, 'dashboard/home.html', context)


# ── CLIENTS ─────────────────────────────────────────────────────────────────────

class ClientListView(LoginRequiredMixin, ListView):
    model               = Client
    template_name       = 'dashboard/clients/list.html'
    context_object_name = 'clients'
    paginate_by         = 20

    def get_queryset(self):
        qs = super().get_queryset()
        q      = self.request.GET.get('q', '').strip()
        statut = self.request.GET.get('statut', '')
        if q:
            qs = qs.filter(
                Q(nom__icontains=q) | Q(prenom__icontains=q) |
                Q(societe__icontains=q) | Q(email__icontains=q)
            )
        if statut:
            qs = qs.filter(statut=statut)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts']         = ClientStatut.choices
        ctx['current_q']       = self.request.GET.get('q', '')
        ctx['current_statut']  = self.request.GET.get('statut', '')
        return ctx


@login_required
def client_detail(request, pk):
    client  = get_object_or_404(Client, pk=pk)
    factures = client.factures.order_by('-date_emission')[:10]
    return render(request, 'dashboard/clients/detail.html', {
        'client': client, 'factures': factures
    })


class ClientCreateView(LoginRequiredMixin, CreateView):
    model         = Client
    form_class    = ClientForm
    template_name = 'dashboard/clients/form.html'
    success_url   = reverse_lazy('dashboard:client_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Client créé avec succès.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action']       = 'Nouveau client'
        ctx['submit_label'] = 'Créer le client'
        return ctx


class ClientUpdateView(LoginRequiredMixin, UpdateView):
    model         = Client
    form_class    = ClientForm
    template_name = 'dashboard/clients/form.html'
    success_url   = reverse_lazy('dashboard:client_list')

    def form_valid(self, form):
        messages.success(self.request, 'Client mis à jour.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action']       = f"Modifier — {self.object}"
        ctx['submit_label'] = 'Enregistrer les modifications'
        return ctx


# ── PROSPECTS ─────────────────────────────────────────────────────────────────

class ProspectListView(LoginRequiredMixin, ListView):
    model               = Prospect
    template_name       = 'dashboard/prospects/list.html'
    context_object_name = 'prospects'
    paginate_by         = 20

    def get_queryset(self):
        qs     = super().get_queryset()
        q      = self.request.GET.get('q', '').strip()
        statut = self.request.GET.get('statut', '')
        source = self.request.GET.get('source', '')
        if q:
            qs = qs.filter(
                Q(nom__icontains=q) | Q(prenom__icontains=q) |
                Q(societe__icontains=q) | Q(email__icontains=q)
            )
        if statut:
            qs = qs.filter(statut=statut)
        if source:
            qs = qs.filter(source=source)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts']         = ProspectStatut.choices
        ctx['sources']         = ProspectSource.choices
        ctx['current_q']       = self.request.GET.get('q', '')
        ctx['current_statut']  = self.request.GET.get('statut', '')
        ctx['current_source']  = self.request.GET.get('source', '')
        # Kanban columns (one DB fetch, then Python grouping)
        all_p = list(Prospect.objects.all())
        by_statut = {}
        for p in all_p:
            by_statut.setdefault(p.statut, []).append(p)
        ctx['kanban_colonnes'] = [
            {'statut': s[0], 'label': s[1], 'items': by_statut.get(s[0], [])}
            for s in ProspectStatut.choices
        ]
        return ctx


class ProspectCreateView(LoginRequiredMixin, CreateView):
    model         = Prospect
    form_class    = ProspectForm
    template_name = 'dashboard/prospects/form.html'
    success_url   = reverse_lazy('dashboard:prospect_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Prospect créé avec succès.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action']       = 'Nouveau prospect'
        ctx['submit_label'] = 'Créer le prospect'
        return ctx


class ProspectUpdateView(LoginRequiredMixin, UpdateView):
    model         = Prospect
    form_class    = ProspectForm
    template_name = 'dashboard/prospects/form.html'
    success_url   = reverse_lazy('dashboard:prospect_list')

    def form_valid(self, form):
        messages.success(self.request, 'Prospect mis à jour.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action']       = f"Modifier — {self.object}"
        ctx['submit_label'] = 'Enregistrer les modifications'
        return ctx


# ── FACTURES ──────────────────────────────────────────────────────────────────

class FactureListView(LoginRequiredMixin, ListView):
    model               = Facture
    template_name       = 'dashboard/factures/list.html'
    context_object_name = 'factures'
    paginate_by         = 20

    def get_queryset(self):
        qs     = super().get_queryset().select_related('client')
        statut = self.request.GET.get('statut', '')
        q      = self.request.GET.get('q', '').strip()
        if statut:
            qs = qs.filter(statut=statut)
        if q:
            qs = qs.filter(
                Q(numero__icontains=q) | Q(objet__icontains=q) |
                Q(client__nom__icontains=q) | Q(client__societe__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts']        = FactureStatut.choices
        ctx['current_statut'] = self.request.GET.get('statut', '')
        ctx['current_q']      = self.request.GET.get('q', '')
        agg = Facture.objects.aggregate(
            encours=Sum('montant_ht',
                filter=Q(statut__in=[FactureStatut.ENVOYEE, FactureStatut.EN_RETARD])),
            paye=Sum('montant_ht', filter=Q(statut=FactureStatut.PAYEE)),
            retard=Sum('montant_ht', filter=Q(statut=FactureStatut.EN_RETARD)),
        )
        ctx['encours_total'] = agg['encours'] or 0
        ctx['paye_total']    = agg['paye']    or 0
        ctx['retard_total']  = agg['retard']  or 0
        return ctx


@login_required
def facture_detail(request, pk):
    facture = get_object_or_404(Facture.objects.select_related('client'), pk=pk)
    lignes  = facture.lignes.all()
    return render(request, 'dashboard/factures/detail.html', {
        'facture': facture, 'lignes': lignes
    })


@login_required
def facture_create(request):
    form    = FactureForm(request.POST or None)
    formset = LigneFactureFormSet(request.POST or None)
    if request.method == 'POST':
        if form.is_valid() and formset.is_valid():
            facture = form.save(commit=False)
            facture.created_by = request.user
            facture.save()
            formset.instance = facture
            formset.save()
            facture.recompute_totals(save=True)
            messages.success(request, f'Facture {facture.numero} créée avec succès.')
            return redirect('dashboard:facture_list')
        else:
            # Debug minimal : log les erreurs côté serveur
            print("FACTURE CREATE INVALID FORM =>", form.errors.as_json(), formset.errors)
    return render(request, 'dashboard/factures/form.html', {
        'form': form, 'lignes_formset': formset,
        'action': 'Nouvelle facture', 'submit_label': 'Créer la facture',
    })


@login_required
def facture_update(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    form    = FactureForm(request.POST or None, instance=facture)
    formset = LigneFactureFormSet(request.POST or None, instance=facture)
    if request.method == 'POST':
        if form.is_valid() and formset.is_valid():
            facture = form.save()
            formset.save()
            facture.recompute_totals(save=True)
            messages.success(request, 'Facture mise à jour.')
            return redirect('dashboard:facture_list')
    return render(request, 'dashboard/factures/form.html', {
        'form': form, 'lignes_formset': formset,
        'action': f'Modifier — {facture.numero}',
        'submit_label': 'Enregistrer les modifications',
        'facture': facture,
    })


# PDF facture (xhtml2pdf pour éviter les dépendances GTK)
@login_required
def facture_pdf(request, pk):
    from xhtml2pdf import pisa

    facture = get_object_or_404(Facture.objects.select_related('client'), pk=pk)
    facture = compute_invoice_totals(facture)
    lignes  = facture.lignes.filter(item_type='NORMAL')
    debours = facture.lignes.filter(item_type='DEBOURS')

    context = {
        "facture": facture,
        "client": facture.client,
        "lignes": lignes,
        "debours": debours,
        "today": timezone.now().date(),
    }

    html = render_to_string("invoices/invoice_pdf.html", context)
    result = BytesIO()
    pdf = pisa.CreatePDF(src=html, dest=result, encoding="utf-8")
    if pdf.err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)

    response = HttpResponse(result.getvalue(), content_type="application/pdf")
    filename = f"facture-{facture.numero}.pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
