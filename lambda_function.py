"""
SupplierLens — International Supplier Risk Evaluator
------------------------------------------------------
Scores a supplier across 7 risk dimensions and generates
a professional PDF report with recommended actions.

Dimensions:
  1. Country risk
  2. Currency & quotation risk
  3. Shipping complexity risk
  4. Incoterm risk
  5. Market access risk
  6. Quality assurance risk
  7. Supplier availability risk

Usage:
    pip install pandas reportlab requests
    python supplier_lens.py

AWS Lambda usage:
    Uncomment lambda_handler at the bottom.
"""

import sys
import types

pil_mock = types.ModuleType("PIL")
class FakeImage:
    ANTIALIAS = 1
    LANCZOS = 1
    @staticmethod
    def open(*a, **k): pass
    @staticmethod
    def new(*a, **k): pass

pil_mock.Image = FakeImage
pil_mock._imaging = types.ModuleType("PIL._imaging")
sys.modules["PIL"] = pil_mock
sys.modules["PIL._imaging"] = pil_mock._imaging
sys.modules["PIL.Image"] = types.ModuleType("PIL.Image")
sys.modules["PIL.Image"].Image = FakeImage


import json
import boto3
import io
import os
import requests
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable
)


# ─────────────────────────────────────────────
# COLOURS
# ─────────────────────────────────────────────
DARK_BLUE   = colors.HexColor("#1B3A5C")
MID_BLUE    = colors.HexColor("#2E6DA4")
LIGHT_BLUE  = colors.HexColor("#EAF3FB")
RED         = colors.HexColor("#C0392B")
AMBER       = colors.HexColor("#D68910")
GREEN       = colors.HexColor("#1E8449")
LIGHT_RED   = colors.HexColor("#FDEDEC")
LIGHT_AMBER = colors.HexColor("#FEF9E7")
LIGHT_GREEN = colors.HexColor("#EAFAF1")
LIGHT_GRAY  = colors.HexColor("#F4F6F7")
MID_GRAY    = colors.HexColor("#BDC3C7")
DARK_GRAY   = colors.HexColor("#2C3E50")


# ─────────────────────────────────────────────
# STATIC RISK DATA
# ─────────────────────────────────────────────

# Country risk scores (1-10) based on World Bank / Transparency International
# Lower = safer, Higher = riskier
COUNTRY_RISK = {
    "germany": 1, "japan": 1, "uk": 1, "united kingdom": 1,
    "united states": 1, "usa": 1, "canada": 1, "australia": 1,
    "france": 2, "netherlands": 2, "sweden": 2, "switzerland": 2,
    "south korea": 3, "singapore": 2, "uae": 3,
    "china": 5, "india": 5, "turkey": 6, "brazil": 5,
    "mexico": 6, "indonesia": 5, "vietnam": 5, "thailand": 4,
    "malaysia": 4, "taiwan": 3, "poland": 3, "czechia": 3,
    "nigeria": 7, "ghana": 6, "kenya": 6, "south africa": 6,
    "egypt": 7, "pakistan": 8, "bangladesh": 7, "myanmar": 9,
    "russia": 9, "ukraine": 8, "iran": 10, "north korea": 10,
    "venezuela": 9, "afghanistan": 10, "libya": 10,
}

# Currency volatility risk (1-10)
CURRENCY_RISK = {
    "usd": 1, "eur": 1, "gbp": 1, "chf": 1, "jpy": 2,
    "sgd": 2, "aud": 2, "cad": 2, "nzd": 2,
    "cny": 3, "inr": 4, "brl": 5, "mxn": 5, "try": 8,
    "zar": 6, "ngn": 9, "ghs": 7, "kes": 6, "egp": 7,
    "pkr": 8, "idr": 5, "thb": 4, "vnd": 5, "myr": 4,
}

# Incoterm risk (1-10) — higher means more risk on buyer
INCOTERM_RISK = {
    "DDP": 1,  # Delivered Duty Paid — supplier carries most risk
    "DAP": 2,  # Delivered At Place
    "CIF": 4,  # Cost Insurance Freight — handover at destination port
    "CFR": 4,  # Cost and Freight
    "CPT": 4,  # Carriage Paid To
    "CIP": 3,  # Carriage and Insurance Paid
    "FCA": 6,  # Free Carrier
    "FAS": 7,  # Free Alongside Ship
    "FOB": 7,  # Free On Board — you take risk at origin port
    "EXW": 10, # Ex Works — maximum risk on buyer
}

