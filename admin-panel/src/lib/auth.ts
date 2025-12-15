/**
 * Auth utilities for JWT handling
 */

import { jwtVerify, type JWTPayload } from "jose";

export interface TokenPayload extends JWTPayload {
  sub: string;
  exp: number;
  iat: number;
  type: string;
}

/**
 * Decode JWT token without verification (client-side only)
 * Note: Actual verification happens on the server
 */
export function decodeToken(token: string): TokenPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;

    const payload = JSON.parse(atob(parts[1]));
    return payload as TokenPayload;
  } catch {
    return null;
  }
}

/**
 * Check if token is expired
 */
export function isTokenExpired(token: string): boolean {
  const payload = decodeToken(token);
  if (!payload || !payload.exp) return true;

  // Add 60 second buffer
  return Date.now() >= payload.exp * 1000 - 60000;
}

/**
 * Get remaining time until token expires (in seconds)
 */
export function getTokenExpiresIn(token: string): number {
  const payload = decodeToken(token);
  if (!payload || !payload.exp) return 0;

  const remaining = payload.exp - Math.floor(Date.now() / 1000);
  return Math.max(0, remaining);
}

/**
 * Verify JWT token on server side
 */
export async function verifyToken(
  token: string,
  secret: string
): Promise<TokenPayload | null> {
  try {
    const secretKey = new TextEncoder().encode(secret);
    const { payload } = await jwtVerify(token, secretKey);
    return payload as TokenPayload;
  } catch {
    return null;
  }
}
