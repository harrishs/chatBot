import test from "node:test";
import assert from "node:assert/strict";
import {
        handleGitSubmit,
        GIT_MISSING_CREDENTIAL_MESSAGE,
} from "../src/pages/gitSubmitHelper.js";

test("handleGitSubmit blocks submission without credential", async () => {
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

        const result = await handleGitSubmit({
                event,
                newGit: {
                        repo_full_name: "owner/repo",
                        branch: "main",
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
        assert.equal(alertMessage, GIT_MISSING_CREDENTIAL_MESSAGE, "user should see validation alert");
        assert.equal(resetCalled, false, "form should not reset on validation failure");
        assert.equal(reloadCalled, false, "data reload should not trigger on validation failure");
        assert.deepEqual(result, { success: false, reason: "missing-credential" });
});
