export function developmentLoginEnabled(environment: NodeJS.ProcessEnv = process.env) {
  return environment.NODE_ENV === "development" && environment.EDUAGENT_FRONTEND_MODE === "development" && environment.EDUAGENT_FRONTEND_DEV_AUTH === "true";
}
export function developmentAliases(environment: NodeJS.ProcessEnv = process.env) { return (environment.EDUAGENT_DEV_ALIASES ?? "").split(",").map((s) => s.trim()).filter(Boolean); }
