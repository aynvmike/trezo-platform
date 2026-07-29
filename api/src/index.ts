import "dotenv/config";
import express from "express";
import cors from "cors";
import helmet from "helmet";
import morgan from "morgan";
import rateLimit from "express-rate-limit";

import { config } from "./core/config";
import { logger } from "./core/logger";
import { healthRouter } from "./routes/health";
import { authRouter } from "./routes/auth";
import { profileRouter } from "./routes/profile";
import { errorHandler } from "./middleware/error";

const app = express();

app.use(helmet());
app.use(
  cors({
    origin: config.corsOrigins,
    credentials: true
  })
);
app.use(express.json({ limit: "1mb" }));
app.use(morgan(config.env === "production" ? "combined" : "dev"));

app.use(
  rateLimit({
    windowMs: 60_000,
    max: 120,
    standardHeaders: true,
    legacyHeaders: false
  })
);

app.use("/health", healthRouter);
app.use("/auth", authRouter);
app.use("/profile", profileRouter);

app.use(errorHandler);

const port = Number(config.port);
// SECURITY (Mike 2026-07-28): Express binds 0.0.0.0 by default, so this
// dev API was reachable from the whole network -- and its log filled
// with automated router/IoT exploit probes ("/loginMsg.js",
// "/cgi/get.cgi?cmd=home_login"). Nothing was exposed (every probe
// 404'd, helmet + CORS + rate-limit were all active), but a local dev
// service has no business listening on a public interface. Bind
// loopback only; the web app runs on the same machine. Set
// API_BIND_HOST to override if this is ever fronted by a reverse proxy.
const host = process.env.API_BIND_HOST ?? "127.0.0.1";
app.listen(port, host, () => {
  logger.info({ port, host }, "Trezo API listening");
});
