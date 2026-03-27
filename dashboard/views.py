import base64
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from xml.sax.saxutils import escape
import zipfile

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.template.loader import render_to_string
from django.views.generic import ListView, CreateView, UpdateView
from django.utils import timezone
from io import BytesIO
from django.conf import settings
from django.core.paginator import Paginator

from .models import (
    Client, ClientStatut,
    Prospect, ProspectStatut, ProspectSource,
    Facture, FactureStatut, LigneFacture, FactureEmailLog,
)
from .forms import ClientForm, ProspectForm, FactureForm, LigneFactureFormSet
from .services import build_invoice_pdf_context, compute_invoice_totals, send_invoice_email
from accounts.forms import EmployeeCreateForm
from accounts.models import UserRole


def _can_manage_deletion(user):
    return user.is_superuser or getattr(user, "role", "") in [UserRole.ADMIN, UserRole.RECOVEREMENT]


def _can_edit_invoice(user):
    """Autorise uniquement Admin ou Recouvrement à modifier une facture."""
    return user.is_superuser or getattr(user, "role", "") in [UserRole.ADMIN, UserRole.RECOVEREMENT]


def _quantize(value: Decimal) -> Decimal:
    """Arrondit au centime avec HALF_UP pour rester cohérent avec les totaux PDF."""
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _next_facture_numero():
    """Calcule le prochain numéro de facture sans créer d'objet."""
    year = timezone.now().year
    base_seq = 288 if year == 2026 else 1
    last = Facture.objects.filter(numero__startswith=f"FAC-{year}-").order_by('numero').last()
    if last:
        try:
            seq = int(last.numero.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = base_seq
    else:
        seq = base_seq
    if seq < base_seq:
        seq = base_seq
    return f"FAC-{year}-{seq:04d}"


def _build_preview_pdf(form, formset):
    """
    Génère un PDF en mémoire à partir des données du formulaire sans rien persister.
    Retourne la base64 à injecter dans une iframe data:application/pdf.
    """
    try:
        from xhtml2pdf import pisa
    except Exception:
        return None

    facture = form.save(commit=False)
    facture.numero = facture.numero or "PRÉVISUALISATION"
    facture.subtotal_ht = Decimal('0.00')
    taxable_subtotal = Decimal('0.00')

    lignes_normales = []
    lignes_debours = []

    for lf in formset:
        data = getattr(lf, "cleaned_data", {}) or {}
        if not data or data.get("DELETE"):
            continue
        desc = data.get("description") or ""
        qty = Decimal(str(data.get("quantite") or 0))
        pu = Decimal(str(data.get("prix_unitaire") or 0))
        item_type = data.get("item_type") or "NORMAL"
        hors_taxe = bool(data.get("hors_taxe"))
        total_ht = _quantize(qty * pu)
        ligne_obj = SimpleNamespace(
            description=desc,
            quantite=qty,
            prix_unitaire=pu,
            total_ht=total_ht,
        )
        if item_type == "DEBOURS":
            lignes_debours.append(ligne_obj)
        else:
            lignes_normales.append(ligne_obj)
        facture.subtotal_ht += total_ht
        if not hors_taxe:
            taxable_subtotal += total_ht

    facture.montant_ht = facture.subtotal_ht
    facture.tva_amount = _quantize(taxable_subtotal * (facture.tva_rate / Decimal('100')))
    facture.total_ttc = _quantize(facture.subtotal_ht + facture.tva_amount)

    context = build_invoice_pdf_context(facture, lignes_normales, lignes_debours)

    html = render_to_string("invoices/invoice_pdf.html", context)
    result = BytesIO()
    pdf = pisa.CreatePDF(src=html, dest=result, encoding="utf-8")
    if pdf.err:
        return None
    return base64.b64encode(result.getvalue()).decode("ascii")


def _filtered_clients_queryset(request):
    qs = Client.objects.all()
    q = request.GET.get('q', '').strip()
    statut = request.GET.get('statut', '')
    no_invoice = request.GET.get('no_invoice') == '1'

    if q:
        qs = qs.filter(
            Q(nom__icontains=q) | Q(prenom__icontains=q) |
            Q(societe__icontains=q) | Q(email__icontains=q)
        )
    if statut:
        qs = qs.filter(statut=statut)
    if no_invoice:
        qs = qs.annotate(facture_count=Count('factures')).filter(facture_count=0)
    return qs


def _filtered_factures_queryset(request):
    qs = Facture.objects.select_related('client')
    statut = request.GET.get('statut', '')
    q = request.GET.get('q', '').strip()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    client_id = request.GET.get('client', '')

    if statut:
        qs = qs.filter(statut=statut)
    if q:
        qs = qs.filter(
            Q(numero__icontains=q) | Q(objet__icontains=q) |
            Q(client__nom__icontains=q) | Q(client__societe__icontains=q)
        )
    if date_from:
        qs = qs.filter(date_emission__gte=date_from)
    if date_to:
        qs = qs.filter(date_emission__lte=date_to)
    if client_id:
        qs = qs.filter(client_id=client_id)
    return qs


def _xlsx_column_name(index):
    name = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xlsx_text(value):
    if value is None:
        return ""
    text = str(value)
    return "".join(
        ch for ch in text
        if ch in "\t\n\r" or ord(ch) >= 32
    )


def _xlsx_inline_cell(cell_ref, value, style_id):
    text = escape(_xlsx_text(value))
    return (
        f'<c r="{cell_ref}" s="{style_id}" t="inlineStr">'
        f'<is><t xml:space="preserve">{text}</t></is>'
        f'</c>'
    )


def _build_clients_xlsx(clients):
    columns = [
        ("Nom", 18),
        ("Prenom", 18),
        ("Societe", 24),
        ("Email", 28),
        ("Telephone", 18),
        ("RC", 16),
        ("ICE", 18),
        ("Statut", 14),
        ("Adresse", 34),
        ("Notes", 34),
        ("Cree le", 16),
    ]
    clients = list(clients)
    last_column = _xlsx_column_name(len(columns))
    last_row = len(clients) + 1

    rows_xml = [
        '<row r="1" ht="24" customHeight="1">'
        + "".join(
            _xlsx_inline_cell(f"{_xlsx_column_name(index)}1", header, 1)
            for index, (header, _width) in enumerate(columns, start=1)
        )
        + '</row>'
    ]

    for row_number, client in enumerate(clients, start=2):
        values = [
            client.nom,
            client.prenom,
            client.societe,
            client.email,
            client.telephone,
            client.siret,
            client.ice,
            client.get_statut_display(),
            client.adresse,
            client.notes,
            client.created_at.strftime("%d/%m/%Y"),
        ]
        cells = []
        for column_index, value in enumerate(values, start=1):
            cell_ref = f"{_xlsx_column_name(column_index)}{row_number}"
            style_id = 3 if column_index in (9, 10) else 2
            cells.append(_xlsx_inline_cell(cell_ref, value, style_id))
        rows_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    cols_xml = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, (_header, width) in enumerate(columns, start=1)
    )

    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:{last_column}{last_row}"/>
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>{cols_xml}</cols>
  <sheetData>{"".join(rows_xml)}</sheetData>
  <autoFilter ref="A1:{last_column}{last_row}"/>
  <pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>'''

    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1D4ED8"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFD1D5DB"/></left>
      <right style="thin"><color rgb="FFD1D5DB"/></right>
      <top style="thin"><color rgb="FFD1D5DB"/></top>
      <bottom style="thin"><color rgb="FFD1D5DB"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center"/>
    </xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1">
      <alignment vertical="top"/>
    </xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1">
      <alignment vertical="top" wrapText="1"/>
    </xf>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>'''

    timestamp = timezone.now().isoformat()
    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Clients" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>'''
    workbook_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    root_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''
    content_types_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''
    app_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft Excel</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>1</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="1" baseType="lpstr">
      <vt:lpstr>Clients</vt:lpstr>
    </vt:vector>
  </TitlesOfParts>
  <Company></Company>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>16.0300</AppVersion>
