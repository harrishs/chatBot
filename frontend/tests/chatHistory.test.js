import test from "node:test";
import assert from "node:assert/strict";
import { buildChatRequest, buildChatHistory } from "../src/utils/chatHistory.js";

test("buildChatHistory pairs user and assistant turns", () => {
        const messages = [
                { role: "user", content: "Hello" },
                { role: "assistant", content: "Hi there" },
                { role: "user", content: "How are you?" },
                { role: "assistant", content: "Doing great!" },
        ];

        const history = buildChatHistory(messages, 7);

        assert.deepEqual(history, [
                { chatbot_id: 7, user: "Hello", assistant: "Hi there" },
                { chatbot_id: 7, user: "How are you?", assistant: "Doing great!" },
        ]);
});

test("buildChatRequest includes history payload", () => {
        const messages = [
                { role: "user", content: "Hi" },
                { role: "assistant", content: "Hello" },
        ];

        const { url, body } = buildChatRequest({ id: "42", messages, query: "Next question" });

        assert.equal(url, "/chatbots/42/chat/");
        assert.deepEqual(body, {
                query: "Next question",
                history: [{ chatbot_id: 42, user: "Hi", assistant: "Hello" }],
        });
});

test("buildChatHistory skips incomplete pairs", () => {
        const messages = [
                { role: "user", content: "Only user" },
        ];

        const history = buildChatHistory(messages, 9);

        assert.deepEqual(history, []);
});
