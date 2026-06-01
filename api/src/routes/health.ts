import { Router } from "express";

export const healthRouter = Router();

healthRouter.get("/", (_req, res) => {
  res.json({
    status: "ok",
    service: "trezo-api",
    time: new Date().toISOString(),
    env: process.env.NODE_ENV ?? "development"
  });
});