INCOTERM_ACTIONS = {
    "DDP": "Confirm DDP includes ALL destination duties and taxes. Get total landed cost in writing before confirming order.",
    "DAP": "Confirm whether import duties are included. Appoint clearing agent before shipment arrives.",
    "CIF": "Specify exact handover point in writing. Confirm your clearing agent is approved by supplier's forwarder before shipment. Include demurrage liability clause in contract.",
    "CFR": "Arrange your own cargo insurance from port of origin. Confirm clearing agent before shipment.",
    "CPT": "Confirm carrier and transit route. Arrange cargo insurance independently.",
    "CIP": "Verify insurance coverage level meets your requirements. Confirm handover point in writing.",
    "FCA": "Appoint freight forwarder before order is placed. Confirm export documentation responsibility with supplier.",
    "FAS": "Arrange vessel booking before order confirmation. Obtain cargo insurance from point of loading.",
    "FOB": "Appoint freight forwarder before order is placed. Obtain cargo insurance from port of origin. Confirm export documentation responsibility with supplier.",
    "EXW": "You carry maximum risk from supplier warehouse. Appoint freight forwarder before order. Obtain cargo insurance from collection point. Handle all export documentation and customs clearance.",
}


# ─────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────
def score_to_rag(score: float) -> str:
    if score <= 3:
        return "GREEN"
    elif score <= 6:
        return "AMBER"
    else:
        return "RED"


def score_country_risk(supplier_country: str) -> dict:
    country = supplier_country.lower().strip()
    score = COUNTRY_RISK.get(country, 6)
    rag = score_to_rag(score)
    if rag == "GREEN":
        action = "Standard due diligence sufficient. Verify supplier registration and trading history."
    elif rag == "AMBER":
        action = "Request third party inspection for high value orders. Ensure payment terms are documented in writing. Consider trade credit insurance."
    else:
        action = "Consider alternative sourcing country. Use escrow payment or letter of credit. Obtain cargo insurance. Verify supplier is not on any sanctions list."
    return {"dimension": "Country risk", "score": score, "rag": rag, "action": action,
            "detail": f"Supplier country: {supplier_country.title()}"}


def score_currency_risk(supplier_currency: str, quote_currency: str) -> dict:
    sup_cur = supplier_currency.upper().strip()
    quo_cur = quote_currency.upper().strip()
    if sup_cur == quo_cur:
        score = 1
        detail = f"Buying and quoting in same currency ({sup_cur}) — no conversion risk"
    else:
        score = CURRENCY_RISK.get(quo_cur, 6)
        detail = f"Buying in {sup_cur}, quoting end user in {quo_cur}"
    rag = score_to_rag(score)
    if rag == "GREEN":
        action = "No hedging needed. Standard margin calculation applies."
    elif rag == "AMBER":
        action = "Add 8% currency buffer to quote. Limit quote validity to 5 days. Monitor exchange rate daily during open quote period."
    else:
        action = "Quote in USD or GBP only where possible. If quoting in local currency add 15-20% buffer. Set quote validity to 24-48 hours maximum. Include currency escalation clause in contract. Lock supplier price in writing before issuing quote to end user."
    return {"dimension": "Currency & quotation risk", "score": score, "rag": rag,
            "action": action, "detail": detail}


