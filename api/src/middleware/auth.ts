import type { Request, Response, NextFunction } from "express";
import jwt from "jsonwebtoken";
import { config } from "../core/config";

export interface AuthedRequest extends Request {
  user?: {
    id: string;
    email?: string;
  };
}

/**
 * Verify Supabase-issued JWT from the Authorization: Bearer <token> header.
 * Returns 401 if missing/invalid.
 */
export function requireAuth(
  req: AuthedRequest,
  res: Response,
  next: NextFunction
) {
  const header = req.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token) {
    return res.status(401).json({ error: "Missing Authorization header" });
  }
  if (!config.supabase.jwtSecret) {
    return res.status(503).json({ error: "Supabase JWT secret not configured" });
  }
  try {
    const decoded = jwt.verify(token, config.supabase.jwtSecret) as {
      sub: string;
      email?: string;
    };
    req.user = { id: decoded.sub, email: decoded.email };
    return next();
  } catch {
    return res.status(401).json({ error: "Invalid or expired token" });
  }
}
