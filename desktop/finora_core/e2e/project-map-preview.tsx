import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/500.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import "../src/design/tokens.css";
import "../src/design/app.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { DataSourceContext } from "../src/data/hooks";
import { DevDataSource } from "../src/data/devSource";
import { ProjectMapLauncher } from "../src/workspace/ProjectMap";
import { projectGraphSchema } from "../src/workspace/projectGraph";
import fixture from "./project-map-fixture.json";
const source = Object.assign(new DevDataSource({ simulate: false, latency: 0 }), {
  getProjectGraph: async () => projectGraphSchema.parse(fixture),
  analyzeProjectGraph: async () => projectGraphSchema.parse(fixture),
  createProjectConnection: async () => ({
    endpointPath: "/test/project/mcp",
    endpoint: "https://example.invalid/test/project/mcp",
    token: "test-only-no-access",
    expiresAt: "2026-10-13T12:00:00Z",
    readOnly: true as const,
  }),
  revokeProjectConnection: async () => undefined,
});
const root = document.getElementById("root");
if (!root) throw new Error("Preview root missing");
createRoot(root).render(
  <QueryClientProvider client={new QueryClient()}>
    <DataSourceContext.Provider value={source}>
      <ProjectMapLauncher conversationId="test" />
    </DataSourceContext.Provider>
  </QueryClientProvider>,
);