def score_shipping_risk(freight_mode: str, hazardous: bool, route_distance: str) -> dict:
    freight_mode   = (freight_mode or "sea").lower().strip()
    route_distance = (route_distance or "medium").lower().strip()
    score = 0
    if freight_mode == "sea":
        score += 4
    elif freight_mode == "air":
        score += 2
    else:
        score += 3
    if hazardous:
        score += 3
    if route_distance == "long":
        score += 2
    elif route_distance == "medium":
        score += 1
    score = min(score, 10)
    rag = score_to_rag(score)
    haz_note = " Hazardous goods classification applies." if hazardous else ""
    detail = f"Freight mode: {freight_mode.title()} | Route: {route_distance.title()} haul | Hazardous: {'Yes' if hazardous else 'No'}"
    if rag == "GREEN":
        action = f"Standard shipping terms apply.{haz_note} Confirm freight forwarder before order."
    elif rag == "AMBER":
        action = f"Build 10-15% shipping cost buffer into quote.{haz_note} Confirm freight forwarder has presence at destination port. Obtain shipping quote before issuing customer quote."
    else:
        action = f"Obtain hazmat certification documentation before shipment.{haz_note} Appoint clearing agent before goods arrive. Add demurrage clause to contract. Budget for port delays of 5-10 working days. Do not quote end user until freight cost is confirmed in writing."
    return {"dimension": "Shipping complexity risk", "score": score, "rag": rag,
            "action": action, "detail": detail}


def score_incoterm_risk(incoterm: str) -> dict:
    term = incoterm.upper().strip()
    score = INCOTERM_RISK.get(term, 6)
    rag = score_to_rag(score)
    action = INCOTERM_ACTIONS.get(term, "Clarify risk transfer point with supplier in writing.")
    detail = f"Selected Incoterm: {term}"
    return {"dimension": "Incoterm risk", "score": score, "rag": rag,
            "action": action, "detail": detail}


def score_market_access_risk(sells_globally: bool, requires_distributor: bool,
                              country_restrictions: bool) -> dict:
    score = 1
    if country_restrictions:
        score += 5
    if requires_distributor:
        score += 3
    if not sells_globally:
        score += 2
    score = min(score, 10)
    rag = score_to_rag(score)
    detail_parts = []
    if country_restrictions:
        detail_parts.append("Supplier has country/region restrictions")
    if requires_distributor:
        detail_parts.append("Must purchase via authorised distributor")
    if not sells_globally:
        detail_parts.append("Supplier does not sell globally")
    detail = " | ".join(detail_parts) if detail_parts else "No access restrictions identified"
    if rag == "GREEN":
        action = "No access restrictions identified. Confirm supplier accepts orders from your country before placing order."
    elif rag == "AMBER":
        action = "Identify authorised distributor for your region before approaching supplier directly. Confirm distributor stock levels and lead times. Budget 10-15% additional margin for distributor."
    else:
        action = "Direct purchase unlikely. Source via authorised regional distributor or a freight forwarding company with a US/UK registered entity. Budget additional 15-20% for distributor margin. Confirm distributor can export to your destination country."
    return {"dimension": "Market access risk", "score": score, "rag": rag,
            "action": action, "detail": detail}


def score_qa_risk(iso_certified: bool, third_party_inspection: bool,
                  cross_border_returns: bool) -> dict:
    score = 0
    if not iso_certified:
        score += 3
    if not third_party_inspection:
        score += 4
    if not cross_border_returns:
        score += 3
    score = min(score, 10)
    rag = score_to_rag(score)
    detail_parts = []
    detail_parts.append(f"ISO certified: {'Yes' if iso_certified else 'No'}")
    detail_parts.append(f"Third party inspection available: {'Yes' if third_party_inspection else 'No'}")
    detail_parts.append(f"Cross-border returns process: {'Yes' if cross_border_returns else 'No'}")
    detail = " | ".join(detail_parts)
    if rag == "GREEN":
        action = "Request copy of current ISO certificate. Conduct standard inspection on delivery. Document condition on receipt."
    elif rag == "AMBER":
        action = "Specify inspection criteria in purchase order. Request pre-shipment photos and signed packing list. Consider sending representative for high value orders."
    else:
        action = "Do not rely on supplier's own quality test. Appoint independent third party inspector before shipment. Document condition at origin with photos and signed inspection report. For high value orders send your own representative. Include rejection and return clause in contract — even if cross-border returns are difficult, having it in the contract strengthens your position."
    return {"dimension": "Quality assurance risk", "score": score, "rag": rag,
            "action": action, "detail": detail}


