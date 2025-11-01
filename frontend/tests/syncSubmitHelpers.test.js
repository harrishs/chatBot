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
        const notifications = [];
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
                notifier: (notification) => {
                        notifications.push(notification);
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
        assert.deepEqual(
                notifications,
                [
                        {
                                type: "error",
                                message: SYNC_MISSING_CREDENTIAL_MESSAGE,
                                placement: "inline",
                                autoDismiss: null,
                        },
                ],
                "user should see validation notification"
        );
        assert.equal(resetCalled, false, "form should not reset on validation failure");
        assert.equal(reloadCalled, false, "data reload should not trigger on validation failure");
        assert.deepEqual(result, {
                success: false,
                reason: "missing-credential",
                notification: notifications[0],
        });
});

test("handleConfluenceSubmit blocks submission without credential", async () => {
        let prevented = false;
        const event = {
                preventDefault() {
                        prevented = true;
                },
        };

        const postCalls = [];
        const notifications = [];
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
                notifier: (notification) => {
                        notifications.push(notification);
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
        assert.deepEqual(
                notifications,
                [
                        {
                                type: "error",
                                message: SYNC_MISSING_CREDENTIAL_MESSAGE,
                                placement: "inline",
                                autoDismiss: null,
                        },
                ],
                "user should see validation notification"
        );
        assert.equal(resetCalled, false, "form should not reset on validation failure");
        assert.equal(reloadCalled, false, "data reload should not trigger on validation failure");
        assert.deepEqual(result, {
                success: false,
                reason: "missing-credential",
                notification: notifications[0],
        });
});
