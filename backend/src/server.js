require("dotenv").config();

const express = require("express");
const helmet = require("helmet");
const cors = require("cors");
const rateLimit = require("express-rate-limit");

const connectDB = require("./config/db");
const { connectRedis } = require("./config/redis");

const authRoutes = require("./routes/auth");
const taskRoutes = require("./routes/tasks");

const app = express();

const PORT = process.env.PORT || 5000;

// ==========================================
// CORS
// ==========================================

const allowedOrigins = [
  "https://task-processor-assignment.vercel.app",
  "https://task-processor-assignment-19oqm2gni.vercel.app",
];

// Allow Vercel preview deployments matching your project
function isAllowedOrigin(origin) {
  if (!origin) {
    return true;
  }

  if (allowedOrigins.includes(origin)) {
    return true;
  }

  // Allow Vercel deployment URLs for this project
  return /^https:\/\/task-processor-assignment-[a-z0-9]+\.vercel\.app$/.test(
    origin
  );
}

app.use(
  cors({
    origin: (origin, callback) => {
      if (isAllowedOrigin(origin)) {
        callback(null, true);
      } else {
        console.error("[CORS] Blocked origin:", origin);
        callback(new Error("Not allowed by CORS"));
      }
    },
    credentials: true,
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization"],
  })
);

// ==========================================
// SECURITY
// ==========================================

app.use(helmet());

// ==========================================
// BODY PARSER
// ==========================================

app.use(
  express.json({
    limit: "1mb",
  })
);

// ==========================================
// RATE LIMITING
// ==========================================

const apiLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 100,
  standardHeaders: true,
  legacyHeaders: false,
});

app.use("/api", apiLimiter);

// ==========================================
// HEALTH CHECK
// ==========================================

app.get("/healthz", (req, res) => {
  return res.status(200).json({
    status: "ok",
  });
});

// ==========================================
// READINESS CHECK
// ==========================================

app.get("/readyz", async (req, res) => {
  const mongoose = require("mongoose");

  const ready = mongoose.connection.readyState === 1;

  return res.status(ready ? 200 : 503).json({
    ready,
  });
});

// ==========================================
// API ROUTES
// ==========================================

app.use("/api/auth", authRoutes);

app.use("/api/tasks", taskRoutes);

// ==========================================
// 404 HANDLER
// ==========================================

app.use((req, res) => {
  return res.status(404).json({
    message: "Not found",
  });
});

// ==========================================
// GLOBAL ERROR HANDLER
// ==========================================

app.use((err, req, res, next) => {
  console.error("[unhandled]", err);

  return res.status(500).json({
    message: "Internal server error",
  });
});

// ==========================================
// SERVER START
// ==========================================

async function start() {
  try {
    await connectDB();

    await connectRedis();

    app.listen(PORT, () => {
      console.log(`[server] Listening on port ${PORT}`);
    });
  } catch (err) {
    console.error("[server] Failed to start:", err);
    process.exit(1);
  }
}

start();

module.exports = app;