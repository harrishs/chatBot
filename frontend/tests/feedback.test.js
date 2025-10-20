import test from "node:test";
import assert from "node:assert/strict";
import {
        FEEDBACK_PREFIX,
        extractFeedbackComment,
        submitFeedbackComment,
        processFeedbackCommand,
} from "../src/utils/feedback.js";

const noop = () => {};

test("extractFeedbackComment parses feedback content", () => {
        assert.equal(extractFeedbackComment("/feedback Loving the updates"), "Loving the updates");
        assert.equal(extractFeedbackComment("/feedback    needs more docs"), "needs more docs");
        assert.equal(extractFeedbackComment("not a command"), null);
});

test("submitFeedbackComment sends comment-only payload", async () => {
        const requests = [];
        const apiClient = {
                post: async (url, body) => {
                        requests.push({ url, body });
                        return { data: { message: "Thanks for your feedback!" } };
                },
        };

        const result = await submitFeedbackComment({
                apiClient,
                chatbotId: "12",
                comment: "Great answers",
        });

        assert.deepEqual(requests, [
                {
                        url: "/chatbots/12/chat/",
                        body: { query: FEEDBACK_PREFIX, comment: "Great answers" },
                },
        ]);
        assert.equal(result.message, "Thanks for your feedback!");
});

test("processFeedbackCommand stores acknowledgement and clears query", async () => {
        let notice;
        let cleared = false;
        const apiClient = {
                post: async () => ({ data: { message: "Received loud and clear" } }),
        };

        const handled = await processFeedbackCommand({
                trimmedQuery: "/feedback Stellar support",
                apiClient,
                chatbotId: "9",
                setNotice: (value) => {
                        notice = value;
                },
                setQuery: () => {
                        cleared = true;
                },
        });

        assert.equal(handled, true);
        assert.equal(notice, "Received loud and clear");
        assert.equal(cleared, true);
});

test("processFeedbackCommand rejects empty comments", async () => {
        let notice = "";
        let cleared = false;

        const handled = await processFeedbackCommand({
                trimmedQuery: "/feedback   ",
                apiClient: { post: noop },
                chatbotId: "9",
                setNotice: (value) => {
                        notice = value;
                },
                setQuery: () => {
                        cleared = true;
                },
        });

        assert.equal(handled, true);
        assert.equal(notice, "Please provide feedback after /feedback.");
        assert.equal(cleared, false);
});

test("processFeedbackCommand ignores regular chat input", async () => {
        const handled = await processFeedbackCommand({
                trimmedQuery: "How are you?",
                apiClient: { post: noop },
                chatbotId: "9",
                setNotice: noop,
                setQuery: noop,
        });

        assert.equal(handled, false);
});
