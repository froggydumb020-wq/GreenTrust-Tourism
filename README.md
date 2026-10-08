# GreenTrust — Sustainable Tourism Verification System

**Phase 1: Evidence Ingestion & Preprocessing**

A hotel evidence ingestion and preprocessing system that takes uploaded documents (PDF, DOCX, PNG, JPG), extracts and cleans text, generates structured JSON, computes a SHA-256 integrity hash, and stores everything in MongoDB with a dashboard for visibility.

---

## Architecture

```
Frontend (React + Vite + Tailwind)
        ↓  HTTP
Backend (Node.js + Express + Multer)
        ↓  HTTP (multipart)
Processor (Python + FastAPI + PyMuPDF + Tesseract)
        ↓
MongoDB Atlas (Mongoose models)
        ↑
Frontend dashboard reads results
```

### Processing flow

```
UPLOADED → PROCESSING → PROCESSED
                     ↘ FAILED (with error message)
```

1. Validate file (type + 20 MB max)
2. Save file to disk
3. Create document record in MongoDB
4. Set status = PROCESSING
5. Send file to FastAPI processor
6. Extract text (PyMuPDF / python-docx / Tesseract OCR)
7. Clean text (whitespace, line breaks, noise)
8. Extract metadata (file type, pages, words, lines, dates, method, timestamp)
9. Generate structured JSON (document info, summary, key excerpts, relevant terms, metadata)
10. Generate SHA-256 hash
11. Save extracted data to MongoDB
12. Set status = PROCESSED
13. Display results in dashboard

---

## Project structure

```
├── src/                    # Frontend (React + Vite + Tailwind)
│   ├── App.tsx             # Dashboard, upload, documents, details
│   ├── api.ts              # API client (backend calls + mock fallback)
│   └── index.css           # GreenTrust design system
├── backend/                # Express API
│   ├── src/
│   │   ├── index.js        # Routes & server
│   │   ├── config.js       # Env config & Mongo connection
│   │   ├── models.js       # Mongoose models
│   │   └── processor.js    # FastAPI integration & pipeline
│   ├── package.json
│   └── .env.example
└── processor/              # FastAPI document processor
    ├── app.py              # Extraction endpoints
    └── requirements.txt
```

---

## Prerequisites

- Node.js 18+
- Python 3.10+
- Tesseract OCR (system package)
- MongoDB Atlas cluster (connection string)

### Install Tesseract

**macOS:** `brew install tesseract`
**Ubuntu/Debian:** `sudo apt-get install tesseract-ocr`
**Windows:** Download from https://github.com/UB-Mannheim/tesseract/wiki

---

## Setup & Run

### 1. Frontend

```bash
npm install
cp .env.example .env
npm run dev
```

The dashboard runs on http://localhost:5173. It automatically detects whether the backend is running — a "Live" badge in the header means the frontend is connected to your real API; a "Demo" badge means it's using mock data. The Vite dev server proxies `/api` requests to the backend at `VITE_BACKEND_URL` (default http://localhost:4000).

### 2. Backend

```bash
cd backend
npm install
cp .env.example .env
# Edit .env and set MONGODB_URI to your MongoDB Atlas connection string
npm run dev
```

The API runs on http://localhost:4000.

Required environment variables:

| Variable | Description |
|---|---|
| `MONGODB_URI` | MongoDB Atlas connection string |
| `PORT` | Express port (default 4000) |
| `PROCESSOR_URL` | FastAPI processor URL (default http://localhost:8000) |
| `FRONTEND_URL` | Frontend origin for CORS (default http://localhost:5173) |
| `UPLOAD_DIR` | Upload directory (default uploads) |
| `MAX_FILE_SIZE_MB` | Max upload size (default 20) |

### 3. Processor

```bash
cd processor
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

The processor runs on http://localhost:8000.

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| GET | `/api/health` | Service health check |
| POST | `/api/hotels` | Register a hotel (find-or-create by registration_number) |
| GET | `/api/hotels/:hotelId` | Get hotel details |
| POST | `/api/documents/upload` | Upload & start processing a document |
| GET | `/api/documents/:id` | Get document with extracted data |
| GET | `/api/hotels/:hotelId/documents` | List documents for a hotel |
| GET | `/api/packages/:hotelId` | List evidence packages for a hotel |

### Upload example

```bash
curl -X POST http://localhost:4000/api/hotels \
  -H "Content-Type: application/json" \
  -d '{"hotel_name":"Azure Mornings","location":"Kochi, Kerala"}'

curl -X POST http://localhost:4000/api/documents/upload \
  -F "hotel_id=<HOTEL_ID>" \
  -F "package_type=Energy & Water" \
  -F "file=@water-bill.pdf"
```

---

## Evidence Packages

1. **Sustainability & Legal** — policies, licenses, sustainability commitments
2. **Energy & Water** — utility statements, resource consumption
3. **Waste Management** — collection records, waste reduction plans
4. **Environmental Practices** — biodiversity and conservation evidence

---

## Testing the Pipeline

1. Start all three services (frontend, backend, processor)
2. The frontend auto-creates a hotel ("Azure Mornings") on first load when connected to the backend
3. Upload each file type through the dashboard or API:
   - A water-bill PDF (text-based)
   - A PNG/JPG scanned document (OCR)
   - A DOCX policy document
4. Open the document in the dashboard to verify:
   - Extracted text is visible
   - Structured JSON is displayed
   - Metadata (pages, words, dates, method) is shown
   - SHA-256 hash is present

The frontend falls back to mock data when the backend is offline, so the dashboard is always explorable.

---

## Tech Stack

- **Frontend:** React + Vite + Tailwind CSS + Lucide icons
- **Backend:** Node.js + Express + Multer + Mongoose
- **Processor:** Python + FastAPI + PyMuPDF + python-docx + Tesseract
- **Database:** MongoDB Atlas
- **Hashing:** SHA-256

---

**Phase 1 scope only:** Data ingestion and preprocessing. No GSTC rules, AI verification, auditor module, blockchain, smart contracts, credentials, or public verification.
