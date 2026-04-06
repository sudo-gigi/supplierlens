# SupplierLens — International Supplier Risk Evaluator

A cloud-native web application that scores international suppliers across seven procurement risk dimensions and generates a professional PDF report with recommended actions in under 10 seconds.

**Live demo:** [https://d1esjjb5m0g2st.cloudfront.net](https://d1esjjb5m0g2st.cloudfront.net)

---

## The Problem

International procurement is where things go wrong in ways that are expensive and hard to recover from.

A supplier charges above the agreed rate and nobody notices for months. Goods arrive from China already rusting because nobody specified a pre-shipment inspection. A freight forwarder refuses to hand over cargo at the Nigerian port because the Incoterm handover point was never documented. You quote an end user in Naira, the exchange rate moves 15% before they pay, and you absorb the loss.

These are not edge cases. They are the daily reality of procurement teams sourcing internationally, particularly those operating in African markets where currency volatility, port complexity and supplier access restrictions add layers of risk that standard procurement tools ignore entirely.

Enterprise solutions like SAP Ariba and Coupa exist, but they are priced for large corporates and built for Western supply chains. The SMEs and trading companies doing the hardest sourcing work have nothing.

SupplierLens is built for them.

---

## What It Does

Fill in a web form about a supplier you are evaluating. SupplierLens scores them across seven risk dimensions, generates an overall RAG rating, and produces a two-page PDF report with specific recommended actions for each dimension.

The whole process takes under 10 seconds.

---

## The Seven Risk Dimensions

These dimensions were designed from real procurement experience.

| Dimension | What it measures |
|---|---|
| Country risk | Political stability, corruption index, sanctions risk for the supplier's country |
| Currency & quotation risk | Volatility between purchase currency and end-user quote currency, critical when quoting in NGN while buying in USD |
| Shipping complexity risk | Freight mode, route distance, hazardous goods classification |
| Incoterm risk | Where risk transfers from supplier to buyer, EXW scores 10/10, DDP scores 1/10 |
| Market access risk | Whether the supplier sells globally, requires an authorised distributor, or restricts sales by country |
| Quality assurance risk | ISO certification, availability of independent third-party inspection, cross-border returns process |
| Supplier availability risk | Single source items, long lead times, limited alternative suppliers |

Each dimension is scored 1–10 and rated GREEN (low), AMBER (moderate) or RED (high). The overall score is the average across all seven.

---

## Why Incoterms and Currency Risk Are Different Here

Most supplier risk tools treat Incoterms as a compliance checkbox. SupplierLens treats them as a risk dimension because the consequences are real:

- **FOB from China to Lagos** — you own the cargo from the moment it leaves the Chinese port. If your freight forwarder and the supplier's agent disagree over the handover, your goods sit in port accumulating demurrage charges while you negotiate.
- **EXW** — you are responsible from the supplier's warehouse door. Every export document, every customs declaration, every insurance policy is your problem.
- **DDP** — the supplier handles everything to your door. Lowest risk on your side, but you are trusting their landed cost calculation.

Similarly, currency risk here is specifically about the gap between quote date and payment date when quoting in a volatile currency. A procurement team buying in USD and quoting an end user in NGN has real exposure if the rate moves between issuing the quote and receiving payment. SupplierLens flags this and recommends specific buffer percentages and quote validity windows.

---

## Architecture

```
User (browser)
      |
      v
CloudFront (HTTPS, hides S3)
      |
      |-----> S3 (hosts index.html)
      |
      v
API Gateway (HTTP POST /supplierlens)
      |
      v
AWS Lambda (Python 3.11)
  - Parses JSON from form
  - Scores all 7 dimensions
  - Builds PDF with ReportLab
  - Uploads PDF to S3
  - Returns CloudFront URL
      |
      v
S3 outputs/ (stores PDF reports)
      |
      v
CloudFront (serves PDF via clean URL)
      |
      v
User downloads PDF
```

### AWS Services
- **CloudFront** — CDN, HTTPS, hides S3 bucket from public URLs
- **S3** — static website hosting and PDF report storage
- **API Gateway** — HTTP API receiving POST requests from the form
- **Lambda** — serverless scoring engine and PDF generator
- **IAM** — least-privilege roles between services

### Languages and Libraries
- **Python 3.11** — scoring engine and Lambda handler
- **ReportLab** — professional PDF generation
- **HTML / CSS / JavaScript** — single-page form with client-side validation
- No frontend framework — plain HTML keeps it fast and dependency-free

---

## PDF Report

The report is two pages:

**Page 1** — Overall risk score (large, colour-coded), RAG legend, dimension breakdown table

**Page 2** — Recommended actions for each dimension, RED items with specific actionable guidance, confidential footer with timestamp

---

## Scoring Logic

```python
# Country risk
COUNTRY_RISK = {
    "germany": 1, "uk": 1, "usa": 1,
    "china": 5, "nigeria": 7, "iran": 10,
}

# Currency risk — based on volatility profile
CURRENCY_RISK = {
    "usd": 1, "gbp": 1, "eur": 1,
    "ngn": 9, "try": 8, "zar": 6,
}

# Incoterm risk — reflects actual buyer risk exposure
INCOTERM_RISK = {
    "DDP": 1,   # supplier carries everything
    "CIF": 4,   # handover at destination port
    "FOB": 7,   # you own it from origin port
    "EXW": 10,  # you own it from supplier warehouse
}
```

All thresholds are configurable at the top of `lambda_function.py`.

---

## Local Development

```bash
pip install reportlab requests
python lambda_function.py
```

Runs in terminal mode, asks questions interactively and saves PDF locally. No AWS account needed for local testing.

---

## Deployment

All infrastructure is on AWS free tier.

| Service | Free tier limit |
|---|---|
| Lambda | 1M requests/month |
| API Gateway | 1M requests/month |
| S3 | 5GB storage |
| CloudFront | 1TB transfer/month |

---

## About

Built by a procurement and supply chain professional with an AWS Solutions Architect certification and a PGDip in Cloud Computing.

The risk dimensions, Incoterm logic, and currency hedging recommendations in this tool are drawn from real experience sourcing industrial equipment, batteries, and commodities internationally, including the specific failure modes that enterprise tools do not capture: freight forwarder disputes at African ports, NGN volatility exposure in back-to-back trading, and pre-shipment quality failures on long-haul sea freight.

---

## Roadmap

- [ ] Terraform IaC — replace manual AWS console setup with infrastructure as code
- [ ] CI/CD pipeline — GitHub Actions auto-deploy on push
- [ ] Supplier comparison — score multiple suppliers side by side
- [ ] Historical scoring — track how a supplier's risk profile changes over time
- [ ] Companies House API — auto-populate UK supplier financial data

---

## Related Project

[Supply Chain Cost Anomaly Detector](https://github.com/sudo-gigi/Supplychain-Anomaly-Detector.git) — automatically detects price spikes, budget overruns and duplicate invoices in procurement spend data.

---
