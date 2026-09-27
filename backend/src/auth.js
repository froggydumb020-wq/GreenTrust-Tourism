import jwt from 'jsonwebtoken';
import { Hotel } from './models.js';
import { config } from './config.js';

export const JWT_SECRET = config.jwtSecret;
export const JWT_EXPIRES_IN = config.jwtExpiresIn;

export function signToken(hotel) {
  return jwt.sign(
    { sub: hotel._id.toString(), email: hotel.email, hotel_name: hotel.hotel_name },
    JWT_SECRET,
    { expiresIn: JWT_EXPIRES_IN },
  );
}

export async function requireAuth(req, res, next) {
  try {
    const header = req.headers.authorization || '';
    const token = header.startsWith('Bearer ') ? header.slice(7) : null;
    if (!token) return res.status(401).json({ error: 'Authentication required' });
    const payload = jwt.verify(token, JWT_SECRET);
    const hotel = await Hotel.findById(payload.sub);
    if (!hotel) return res.status(401).json({ error: 'Account not found' });
    req.hotel = hotel;
    next();
  } catch (err) {
    if (err.name === 'TokenExpiredError') return res.status(401).json({ error: 'Session expired' });
    if (err.name === 'JsonWebTokenError') return res.status(401).json({ error: 'Invalid token' });
    return res.status(401).json({ error: 'Authentication failed' });
  }
}

export function sanitizeHotel(hotel) {
  const obj = hotel.toObject ? hotel.toObject() : { ...hotel };
  delete obj.password_hash;
  delete obj.__v;
  return obj;
}
