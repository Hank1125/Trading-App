import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // pg and the Prisma adapter must stay as Node modules on the server.
  serverExternalPackages: ["pg", "@prisma/adapter-pg"],
};

export default nextConfig;
