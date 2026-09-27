import express from 'express';
import cors from 'cors';
import multer from 'multer';
import crypto from 'node:crypto';
import path from 'node:path';
import fs from 'node:fs';
import { config, connectMongo, isAllowedFile, detectExtension } from './config.js';
import { Hotel, Document, ExtractedData, EvidencePackage } from './models.js';
import { processDocument, ensurePackage } from './processor.js';

const app = express();

app.use(cors({ origin: config.frontendUrl, credentials: true }));
app.use(express.json());

fs.mkdirSync(path.resolve(config.uploadDir), { recursive: true });

const upload = multer({
  dest: path.resolve(config.uploadDir),
  limits: { fileSize: config.maxFileSize },
  fileFilter: (_req, file, cb) => {
    if (isAllowedFile(file.mimetype, file.originalname)) cb(null, true);
    else cb(new Error('Only PDF, DOCX, PNG, and JPG files are allowed'));
  },
});

function shortHash() { return crypto.randomBytes(6).toString('hex'); }

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', service: 'greentrust-backend', timestamp: new Date().toISOString() });
});

app.post('/api/hotels', async (req, res) => {
  try {
    const { hotel_name, location, contact, registration_number } = req.body || {};
    if (!hotel_name) return res.status(400).json({ error: 'hotel_name is required' });

    if (registration_number) {
      const existing = await Hotel.findOne({ registration_number });
      if (existing) return res.status(200).json(existing);
    }

    const hotel = await Hotel.create({ hotel_name, location, contact, registration_number });
    res.status(201).json(hotel);
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
});

app.get('/api/hotels/:hotelId', async (req, res) => {
  try {
    const hotel = await Hotel.findById(req.params.hotelId);
    if (!hotel) return res.status(404).json({ error: 'Hotel not found' });
    res.json(hotel);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/documents/upload', upload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
  const hotelId = req.body.hotel_id;
  const packageType = req.body.package_type || 'Energy & Water';
  if (!hotelId) return res.status(400).json({ error: 'hotel_id is required' });

  const fileType = detectExtension(req.file.mimetype, req.file.originalname);
  if (!fileType) return res.status(400).json({ error: 'Unsupported file type' });

  try {
    const hotel = await Hotel.findById(hotelId);
    if (!hotel) return res.status(404).json({ error: 'Hotel not found' });

    const pkg = await ensurePackage(hotelId, packageType);
    const document = await Document.create({
      document_id: `doc-${shortHash()}`,
      package: pkg._id,
      hotel: hotelId,
      file_name: req.file.originalname,
      file_type: fileType,
      file_path: req.file.path,
      file_size: req.file.size,
      status: 'UPLOADED',
      uploaded_at: new Date(),
    });

    processDocument(document).catch((err) => console.error('[async] processing error:', err.message));

    res.status(202).json({ message: 'Document uploaded and processing started', document });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/documents/:id', async (req, res) => {
  try {
    const document = await Document.findOne({ document_id: req.params.id }).populate('hotel').populate('package');
    if (!document) return res.status(404).json({ error: 'Document not found' });
    const extracted = await ExtractedData.findOne({ document: document._id }).sort({ processed_at: -1 });
    res.json({ document, extracted_data: extracted });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/hotels/:hotelId/documents', async (req, res) => {
  try {
    const documents = await Document.find({ hotel: req.params.hotelId }).populate('package').sort({ uploaded_at: -1 });
    res.json({ documents });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/packages/:hotelId', async (req, res) => {
  try {
    const packages = await EvidencePackage.find({ hotel: req.params.hotelId }).sort({ created_at: -1 });
    res.json({ packages });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

const server = app.listen(config.port, async () => {
  console.log(`[api] GreenTrust backend on http://localhost:${config.port}`);
  await connectMongo();
});

export { server };
