import test, { mock } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthContext } from "../src/context/AuthContext.jsx";

const noop = () => {};
const authValue = {
        user: { role: "viewer" },
        initializing: false,
        login: noop,
        logout: noop,
        refreshSession: noop,
};

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

test("ChatBots renders read-only guidance for viewers", async () => {
        const { default: ChatBots } = await import("../src/pages/ChatBots.jsx");

        const html = renderToStaticMarkup(
                <AuthContext.Provider value={authValue}>
                        <MemoryRouter>
                                <ChatBots />
                        </MemoryRouter>
                </AuthContext.Provider>,
        );

        assert.ok(html.includes("You have read-only access."));
        assert.ok(html.includes("manage chatbots."));
        assert.ok(!html.includes("Create ChatBot"));
        assert.ok(!html.includes("Update"));
});

test("Credentials page hides management controls for viewers", async () => {
        const { default: Credentials } = await import("../src/pages/Credentials.jsx");

        const html = renderToStaticMarkup(
                <AuthContext.Provider value={authValue}>
                        <Credentials />
                </AuthContext.Provider>,
        );

        assert.ok(html.includes("manage credentials."));
        assert.ok(!html.includes("Save Credential"));
        assert.ok(!html.includes("Add Git Credential"));
});

test("ChatBotSyncs only renders status information for viewers", async () => {
        const { default: ChatBotSyncs } = await import("../src/pages/ChatBotSyncs.jsx");

        const html = renderToStaticMarkup(
                <AuthContext.Provider value={authValue}>
                        <MemoryRouter initialEntries={["/chatbots/1/syncs"]}>
                                <Routes>
                                        <Route path="/chatbots/:chatBotId/syncs" element={<ChatBotSyncs />} />
                                </Routes>
                        </MemoryRouter>
                </AuthContext.Provider>,
        );

        assert.ok(html.includes("manage sync settings."));
        assert.ok(!html.includes("Add Jira Sync"));
        assert.ok(!html.includes("Add Confluence Sync"));
        assert.ok(!html.includes("Add Git Sync"));
});
