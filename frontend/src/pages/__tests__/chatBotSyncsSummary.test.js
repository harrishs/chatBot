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

const adminAuthValue = {
        user: { role: "admin", is_staff: true },
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
export function useAuth() { return ${JSON.stringify(adminAuthValue)}; }
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

test("ChatBotSyncs summary renders empty state guidance", async () => {
        const [{ default: ChatBotSyncs }] = await Promise.all([
                loadModule("src/pages/ChatBotSyncs.jsx"),
        ]);

        const markup = renderToStaticMarkup(
                createElement(
                        MemoryRouter,
                        { initialEntries: ["/chatbots/42/syncs"] },
                        createElement(
                                Routes,
                                null,
                                createElement(Route, {
                                        path: "/chatbots/:chatBotId/syncs",
                                        element: createElement(ChatBotSyncs, {
                                                initialSyncData: {
                                                        jiraSyncs: [],
                                                        confluenceSyncs: [],
                                                        gitSyncs: [],
                                                        credentials: [],
                                                        gitCredentials: [],
                                                        summary: null,
                                                },
                                        }),
                                }),
                        ),
                ),
        );
        assert.match(markup, /Total syncs configured:<\/strong>\s*0/);
        assert.match(markup, /Most recent sync:<\/strong>\s*No sync runs have completed yet\./);
        assert.match(markup, /Next scheduled run:<\/strong>\s*No upcoming scheduled runs\./);
        assert.ok(markup.includes("No Jira syncs configured yet."));
        assert.ok(markup.includes('href="/credentials"'));
});

test("ChatBotSyncs summary aggregates populated sync data", async () => {
        const [{ default: ChatBotSyncs }] = await Promise.all([
                loadModule("src/pages/ChatBotSyncs.jsx"),
        ]);

        const initialSyncData = {
                jiraSyncs: [
                        {
                                id: 1,
                                board_url: "https://example.atlassian.net/board",
                                sync_status: "failed",
                                sync_status_message: "Latest run failed",
                                last_sync_time: "2024-01-01T12:00:00Z",
                                next_sync_at: "2024-02-10T09:00:00Z",
                                credential: { id: 11, name: "Jira Cred" },
                                sync_interval: "daily",
                        },
                ],
                confluenceSyncs: [
                        {
                                id: 2,
                                space_url: "https://example.atlassian.net/wiki",
                                sync_status: "succeeded",
                                last_sync_time: "2024-02-02T11:00:00Z",
                                next_sync_at: "2024-02-20T10:00:00Z",
                                credential: { id: 11, name: "Jira Cred" },
                                sync_interval: "weekly",
                        },
                ],
                gitSyncs: [
                        {
                                id: 3,
                                repo_full_name: "owner/repo",
                                branch: "main",
                                sync_status: "running",
                                last_sync_time: "2024-02-01T09:00:00Z",
                                next_sync_at: "2024-02-01T15:00:00Z",
                                credential: { id: 21, name: "Git Cred" },
                                sync_interval: "daily",
                        },
                ],
                credentials: [{ id: 11, name: "Jira Cred" }],
                gitCredentials: [{ id: 21, name: "Git Cred" }],
                summary: null,
        };

        const markup = renderToStaticMarkup(
                createElement(
                        MemoryRouter,
                        { initialEntries: ["/chatbots/42/syncs"] },
                        createElement(
                                Routes,
                                null,
                                createElement(Route, {
                                        path: "/chatbots/:chatBotId/syncs",
                                        element: createElement(ChatBotSyncs, {
                                                initialSyncData,
                                        }),
                                }),
                        ),
                ),
        );
        assert.match(markup, /Total syncs configured:<\/strong>\s*3/);
        assert.match(markup, /Currently failing:<\/strong>\s*1/);
        assert.match(markup, /Active jobs:<\/strong>\s*1/);
        assert.match(markup, /Most recent sync:<\/strong>\s*Confluence • 2024-02-02 11:00 UTC/);
        assert.match(markup, /Next scheduled run:<\/strong>\s*Git Repository • 2024-02-01 15:00 UTC/);
        assert.match(markup, /Failing syncs:<\/strong>/);
        assert.ok(markup.includes("Jira: https://example.atlassian.net/board"));
        assert.match(markup, /Status breakdown:<\/strong>/);
        assert.ok(markup.includes("Failed: 1"));
        assert.ok(markup.includes("Running: 1"));
        assert.ok(markup.includes("Succeeded: 1"));
        assert.match(markup, /Per source:<\/strong>/);
        assert.ok(markup.includes("Jira: 1 configured"));
        assert.ok(markup.includes("Git Repository: 1 configured"));
        assert.ok(markup.includes("• 1 active"));
});
