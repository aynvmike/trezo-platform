import { Router } from "express";
import { requireAuth, type AuthedRequest } from "../middleware/auth";

export const authRouter = Router();

/**
 * Auth verification probe. Front-end calls this with a fresh Supabase access
 * token to confirm the API can validate the user. Actual sign-up/sign-in flows
 * happen client-side against Supabase directly.
 */
authRouter.get("/me", requireAuth, (req: AuthedRequest, res) => {
  res.json({ user: req.user });
});
