import { z } from "zod";

const intFromEnv = (min: number, max: number) =>
  z
    .string()
    .regex(/^\d+$/, "must be a whole number")
    .transform(Number)
    .pipe(z.number().int().min(min).max(max));

const postgresUrl = z
  .string()
  .refine((v) => /^postgres(ql)?:\/\//.test(v), "must be a postgresql:// URL");

const schema = z.object({
  DATABASE_URL: postgresUrl,
  DATABASE_URL_TEST: postgresUrl.optional(),
  DATA_MODE: z.enum(["mock", "live"]),
  R6_DISSECT_BIN: z.string().min(1),
  UPLOAD_DIR: z.string().min(1),
  MAX_UPLOAD_MB: intFromEnv(1, 2048),
  MIN_SNAPSHOT_ROUNDS: intFromEnv(1, 1_000_000),
  SNAPSHOT_DEBOUNCE_SECONDS: intFromEnv(0, 3600),
  ADMIN_TOKEN: z.string().min(24, "must be at least 24 characters"),
});

export type Config = z.infer<typeof schema>;

export class ConfigError extends Error {}

/** Parses an env object. Throws a readable ConfigError listing every invalid variable (never their values). */
export function parseConfig(env: Record<string, string | undefined>): Config {
  const result = schema.safeParse(env);
  if (!result.success) {
    const problems = result.error.issues.map((i) => `  ${i.path.join(".")}: ${i.message}`);
    throw new ConfigError(`Invalid configuration:\n${problems.join("\n")}`);
  }
  return result.data;
}

let cached: Config | undefined;

export function getConfig(): Config {
  cached ??= parseConfig(process.env);
  return cached;
}