</Properties>'''
    core_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Export clients</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>
</cp:coreProperties>'''

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def _build_factures_xlsx(factures):
    columns = [
        ("Numero de facture", 20),
        ("Client", 26),
        ("Societe", 24),
        ("Objet", 32),
        ("Montant HT", 14),
        ("TVA", 12),
        ("Total TTC", 14),
        ("Statut", 14),
        ("Type", 18),
        ("Date emission", 16),
        ("Date echeance", 16),
        ("Email client", 28),
    ]
    factures = list(factures)
    last_column = _xlsx_column_name(len(columns))
    last_row = len(factures) + 1

    rows_xml = [
        '<row r="1" ht="24" customHeight="1">'
        + "".join(
            _xlsx_inline_cell(f"{_xlsx_column_name(index)}1", header, 1)
            for index, (header, _width) in enumerate(columns, start=1)
        )
        + '</row>'
    ]

    for row_number, facture in enumerate(factures, start=2):
        client_name = f"{facture.client.nom} {facture.client.prenom}".strip()
        values = [
            facture.numero,
            client_name,
            facture.client.societe,
            facture.objet,
            f"{facture.montant_ht:.2f}",
            f"{facture.tva_amount:.2f}",
            f"{facture.total_ttc:.2f}",
            facture.get_statut_display(),
            facture.get_type_facture_display(),
            facture.date_emission.strftime("%d/%m/%Y") if facture.date_emission else "",
            facture.date_echeance.strftime("%d/%m/%Y") if facture.date_echeance else "",
            facture.client.email,
        ]
        cells = []
        for column_index, value in enumerate(values, start=1):
            cell_ref = f"{_xlsx_column_name(column_index)}{row_number}"
            style_id = 3 if column_index == 4 else 2
            cells.append(_xlsx_inline_cell(cell_ref, value, style_id))
        rows_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    cols_xml = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, (_header, width) in enumerate(columns, start=1)
    )

    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:{last_column}{last_row}"/>
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>{cols_xml}</cols>
  <sheetData>{"".join(rows_xml)}</sheetData>
  <autoFilter ref="A1:{last_column}{last_row}"/>
  <pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>'''

    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1D4ED8"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFD1D5DB"/></left>
      <right style="thin"><color rgb="FFD1D5DB"/></right>
      <top style="thin"><color rgb="FFD1D5DB"/></top>
      <bottom style="thin"><color rgb="FFD1D5DB"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center"/>
    </xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1">
      <alignment vertical="top"/>
    </xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1">
      <alignment vertical="top" wrapText="1"/>
    </xf>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>'''

    timestamp = timezone.now().isoformat()
    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Factures" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>'''
    workbook_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    root_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''
    content_types_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''
    app_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft Excel</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>1</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="1" baseType="lpstr">
      <vt:lpstr>Factures</vt:lpstr>
    </vt:vector>
  </TitlesOfParts>
  <Company></Company>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>16.0300</AppVersion>
