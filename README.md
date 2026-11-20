# Searchable PDF — Render deployment

## GitHub repository mein ye files rakho
- app.py
- requirements.txt
- Dockerfile
- render.yaml (optional Blueprint deployment)

## Render par deploy
1. In files ko GitHub repository ke root mein upload karo.
2. Render Dashboard → New + → Blueprint.
3. GitHub repository connect karo.
4. Render `render.yaml` read karke Free web service banayega.
5. Deploy complete hone par Render URL open karo.

Manual setup: New Web Service → GitHub repo → Runtime Docker → Plan Free → Deploy.

## App
- Browser se PDF upload
- Marathi / Hindi / English OCR language
- OCRmyPDF + Tesseract
- Existing searchable pages `--skip-text` se skip
- One OCR worker, `--optimize 0`, PDF output
- Result filename `searchable.pdf`

## Critical Free-plan limitation
App-side upload cap 1 GB set hai. Yeh Render Free ki guaranteed supported upload size ya processing capacity nahi hai. Render Free has limited RAM/CPU and ephemeral local storage; very large uploads can fail, and service restarts can interrupt jobs/delete files. A PDF with 700,000–2,000,000 pages is not a realistic/reliable Free-plan workload. No processing-time or completion guarantee is possible. The app is for small-file testing on Free.