def score_availability_risk(multiple_suppliers: bool, long_lead_time: bool,
                             single_source: bool) -> dict:
    score = 1
    if single_source:
        score += 6
    if not multiple_suppliers:
        score += 2
    if long_lead_time:
        score += 2
    score = min(score, 10)
    rag = score_to_rag(score)
    detail_parts = []
    detail_parts.append(f"Multiple suppliers available: {'Yes' if multiple_suppliers else 'No'}")
    detail_parts.append(f"Single source item: {'Yes' if single_source else 'No'}")
    detail_parts.append(f"Long lead time: {'Yes' if long_lead_time else 'No'}")
    detail = " | ".join(detail_parts)
    if rag == "GREEN":
        action = "Confirm stock availability before quoting end user. Get written price confirmation valid for your quote period."
    elif rag == "AMBER":
        action = "Confirm stock before accepting PO from end user. Do not quote until supplier price is locked in writing. Build lead time buffer into your delivery commitment."
    else:
        action = "This is a single source or hard to find item. Do not quote end user until stock is confirmed AND price is locked in writing. Consider requesting deposit from end user before placing order. Identify alternative suppliers or substitutes before committing. If item is obsolete, confirm condition and warranty terms."
    return {"dimension": "Supplier availability risk", "score": score, "rag": rag,
            "action": action, "detail": detail}


# ─────────────────────────────────────────────
# OVERALL SCORE
# ─────────────────────────────────────────────
def overall_score(scores: list) -> dict:
    avg = sum(s["score"] for s in scores) / len(scores)
    rag = score_to_rag(avg)
    return {"score": round(avg, 1), "rag": rag}


