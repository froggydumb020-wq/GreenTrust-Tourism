import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import fetch from 'node-fetch';
import { Document, ExtractedData, EvidencePackage } from './models.js';
import { config } from './config.js';

function shortHash() { return crypto.randomBytes(6).toString('hex'); }

async function ensureUploadDir() {
  await fs.mkdir(path.resolve(config.uploadDir), { recursive: true });
}

export async function processDocument(document) {
  try {
    await ensureUploadDir();
    const filePath = path.resolve(document.file_path);

    document.status = 'PROCESSING';
    document.error_message = undefined;
    await document.save();

    const formData = new FormData();
    const fileBuffer = await fs.readFile(filePath);
    const blob = new Blob([fileBuffer]);
    formData.append('file', blob, document.file_name);
    formData.append('document_id', document.document_id);
    formData.append('file_type', document.file_type);

    const response = await fetch(`${config.processorUrl}/process/document`, { method: 'POST', body: formData });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Processor responded ${response.status}: ${detail.slice(0, 200)}`);
    }
    const result = await response.json();

    const hash = result.sha256 || crypto.createHash('sha256').update(fileBuffer).digest('hex');
    document.document_hash = hash;
    document.status = 'PROCESSED';
    document.processed_at = new Date();
    await document.save();

    await ExtractedData.create({
      extraction_id: `ext-${shortHash()}`,
      document: document._id,
      extracted_text: result.extracted_text || '',
      structured_data: result.structured_data || {},
      confidence: result.confidence || 1,
      metadata: result.metadata || {},
      processed_at: new Date(),
    });

    return document;
  } catch (error) {
    document.status = 'FAILED';
    document.error_message = error.message || 'Unknown processing error';
    await document.save();
    console.error(`[process] ${document.document_id} failed:`, error.message);
    return document;
  }
}

export async function ensurePackage(hotelId, packageType) {
  const existing = await EvidencePackage.findOne({ hotel: hotelId, package_type: packageType });
  if (existing) return existing;
  return EvidencePackage.create({ package_id: `pkg-${shortHash()}`, hotel: hotelId, package_type: packageType, status: 'Processing' });
}