</Properties>'''
    core_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Export factures</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>
</cp:coreProperties>'''

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


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
        return _filtered_clients_queryset(self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts']         = ClientStatut.choices
        ctx['current_q']       = self.request.GET.get('q', '')
        ctx['current_statut']  = self.request.GET.get('statut', '')
        ctx['current_no_invoice'] = self.request.GET.get('no_invoice', '') == '1'
        return ctx


@login_required
def client_detail(request, pk):
    client  = get_object_or_404(Client, pk=pk)
    factures = client.factures.order_by('-date_emission')[:10]
    return render(request, 'dashboard/clients/detail.html', {
        'client': client, 'factures': factures
    })


@login_required
def client_export_xlsx(request):
    clients = _filtered_clients_queryset(request)
    workbook = _build_clients_xlsx(clients)
    response = HttpResponse(
        workbook,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"clients-{timezone.localdate().isoformat()}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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
        return _filtered_factures_queryset(self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts']        = FactureStatut.choices
        ctx['current_statut'] = self.request.GET.get('statut', '')
        ctx['current_q']      = self.request.GET.get('q', '')
        ctx['current_date_from'] = self.request.GET.get('date_from', '')
        ctx['current_date_to']   = self.request.GET.get('date_to', '')
        ctx['current_client'] = self.request.GET.get('client', '')
        ctx['clients_filter'] = Client.objects.order_by('societe', 'nom')
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
def facture_export_xlsx(request):
    factures = _filtered_factures_queryset(request)
    workbook = _build_factures_xlsx(factures)
    response = HttpResponse(
        workbook,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"factures-{timezone.localdate().isoformat()}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def facture_detail(request, pk):
    facture = get_object_or_404(Facture.objects.select_related('client'), pk=pk)
    lignes  = facture.lignes.all()
    logs    = facture.email_logs.all()
    return render(request, 'dashboard/factures/detail.html', {
        'facture': facture, 'lignes': lignes, 'email_logs': logs
    })


@login_required
def facture_create(request):
    action  = request.POST.get("action")
    form    = FactureForm(request.POST or None)
    formset = LigneFactureFormSet(request.POST or None)
    preview_pdf = None
    next_numero = _next_facture_numero()
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if request.method == 'POST':
        if form.is_valid() and formset.is_valid():
            if is_ajax and action == "preview":
                preview_pdf = _build_preview_pdf(form, formset)
                if not preview_pdf:
                    return JsonResponse(
                        {"success": False, "message": "La prévisualisation PDF n'a pas pu être générée."},
                        status=500,
                    )
                return JsonResponse({"success": True, "pdf": preview_pdf})

            if action == "confirm":
                facture = form.save(commit=False)
                facture.created_by = request.user
                facture.save()
                formset.instance = facture
                formset.save()
                facture.recompute_totals(save=True)
                # Envoi seulement si statut est ENVOYEE et email client présent
                if facture.statut == FactureStatut.ENVOYEE and facture.client.email:
                    success, err = send_invoice_email(
                        facture,
                        admin_email=getattr(settings, "INVOICE_ADMIN_EMAIL", None),
                    )
                    if success:
                        messages.success(request, f'Facture {facture.numero} créée et envoyée à {facture.client.email}.')
                    else:
                        messages.warning(request, f'Facture {facture.numero} créée, mais envoi email échoué ({err or "non précisé"}).')
                else:
                    messages.success(request, f'Facture {facture.numero} créée (non envoyée : statut {facture.get_statut_display()}).')
                return redirect('dashboard:facture_list')
            elif action == "edit":
                preview_pdf = None
            else:
                preview_pdf = _build_preview_pdf(form, formset)
                if preview_pdf:
                    messages.info(request, "Vérifiez le PDF de prévisualisation ci-dessous puis confirmez l'envoi.")
                else:
                    messages.error(request, "La prévisualisation PDF n'a pas pu être générée.")
        else:
            # Debug minimal : log les erreurs côté serveur
            print("FACTURE CREATE INVALID FORM =>", form.errors.as_json(), formset.errors)
            if is_ajax and action == "preview":
                return JsonResponse(
                    {
                        "success": False,
                        "errors": form.errors,
                        "formset_errors": formset.errors,
                    },
                    status=400,
                )
    return render(request, 'dashboard/factures/form.html', {
        'form': form, 'lignes_formset': formset,
        'action': 'Nouvelle facture', 'submit_label': 'Créer la facture',
        'preview_pdf': preview_pdf,
        'preview_mode': bool(preview_pdf),
        'next_numero': next_numero,
    })


@login_required
def facture_update(request, pk):
    if not _can_edit_invoice(request.user):
        return HttpResponseForbidden("Modification réservée à l'administrateur et au recouvrement.")

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
    lignes = list(facture.lignes.filter(item_type='NORMAL'))
    debours = list(facture.lignes.filter(item_type='DEBOURS'))
    context = build_invoice_pdf_context(facture, lignes, debours)

    html = render_to_string("invoices/invoice_pdf.html", context)
    result = BytesIO()
    pdf = pisa.CreatePDF(src=html, dest=result, encoding="utf-8")
    if pdf.err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)

    response = HttpResponse(result.getvalue(), content_type="application/pdf")
    filename = f"facture-{facture.numero}.pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@login_required
def facture_resend(request, pk):
    facture = get_object_or_404(Facture.objects.select_related('client'), pk=pk)
    if facture.statut != FactureStatut.ENVOYEE:
        messages.warning(request, "La facture doit être au statut 'Envoyée' pour être renvoyée.")
        return redirect('dashboard:facture_detail', pk=pk)
    if not facture.client.email:
        messages.error(request, "Aucune adresse email client n'est renseignée.")
        return redirect('dashboard:facture_detail', pk=pk)

    success, err = send_invoice_email(
        facture,
        admin_email=getattr(settings, "INVOICE_ADMIN_EMAIL", None),
    )
    if success:
        messages.success(request, f"Facture {facture.numero} renvoyée à {facture.client.email}.")
    else:
        messages.error(request, f"Échec d'envoi : {err or 'non précisé'}.")
    return redirect('dashboard:facture_detail', pk=pk)


# ——— Notifications / Historique envois ———
@login_required
def notifications(request):
    status = request.GET.get('status', '')
    logs = FactureEmailLog.objects.select_related('facture', 'facture__client').order_by('-sent_at')
    if status == 'success':
        logs = logs.filter(success=True)
    elif status == 'fail':
        logs = logs.filter(success=False)

    paginator = Paginator(logs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'dashboard/notifications/list.html', {
        'page_obj': page,
        'status_filter': status,
    })


# â€”â€”â€” Suppressions clients / factures (admin ou recouvrement) â€”â€”â€” #
@login_required
@require_POST
def client_delete(request, pk):
    if not _can_manage_deletion(request.user):
        return HttpResponseForbidden("Suppression réservée à l'administrateur et au recouvrement.")

    client = get_object_or_404(Client, pk=pk)
    try:
        client.delete()
        messages.success(request, f"Client « {client} » supprimé.")
    except ProtectedError:
        messages.error(request, "Impossible de supprimer ce client car des factures sont associées.")
    return redirect('dashboard:client_list')


@login_required
@require_POST
def facture_delete(request, pk):
    if not _can_manage_deletion(request.user):
        return HttpResponseForbidden("Suppression réservée à l'administrateur et au recouvrement.")

    facture = get_object_or_404(Facture, pk=pk)
    numero = facture.numero
    try:
        with transaction.atomic():
            # Supprime d'abord les paiements rattachés (et leurs événements en cascade)
            facture.paiements.all().delete()
            facture.delete()
        messages.success(request, f"Facture {numero} supprimée.")
    except ProtectedError:
        messages.error(
            request,
            "Impossible de supprimer cette facture : des paiements ou objets liés la protègent."
        )
    return redirect('dashboard:facture_list')


# ── Administration : création d'employés (superuser uniquement) ──────────────
@login_required
def employee_create(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Accès réservé à l'administrateur.")

    form = EmployeeCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        employee = form.save()
        display_name = employee.get_full_name() or employee.email
        messages.success(request, f"Employé {display_name} créé avec succès.")
        return redirect('dashboard:employee_create')

    return render(request, 'dashboard/employees/create.html', {
        'form': form,
    })