# ─────────────────────────────────────────────
# PRINT TERMINAL REPORT
# ─────────────────────────────────────────────
def print_report(supplier_name: str, scores: list, overall: dict):
    divider = "-" * 65
    rag_symbols = {"GREEN": "GREEN  ", "AMBER": "AMBER  ", "RED": "RED    "}
    print(divider)
    print("  SUPPLIERLENS — INTERNATIONAL SUPPLIER RISK REPORT")
    print(f"  Supplier : {supplier_name}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(divider)
    print(f"\n  OVERALL RISK SCORE: {overall['score']}/10 — {overall['rag']}\n")
    print(divider)
    for s in scores:
        print(f"\n  {rag_symbols[s['rag']]} {s['dimension']} — {s['score']}/10")
        print(f"  {s['detail']}")
        print(f"  Action: {s['action']}")
    print(f"\n{divider}\n  END OF REPORT\n{divider}")


# ─────────────────────────────────────────────
# BUILD PDF
# ─────────────────────────────────────────────
def build_pdf(supplier_name: str, scores: list, overall: dict,
              path = "supplier_risk_report.pdf"):

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )

    title_style = ParagraphStyle(
        "Title", fontName="Helvetica-Bold", fontSize=20,
        textColor=DARK_BLUE, spaceAfter=6, leading=26,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", fontName="Helvetica", fontSize=10,
        textColor=colors.HexColor("#7F8C8D"), spaceBefore=4, spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "Section", fontName="Helvetica-Bold", fontSize=13,
        textColor=DARK_BLUE, spaceBefore=14, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", fontName="Helvetica", fontSize=10,
        textColor=DARK_GRAY, spaceAfter=4, leading=15,
    )
    action_style = ParagraphStyle(
        "Action", fontName="Helvetica-Oblique", fontSize=9,
        textColor=DARK_GRAY, spaceAfter=4, leading=13, leftIndent=4,
    )
    footer_style = ParagraphStyle(
        "Footer", fontName="Helvetica", fontSize=8,
        textColor=colors.HexColor("#95A5A6"), alignment=TA_CENTER,
    )

    rag_colors = {"GREEN": GREEN, "AMBER": AMBER, "RED": RED}
    rag_bg     = {"GREEN": LIGHT_GREEN, "AMBER": LIGHT_AMBER, "RED": LIGHT_RED}

    story = []
    generated = datetime.now().strftime("%d %B %Y at %H:%M")

    # ── Header ───────────────────────────────
    story.append(Paragraph("SupplierLens Risk Report", title_style))
    story.append(Paragraph(f"Supplier: {supplier_name} | Generated: {generated}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=MID_BLUE, spaceAfter=10))

    # ── Overall Score ─────────────────────────
    story.append(Paragraph("Overall Risk Score", section_style))

    rag = overall["rag"]
    overall_color = rag_colors[rag]
    overall_bg = rag_bg[rag]

    overall_data = [[
        Paragraph(
            f"{overall['score']} / 10 — {rag}",
            ParagraphStyle(
                "BigScore", fontName="Helvetica-Bold", fontSize=26,
                textColor=overall_color, alignment=TA_CENTER, leading=32,
            )
        )
    ]]
    overall_table = Table(overall_data, colWidths=[170*mm])
    overall_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), overall_bg),
        ("BOX",           (0, 0), (-1, -1), 1.5, overall_color),
        ("TOPPADDING",    (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(overall_table)
    story.append(Spacer(1, 10))

    # ── RAG Legend ───────────────────────────
    story.append(Paragraph("How to read this report", section_style))

    legend_data = [
        [
            Paragraph("GREEN  (1–3)", ParagraphStyle(
                "LegG", fontName="Helvetica-Bold", fontSize=9, textColor=GREEN)),
            Paragraph(
                "Low risk. Standard procurement procedures apply. "
                "Proceed with normal due diligence.", body_style),
        ],
        [
            Paragraph("AMBER  (4–6)", ParagraphStyle(
                "LegA", fontName="Helvetica-Bold", fontSize=9, textColor=AMBER)),
            Paragraph(
                "Moderate risk. Additional precautions are recommended. "
                "Review the specific actions for this dimension before proceeding.", body_style),
        ],
        [
            Paragraph("RED  (7–10)", ParagraphStyle(
                "LegR", fontName="Helvetica-Bold", fontSize=9, textColor=RED)),
            Paragraph(
                "High risk. Do not proceed without addressing the recommended actions. "
                "Failure to act on RED dimensions has historically led to financial loss, "
                "delivery failure, or quality disputes.", body_style),
        ],
    ]
    legend_table = Table(legend_data, colWidths=[38*mm, 132*mm])
    legend_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), LIGHT_GREEN),
        ("BACKGROUND",    (0, 1), (0, 1), LIGHT_AMBER),
        ("BACKGROUND",    (0, 2), (0, 2), LIGHT_RED),
        ("ROWBACKGROUNDS",(1, 0), (1, -1), [LIGHT_GREEN, LIGHT_AMBER, LIGHT_RED]),
        ("BOX",           (0, 0), (-1, -1), 0.5, MID_GRAY),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, MID_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(legend_table)
    story.append(Spacer(1, 10))

    # ── Dimension Breakdown ───────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=MID_GRAY, spaceAfter=6))
    story.append(Paragraph("Risk Dimension Breakdown", section_style))

    cell_style = ParagraphStyle(
        "Cell", fontName="Helvetica", fontSize=9,
        textColor=DARK_GRAY, leading=13,
    )
    cell_bold = ParagraphStyle(
        "CellBold", fontName="Helvetica-Bold", fontSize=9,
        textColor=colors.white, leading=13,
    )

    header_row = [
        Paragraph("Dimension", cell_bold),
        Paragraph("Score", cell_bold),
        Paragraph("Rating", cell_bold),
        Paragraph("Detail", cell_bold),
    ]

    rows = [header_row]
    for s in scores:
        rc = rag_colors[s["rag"]]
        rows.append([
            Paragraph(s["dimension"], cell_style),
            Paragraph(f"{s['score']} / 10", ParagraphStyle(
                "Score", fontName="Helvetica-Bold", fontSize=9,
                textColor=rc, leading=13,
            )),
            Paragraph(s["rag"], ParagraphStyle(
                "RAG", fontName="Helvetica-Bold", fontSize=9,
                textColor=rc, leading=13,
            )),
            Paragraph(s["detail"], cell_style),
        ])

    dim_table = Table(rows, colWidths=[48*mm, 18*mm, 20*mm, 84*mm], repeatRows=1)
    dim_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), DARK_BLUE),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("BOX",           (0, 0), (-1, -1), 0.5, MID_GRAY),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, MID_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(dim_table)

    # ── Recommended Actions (always page 2) ──
    from reportlab.platypus import PageBreak
    story.append(PageBreak())
    story.append(Paragraph("Recommended Actions", section_style))
    story.append(Paragraph(
        "The actions below are listed in order of the seven risk dimensions. "
        "Address RED items before proceeding with this supplier.",
        body_style,
    ))
    story.append(Spacer(1, 6))

    for s in scores:
        rc  = rag_colors[s["rag"]]
        rbg = rag_bg[s["rag"]]
        action_data = [[
            Paragraph(s["dimension"], ParagraphStyle(
                "DimTitle", fontName="Helvetica-Bold", fontSize=9,
                textColor=rc, leading=13,
            )),
            Paragraph(s["action"], action_style),
        ]]
        action_table = Table(action_data, colWidths=[48*mm, 122*mm])
        action_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0), rbg),
            ("BOX",           (0, 0), (-1, -1), 0.5, rc),
            ("INNERGRID",     (0, 0), (-1, -1), 0.3, MID_GRAY),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(action_table)
        story.append(Spacer(1, 4))

    # ── Footer ───────────────────────────────
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=MID_GRAY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Confidential — SupplierLens International Supplier Risk Evaluator | {generated}",
        footer_style,
    ))

    doc.build(story)
    print(f"\nPDF saved to: {path}")


