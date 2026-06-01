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
app.listen(port, () => {
  logger.info({ port }, "Trezo API listening");
});
