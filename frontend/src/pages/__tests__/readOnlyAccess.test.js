import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { build } from "esbuild";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

if (!globalThis.window) {
        globalThis.window = {};
}
if (!globalThis.window.alert) {
        globalThis.window.alert = () => {};
}
if (!globalThis.window.confirm) {
        globalThis.window.confirm = () => true;
}

const viewerAuthValue = {
        user: { role: "member", is_staff: false },
        initializing: false,
        login: async () => {},
        logout: async () => {},
        refreshSession: async () => {},
};

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "../../..");

async function loadModule(modulePath) {
        const absEntry = path.resolve(projectRoot, modulePath);
        const stubContents = `export const AuthContext = { Provider: ({ children }) => children };
export const AuthProvider = ({ children }) => children;
export function useAuth() { return ${JSON.stringify(viewerAuthValue)}; }
`;
        const result = await build({
                entryPoints: [absEntry],
                bundle: true,
                format: "esm",
                platform: "node",
                write: false,
                jsx: "automatic",
                jsxImportSource: "react",
                loader: { ".jsx": "jsx" },
                external: [
                        "react",
                        "react-dom",
                        "react-router",
                        "react-router-dom",
                        "axios",
                ],
                plugins: [
                        {
                                name: "auth-stub",
                                setup(buildInstance) {
                                        buildInstance.onResolve(
                                                { filter: /context\/AuthContext\.jsx$/ },
                                                () => ({ path: "auth-stub", namespace: "stub" }),
                                        );
                                        buildInstance.onLoad(
                                                { filter: /.*/, namespace: "stub" },
                                                () => ({ contents: stubContents, loader: "js" }),
                                        );
                                },
                        },
                ],
        });

        const [{ text }] = result.outputFiles;
        const tempDir = path.join(projectRoot, "src/.esbuild-tests");
        await fs.mkdir(tempDir, { recursive: true });
        const tempFile = path.join(
                tempDir,
                `esbuild-test-${Date.now()}-${Math.random().toString(36).slice(2)}.mjs`,
        );
        await fs.writeFile(tempFile, text, "utf8");
        try {
                return await import(pathToFileURL(tempFile).href);
        } finally {
                await fs.unlink(tempFile).catch(() => {});
        }
}

test("ChatBots page hides management controls for viewers", async () => {
        const [{ default: ChatBots }] = await Promise.all([
                loadModule("src/pages/ChatBots.jsx"),
        ]);

        const markup = renderToStaticMarkup(
                createElement(MemoryRouter, null, createElement(ChatBots, null)),
        );

        assert.ok(markup.includes("You have read-only access"));
        assert.ok(!markup.includes("<form"));
        assert.ok(!markup.includes("Create"));
});

test("Credentials page renders read-only guidance for viewers", async () => {
        const [{ default: Credentials }] = await Promise.all([
                loadModule("src/pages/Credentials.jsx"),
        ]);

        const markup = renderToStaticMarkup(
                createElement(MemoryRouter, null, createElement(Credentials, null)),
        );

        assert.ok(markup.includes("manage credentials"));
        assert.ok(!markup.includes("<form"));
        assert.ok(!markup.includes("Add Git Credential"));
});

test("ChatBotSyncs page only renders lists for viewers", async () => {
        const [{ default: ChatBotSyncs }] = await Promise.all([
                loadModule("src/pages/ChatBotSyncs.jsx"),
        ]);

        const markup = renderToStaticMarkup(
                createElement(
                        MemoryRouter,
                        { initialEntries: ["/chatbots/1/syncs"] },
                        createElement(
                                Routes,
                                null,
                                createElement(Route, {
                                        path: "/chatbots/:chatBotId/syncs",
                                        element: createElement(ChatBotSyncs, null),
                                }),
                        ),
                ),
        );

        assert.ok(markup.includes("manage sync configurations"));
        assert.ok(!markup.includes("<form"));
        assert.ok(!markup.includes("Add Jira Sync"));
});