# ─────────────────────────────────────────────
# USER INPUT (local mode)
# ─────────────────────────────────────────────
def get_input(prompt: str, options: list = None) -> str:
    if options:
        opts = "/".join(options)
        while True:
            val = input(f"{prompt} [{opts}]: ").strip()
            if val.lower() in [o.lower() for o in options]:
                return val.lower()
            print(f"  Please enter one of: {opts}")
    return input(f"{prompt}: ").strip()


def get_bool(prompt: str) -> bool:
    val = get_input(prompt, ["yes", "no"])
    return val == "yes"


def collect_inputs() -> dict:
    print("\n" + "="*65)
    print("  SUPPLIERLENS — INTERNATIONAL SUPPLIER RISK EVALUATOR")
    print("="*65)
    print("  Answer the questions below to generate your risk report.\n")

    data = {}
    data["supplier_name"]       = get_input("Supplier name")
    data["supplier_country"]    = get_input("Supplier country")
    data["supplier_currency"]   = get_input("Supplier invoice currency (e.g. USD, GBP, CNY)")
    data["quote_currency"]      = get_input("Currency you will quote end user in (e.g. NGN, GBP)")
    data["incoterm"]            = get_input("Incoterm", ["EXW","FCA","FAS","FOB","CFR","CIF","CPT","CIP","DAP","DDP"])
    data["freight_mode"]        = get_input("Freight mode", ["air", "sea", "road"])
    data["route_distance"]      = get_input("Route distance", ["short", "medium", "long"])
    data["hazardous"]           = get_bool("Are the goods hazardous?")
    data["sells_globally"]      = get_bool("Does the supplier sell globally?")
    data["requires_distributor"]= get_bool("Must you buy via an authorised distributor?")
    data["country_restrictions"]= get_bool("Does the supplier restrict sales by country/region?")
    data["iso_certified"]       = get_bool("Is the supplier ISO certified?")
    data["third_party_inspection"] = get_bool("Is independent third party inspection available?")
    data["cross_border_returns"]= get_bool("Does the supplier have a cross-border returns process?")
    data["multiple_suppliers"]  = get_bool("Are there multiple suppliers for this item?")
    data["single_source"]       = get_bool("Is this a single source or hard to find item?")
    data["long_lead_time"]      = get_bool("Is the lead time longer than 4 weeks?")
    return data


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def run():
    data = collect_inputs()

    scores = [
        score_country_risk(data["supplier_country"]),
        score_currency_risk(data["supplier_currency"], data["quote_currency"]),
        score_shipping_risk(data["freight_mode"], data["hazardous"], data["route_distance"]),
        score_incoterm_risk(data["incoterm"]),
        score_market_access_risk(data["sells_globally"], data["requires_distributor"],
                                  data["country_restrictions"]),
        score_qa_risk(data["iso_certified"], data["third_party_inspection"],
                      data["cross_border_returns"]),
        score_availability_risk(data["multiple_suppliers"], data["long_lead_time"],
                                 data["single_source"]),
    ]

    overall = overall_score(scores)
    print_report(data["supplier_name"], scores, overall)
    build_pdf(data["supplier_name"], scores, overall)


