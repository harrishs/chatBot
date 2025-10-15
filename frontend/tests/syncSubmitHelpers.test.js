import test from "node:test";
import assert from "node:assert/strict";
import {
        handleJiraSubmit,
        handleConfluenceSubmit,
        SYNC_MISSING_CREDENTIAL_MESSAGE,
} from "../src/pages/syncSubmitHelpers.js";

test("handleJiraSubmit blocks submission without credential", async () => {
        let prevented = false;
        const event = {
                preventDefault() {
                        prevented = true;
                },
        };

        const postCalls = [];
        let alertMessage = null;
        let resetCalled = false;
        let reloadCalled = false;

        const result = await handleJiraSubmit({
                event,
                newJira: {
                        board_url: "https://example.com/board",
                        credential_id: "",
                        sync_interval: "manual",
                },
                chatBotId: "123",
                apiClient: {
                        post: (...args) => {
                                postCalls.push(args);
                                return Promise.resolve();
                        },
                },
                alertFn: (message) => {
                        alertMessage = message;
                },
                resetForm: () => {
                        resetCalled = true;
                },
                reload: () => {
                        reloadCalled = true;
                        return Promise.resolve();
                },
                logError: () => {},
        });

        assert.equal(prevented, true, "submit handler should prevent default form submission");
        assert.deepEqual(postCalls, [], "no network calls should be made");
        assert.equal(alertMessage, SYNC_MISSING_CREDENTIAL_MESSAGE, "user should see validation alert");
        assert.equal(resetCalled, false, "form should not reset on validation failure");
        assert.equal(reloadCalled, false, "data reload should not trigger on validation failure");
        assert.deepEqual(result, { success: false, reason: "missing-credential" });
});

test("handleConfluenceSubmit blocks submission without credential", async () => {
        let prevented = false;
        const event = {
                preventDefault() {
                        prevented = true;
                },
        };

        const postCalls = [];
        let alertMessage = null;
        let resetCalled = false;
        let reloadCalled = false;

        const result = await handleConfluenceSubmit({
                event,
                newConfluence: {
                        space_url: "https://example.com/wiki",
                        credential_id: "",
                        sync_interval: "manual",
                },
                chatBotId: "123",
                apiClient: {
                        post: (...args) => {
                                postCalls.push(args);
                                return Promise.resolve();
                        },
                },
                alertFn: (message) => {
                        alertMessage = message;
                },
                resetForm: () => {
                        resetCalled = true;
                },
                reload: () => {
                        reloadCalled = true;
                        return Promise.resolve();
                },
                logError: () => {},
        });

        assert.equal(prevented, true, "submit handler should prevent default form submission");
        assert.deepEqual(postCalls, [], "no network calls should be made");
        assert.equal(alertMessage, SYNC_MISSING_CREDENTIAL_MESSAGE, "user should see validation alert");
        assert.equal(resetCalled, false, "form should not reset on validation failure");
        assert.equal(reloadCalled, false, "data reload should not trigger on validation failure");
        assert.deepEqual(result, { success: false, reason: "missing-credential" });
});
