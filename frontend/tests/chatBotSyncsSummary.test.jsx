import test, { mock } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../src/context/AuthContext.jsx";

const noop = () => {};

const apiStub = {
        get: async () => ({ data: [] }),
        post: async () => ({ data: {} }),
        put: async () => ({ data: {} }),
        patch: async () => ({ data: {} }),
        delete: async () => ({ data: {} }),
};

mock.module("../src/api/axios.js", () => ({ default: apiStub }));
mock.module("../src/context/NotificationsContext.jsx", () => ({
        useNotifications: () => ({ notify: noop }),
}));

const adminAuth = {
        user: { role: "admin" },
        initializing: false,
        login: noop,
        logout: noop,
        refreshSession: noop,
};

test("ChatBotSyncs renders summary and empty state guidance", async () => {
        const { default: ChatBotSyncs } = await import("../src/pages/ChatBotSyncs.jsx");

        const html = renderToStaticMarkup(
                <AuthContext.Provider value={adminAuth}>
                        <MemoryRouter initialEntries={["/chatbots/1/syncs"]}>
                                <ChatBotSyncs
                                        initialData={{
                                                jiraSyncs: [],
                                                confluenceSyncs: [],
                                                gitSyncs: [],
                                        }}
                                />
                        </MemoryRouter>
                </AuthContext.Provider>,
        );

        assert.ok(html.includes("Sync Summary"));
        assert.ok(html.includes("Total syncs:"));
        assert.ok(html.includes("No syncs configured yet."));
        assert.ok(html.includes("No Jira syncs have been configured yet."));
        assert.ok(html.includes("href=\"/credentials\""));
});

test("ChatBotSyncs summary reflects most recent runs and failures", async () => {
        const { default: ChatBotSyncs } = await import("../src/pages/ChatBotSyncs.jsx");

        const initialData = {
                jiraSyncs: [
                        {
                                id: 1,
                                board_url: "https://jira.example.com/board",
                                sync_status: "succeeded",
                                last_sync_time: "2024-05-01T12:00:00Z",
                                next_sync_at: null,
                        },
                ],
                confluenceSyncs: [
                        {
                                id: 2,
                                space_url: "https://confluence.example.com",
                                sync_status: "failed",
                                sync_status_message: "Permissions error",
                                last_sync_time: "2024-05-02T15:30:00Z",
                        },
                ],
                gitSyncs: [
                        {
                                id: 3,
                                repo_full_name: "org/repo",
                                branch: "main",
                                sync_status: "queued",
                                next_sync_at: "2024-05-03T10:00:00Z",
                        },
                ],
        };

        const html = renderToStaticMarkup(
                <AuthContext.Provider value={adminAuth}>
                        <MemoryRouter initialEntries={["/chatbots/1/syncs"]}>
                                <ChatBotSyncs initialData={initialData} />
                        </MemoryRouter>
                </AuthContext.Provider>,
        );

        assert.ok(html.includes("Total syncs:</strong> 3"));
        assert.ok(html.includes("Failing syncs:</strong> 1"));
        assert.ok(html.includes("Running or queued:</strong> 1"));
        assert.ok(
                html.includes(
                        "Confluence (https://confluence.example.com) — May 2, 2024, 3:30 PM UTC",
                ),
        );
        assert.ok(
                html.includes(
                        "Git (org/repo (main)) — May 3, 2024, 10:00 AM UTC",
                ),
        );
        assert.ok(html.includes("Last failure:</strong> Confluence (https://confluence.example.com) — Permissions error"));
        assert.ok(html.includes("Jira: 1 total, 0 failing, 0 running"));
        assert.ok(html.includes("Git: 1 total, 0 failing, 1 running"));
});