if __name__ == "__main__":
    run()


# ─────────────────────────────────────────────
# AWS LAMBDA HANDLER
# Triggered by API Gateway HTTP POST
# Reads JSON body, scores risk, builds PDF,
# saves to S3, returns pre-signed download URL
# ─────────────────────────────────────────────
S3_BUCKET = "YOUR S3 BUCKET NAME"  
URL_EXPIRY = 3600 


def lambda_handler(event, context):
    
    global S3_BUCKET
    S3_BUCKET = os.environ.get("S3_BUCKET", S3_BUCKET)


    import logging
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.info(f"Event received: {json.dumps(event)}")

    # Handle CORS preflight request
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "OPTIONS":
        return _response(200, {})

    # ── Parse incoming JSON body from API Gateway ──
    try:
        if isinstance(event.get("body"), str):
            data = json.loads(event["body"])
        else:
            data = event.get("body", event)
    except Exception as e:
        return _response(400, {"error": f"Invalid JSON body: {str(e)}"})

    # ── Validate required fields ──
    required = [
        "supplier_name", "supplier_country", "supplier_currency",
        "quote_currency", "incoterm", "freight_mode", "route_distance",
    ]
    for field in required:
        if not data.get(field):
            return _response(400, {"error": f"Missing required field: {field}"})

    # ── Run scoring engine ──
    try:
        scores = [
            score_country_risk(data["supplier_country"]),
            score_currency_risk(data["supplier_currency"], data["quote_currency"]),
            score_shipping_risk(
                data["freight_mode"],
                bool(data.get("hazardous", False)),
                data["route_distance"],
            ),
            score_incoterm_risk(data["incoterm"]),
            score_market_access_risk(
                bool(data.get("sells_globally", True)),
                bool(data.get("requires_distributor", False)),
                bool(data.get("country_restrictions", False)),
            ),
            score_qa_risk(
                bool(data.get("iso_certified", False)),
                bool(data.get("third_party_inspection", False)),
                bool(data.get("cross_border_returns", False)),
            ),
            score_availability_risk(
                bool(data.get("multiple_suppliers", True)),
                bool(data.get("long_lead_time", False)),
                bool(data.get("single_source", False)),
            ),
        ]
        overall = overall_score(scores)
    except Exception as e:
        return _response(500, {"error": f"Scoring error: {str(e)}"})

    # ── Build PDF into memory ──
    try:
        pdf_buffer = io.BytesIO()
        build_pdf(data["supplier_name"], scores, overall, pdf_buffer)
        pdf_buffer.seek(0)
    except Exception as e:
        return _response(500, {"error": f"PDF generation error: {str(e)}"})

    # ── Upload PDF to S3 ──
    try:
        s3 = boto3.client("s3")
        safe_name = data["supplier_name"].replace(" ", "_").replace("/", "-")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        s3_key = f"outputs/supplier_risk_{safe_name}_{timestamp}.pdf"

        s3.upload_fileobj(
            pdf_buffer,
            S3_BUCKET,
            s3_key,
            ExtraArgs={"ContentType": "application/pdf"},
        )

        # Generate pre-signed URL valid for 1 hour
        CLOUDFRONT_DOMAIN = "YOUR CLOUDFRONT DOMAIN"
        pdf_url = f"https://{CLOUDFRONT_DOMAIN}/{s3_key}"

    except Exception as e:
        return _response(500, {"error": f"S3 upload error: {str(e)}"})

    # ── Return result to the form ──
    return _response(200, {
        "overall_score": overall["score"],
        "rag":           overall["rag"],
        "pdf_url":       pdf_url,
        "supplier_name": data["supplier_name"],
        "dimensions":    [
            {"dimension": s["dimension"], "score": s["score"], "rag": s["rag"]}
            for s in scores
        ],
    })


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }